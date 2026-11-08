import csv
import io
import json
import os
import re
import shlex
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import spotipy
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from spotipy.oauth2 import SpotifyOAuth
from ytmusicapi import YTMusic
from ytmusicapi.helpers import get_authorization, initialize_headers, sapisid_from_cookie
import ytmusicapi

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
DATA_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

YTM_AUTH_FILE = DATA_DIR / "ytm_browser.json"
SPOTIFY_CONFIG_FILE = DATA_DIR / "spotify_config.json"
SPOTIFY_CACHE_FILE = DATA_DIR / ".spotify_cache"
HISTORY_FILE = DATA_DIR / "migration_history.json"

app = FastAPI(title="Switch Music - Spotify to YouTube Music")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory store for active and recent migration jobs
migration_jobs: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers & Models
# ---------------------------------------------------------------------------

class YTMAuthPayload(BaseModel):
    headers_raw: str


class SpotifyConfigPayload(BaseModel):
    client_id: str
    client_secret: str
    redirect_uri: str = "http://127.0.0.1:8765/api/spotify/callback"


class TrackItem(BaseModel):
    title: str
    artist: str
    album: Optional[str] = ""
    duration_ms: Optional[int] = 0
    isrc: Optional[str] = ""
    spotify_uri: Optional[str] = ""


class MigrationRequest(BaseModel):
    target_mode: str = "new_playlist"  # "new_playlist" | "existing_playlist" | "liked_songs"
    playlist_title: Optional[str] = "My Spotify Playlist"
    playlist_description: Optional[str] = "Imported from Spotify via Switch Music"
    privacy_status: str = "PRIVATE"  # "PRIVATE" | "PUBLIC" | "UNLISTED"
    existing_playlist_id: Optional[str] = None
    skip_duplicates: bool = True
    tracks: List[TrackItem]


class DeduplicateTracksRequest(BaseModel):
    mode: str = "standard"  # "standard" | "strict"
    tracks: List[TrackItem]


class RemovePlaylistItem(BaseModel):
    videoId: str
    setVideoId: str


class RemoveDuplicatesRequest(BaseModel):
    items: List[RemovePlaylistItem]


def get_ytmusic() -> YTMusic:
    if not YTM_AUTH_FILE.exists():
        raise HTTPException(status_code=400, detail="尚未配置 YouTube Music 认证信息，请先在第一步完成连接。")
    try:
        return YTMusic(str(YTM_AUTH_FILE))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"YouTube Music 认证加载失败: {str(e)}")


def get_spotify_oauth() -> Optional[SpotifyOAuth]:
    if not SPOTIFY_CONFIG_FILE.exists():
        return None
    try:
        cfg = json.loads(SPOTIFY_CONFIG_FILE.read_text(encoding="utf-8"))
        client_id = cfg.get("client_id", "").strip()
        client_secret = cfg.get("client_secret", "").strip()
        redirect_uri = cfg.get("redirect_uri", "http://127.0.0.1:8765/api/spotify/callback").strip()
        if not client_id or not client_secret:
            return None
        scope = "user-library-read playlist-read-private playlist-read-collaborative"
        return SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=scope,
            cache_path=str(SPOTIFY_CACHE_FILE),
            open_browser=False,
        )
    except Exception:
        return None


def get_spotify_client() -> spotipy.Spotify:
    auth_manager = get_spotify_oauth()
    if not auth_manager:
        raise HTTPException(status_code=400, detail="尚未配置 Spotify Client ID & Secret。")
    token_info = auth_manager.validate_token(auth_manager.cache_handler.get_cached_token())
    if not token_info:
        raise HTTPException(status_code=401, detail="Spotify 尚未完成 OAuth 授权登录或登录已过期。")
    return spotipy.Spotify(auth_manager=auth_manager)


def parse_csv_tracks(content_bytes: bytes, filename: str = "") -> Dict[str, Any]:
    # Decode with utf-8-sig to handle BOM from Exportify
    try:
        text = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content_bytes.decode("latin-1", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    tracks = []
    for row in reader:
        # Normalize keys (strip whitespace and lower-case for matching)
        norm = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items() if k}

        title = (
            norm.get("track name")
            or norm.get("title")
            or norm.get("name")
            or norm.get("track")
            or norm.get("歌曲名")
            or norm.get("标题")
            or ""
        )
        artist = (
            norm.get("artist name(s)")
            or norm.get("artist name")
            or norm.get("artists")
            or norm.get("artist")
            or norm.get("歌手")
            or norm.get("艺术家")
            or ""
        )
        album = (
            norm.get("album name")
            or norm.get("album")
            or norm.get("专辑")
            or ""
        )
        duration_raw = (
            norm.get("duration (ms)")
            or norm.get("track duration (ms)")
            or norm.get("duration_ms")
            or "0"
        )
        isrc = norm.get("isrc") or ""
        uri = norm.get("track uri") or norm.get("spotify uri") or norm.get("uri") or ""

        # Exportify joins multiple artists with ";" or ","
        artist_clean = artist.replace(";", ", ")

        try:
            duration_ms = int(float(duration_raw))
        except ValueError:
            duration_ms = 0

        if title:
            tracks.append(
                {
                    "title": title,
                    "artist": artist_clean,
                    "album": album,
                    "duration_ms": duration_ms,
                    "isrc": isrc,
                    "spotify_uri": uri,
                }
            )

    suggested_name = Path(filename).stem.replace("_", " ").title() if filename else "Imported Spotify Playlist"
    if suggested_name.lower() == "liked" or "liked" in suggested_name.lower():
        suggested_name = "Spotify Liked Songs"

    return {
        "playlist_name": suggested_name,
        "count": len(tracks),
        "tracks": tracks,
    }


def parse_duration_seconds(duration_str: Optional[str]) -> int:
    if not duration_str:
        return 0
    parts = duration_str.strip().split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        pass
    return 0


_TRAD_SIMP_RAW = (
    "澤泽 樣样 東东 貓猫 後后 來来 倫伦 傑杰 孫孙 劉刘 趙赵 愛爱 裡里 獨独 視视 劇剧 專专 輯辑 "
    "雲云 煙烟 風风 戀恋 夢梦 淚泪 橋桥 傷伤 離离 開开 華华 陳陈 張张 學学 鄧邓 蘇苏 綠绿 樂乐 "
    "團团 隊队 國国 語语 粵粤 歲岁 時时 間间 記记 憶忆 誰谁 說说 話话 讓让 變变 過过 還还 沒没 "
    "對对 錯错 難难 聽听 見见 親亲 擁拥 藍蓝 紅红 黃黄 雙双 飛飞 鳥鸟 魚鱼 馬马 島岛 灣湾 臺台 "
    "鐵铁 號号 樓楼 門门 關关 閉闭 燈灯 聲声 響响 詞词 會会 場场 節节 點点 線线 網网 絡络 萬万 "
    "與与 絲丝 兩两 嚴严 喪丧 個个 豐丰 臨临 為为 麗丽 舉举 麼么 義义 烏乌 喬乔 習习 鄉乡 書书 "
    "買买 亂乱 乾干 爭争 虧亏 亞亚 產产 億亿 僅仅 從从 倉仓 們们 價价 眾众 優优 偉伟 傳传 偽伪 "
    "體体 餘余 俠侠 侶侣 偵侦 側侧 僑侨 儂侬 儘尽 兒儿 兌兑 黨党 蘭兰 養养 獸兽 內内 岡冈 冊册 "
    "寫写 軍军 農农 馮冯 沖冲 決决 況况 凍冻 淨净 淒凄 涼凉 減减 湊凑 幾几 鳳凤 憑凭 凱凯 擊击 "
    "別别 刪删 剮剐 劍剑 劑剂 創创 勸劝 辦办 務务 動动 勵励 勁劲 勞劳 勢势 勳勋 區区 醫医 協协 "
    "單单 賣卖 盧卢 衛卫 卻却 廠厂 廳厅 歷历 厲厉 壓压 厭厌 廁厕 廂厢 廈厦 廚厨 縣县 參参 發发 "
    "葉叶 嘆叹 嚇吓 呂吕 嗎吗 噸吨 啟启 吳吴 嘔呕 員员 嗚呜 詠咏 嚨咙 嚀咛 嘯啸 嘩哗 噓嘘 囑嘱 "
    "囉啰 圖图 圍围 園园 圓圆 聖圣 壞坏 塊块 堅坚 壇坛 壩坝 塢坞 墳坟 墜坠 壘垒 墾垦 壯壮 殼壳 "
    "壺壶 壽寿 處处 備备 復复 夠够 頭头 誇夸 夾夹 奪夺 奮奋 獎奖 奧奥 妝妆 婦妇 媽妈 嫵妩 嫗妪 "
    "姍姗 姊姐 婭娅 嬈娆 嬌娇 寧宁 寶宝 實实 寵宠 審审 憲宪 宮宫 寬宽 賓宾 寢寝 尋寻 導导 將将 "
    "爾尔 塵尘 嚐尝 堯尧 尷尴 屍尸 盡尽 層层 屜屉 屆届 屬属 屢屡 嶼屿 嶄崭 嶺岭 嶽岳 巔巅 鞏巩 "
    "幣币 帥帅 師师 帳帐 簾帘 幟帜 帶带 幀帧 幫帮 冪幂 廣广 莊庄 慶庆 廬庐 庫库 應应 廟庙 龐庞 "
    "廢废 異异 棄弃 弒弑 彌弥 彎弯 彈弹 強强 歸归 當当 錄录 彥彦 徹彻 徑径 徠徕 徵征 懺忏 憂忧 "
    "懷怀 態态 慫怂 悵怅 愴怆 憐怜 總总 懟怼 懇恳 惡恶 慟恸 愷恺 惻恻 惱恼 悅悦 懸悬 憫悯 驚惊 "
    "懼惧 慘惨 懲惩 憊惫 愜惬 慚惭 憚惮 慣惯 憤愤 憩憩 憾憾 懶懒 戲戏 戰战 戩戬 戶户 撲扑 執执 "
    "擴扩 掃扫 揚扬 擾扰 撫抚 拋抛 掄抡 搶抢 護护 報报 擔担 擬拟 攏拢 揀拣 攔拦 擰拧 撥拨 擇择 "
    "掛挂 摯挚 挾挟 撓挠 擋挡 掙挣 擠挤 揮挥 撈捞 損损 撿捡 換换 搗捣 據据 擄掳 擲掷 摻掺 攬揽 "
    "擱搁 摟搂 攪搅 攜携 攝摄 擺摆 搖摇 攤摊 撐撑 攆撵 敵敌 斂敛 數数 驅驱 驕骄 驗验 驛驿 驟骤 "
    "驢驴 髒脏 鬚须 髮发 鬧闹 鬱郁 魯鲁 鮮鲜 鯨鲸 鳴鸣 鷗鸥 鴉鸦 鴨鸭 鴦鸯 鴿鸽 鴻鸿 鵝鹅 鵬鹏 "
    "鵲鹊 鶯莺 鶴鹤 鸚鹦 鷹鹰 麥麦 齊齐 齒齿 齡龄 龍龙 龜龟 這这 進进 遠远 連连 遲迟 適适 選选 "
    "遜逊 遞递 週周 遊游 遙遥 遺遗 邊边 達达 遷迁 邁迈 運运 閃闪 問问 閒闲 聞闻 閱阅 闊阔 闌阑 "
    "隻只 雖虽 雜杂 雞鸡 電电 霧雾 靈灵 靜静 韓韩 韻韵 頂顶 順顺 須须 頌颂 預预 頑顽 頓顿 領领 "
    "頸颈 頻频 顆颗 題题 額额 顏颜 願愿 類类 顧顾 顯显 飄飘 飛飞 飯饭 飲饮 飽饱 飾饰 館馆 饒饶 "
    "馳驰 駐驻 駛驶 駝驼 罵骂 駭骇 駱骆 駿骏 騎骑 騙骗 騰腾 騷骚 鬆松 鬍胡 鬢鬓 鬥斗 魚鱼 鯊鲨 "
    "鯉鲤 鯽鲫 鳥鸟 鴦鸯 鴻鸿 鵑鹃 鹹咸 鹽盐 麵面 裏里 妳你 於于 並并 鐘钟 鍾钟 製制 勝胜 檯台 "
    "颱台 嚮向 迴回 睏困 複复 覆复 慾欲 瞭了 藉借 藝艺 蘋苹 蟲虫 術术 裝装 觀观 覺觉 訂订 計计 "
    "訊讯 討讨 訓训 託托 許许 訴诉 診诊 註注 證证 評评 詢询 試试 詩诗 該该 詳详 誠诚 誌志 認认 "
    "誕诞 誘诱 誤误 課课 調调 談谈 請请 諒谅 論论 諸诸 諾诺 謀谋 謂谓 謊谎 謎谜 謙谦 講讲 謝谢 "
    "謠谣 謹谨 識识 譜谱 譯译 議议 譽誉 讀读 讚赞 豔艳 貝贝 貞贞 負负 財财 貢贡 貧贫 貨货 販贩 "
    "貪贪 貫贯 責责 貴贵 貶贬 貸贷 費费 貼贴 貿贸 賀贺 資资 賊贼 賜赐 賞赏 賠赔 賢贤 賤贱 賦赋 "
    "質质 賬账 賭赌 賴赖 賺赚 購购 賽赛 贈赠 贊赞 贏赢 贖赎 趕赶 跡迹 踐践 躍跃 軀躯 車车 軌轨 "
    "軟软 輕轻 載载 轎轿 輛辆 輝辉 輩辈 輪轮 輸输 轉转 轟轰 辭辞 辮辫 辯辩"
)
TRAD_TO_SIMP_MAP = str.maketrans(
    {tok[0]: tok[1] for tok in _TRAD_SIMP_RAW.split() if len(tok) == 2 and tok[0] != tok[1]}
)


def to_simplified(s: str) -> str:
    return (s or "").translate(TRAD_TO_SIMP_MAP)


def clean_str(s: str) -> str:
    s = to_simplified(s).lower()
    s = re.sub(r"\(.*?\)|\[.*?\]|（.*?）|【.*?】", "", s)
    s = re.sub(r"\s+-\s+.*?(?:remaster|version|mix|edit|live|original|ost|soundtrack).*", "", s)
    s = re.sub(r"feat\.?.*|ft\.?.*", "", s)
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+", " ", s)
    return s.strip()


def match_track_on_ytm(ytm: YTMusic, track: TrackItem) -> Optional[Dict[str, Any]]:
    """
    Search YouTube Music for the best match for a Spotify track.
    """
    primary_artist = track.artist.split(",")[0].strip() if track.artist else ""
    query = f"{track.title} {primary_artist}".strip()

    # 1. Try searching specifically for songs first
    try:
        song_results = ytm.search(query, filter="songs", limit=5)
    except Exception:
        song_results = []

    candidates = song_results or []

    # 2. Fallback to videos if no songs found
    if not candidates:
        try:
            video_results = ytm.search(query, filter="videos", limit=3)
            candidates = video_results or []
        except Exception:
            candidates = []

    if not candidates:
        return None

    target_title_clean = clean_str(track.title)
    target_artist_clean = clean_str(primary_artist)
    target_sec = (track.duration_ms // 1000) if track.duration_ms else 0

    best_candidate = None
    best_score = -999

    for idx, item in enumerate(candidates):
        video_id = item.get("videoId")
        if not video_id:
            continue

        score = 0
        # Rank bonus (top results from YTM search are usually strong)
        score += max(0, 15 - idx * 3)

        # Song vs Video bonus
        if item.get("resultType") == "song":
            score += 10

        cand_title = item.get("title", "")
        cand_title_clean = clean_str(cand_title)
        cand_artists = ", ".join([a.get("name", "") for a in item.get("artists", [])])
        cand_artist_clean = clean_str(cand_artists)

        # Title similarity
        if target_title_clean and cand_title_clean:
            if target_title_clean == cand_title_clean:
                score += 30
            elif target_title_clean in cand_title_clean or cand_title_clean in target_title_clean:
                score += 18

        # Artist similarity
        if target_artist_clean and cand_artist_clean:
            if target_artist_clean in cand_artist_clean or cand_artist_clean in target_artist_clean:
                score += 25

        # Duration proximity
        cand_sec = item.get("duration_seconds") or parse_duration_seconds(item.get("duration"))
        if target_sec > 0 and cand_sec > 0:
            diff = abs(target_sec - cand_sec)
            if diff <= 3:
                score += 15
            elif diff <= 10:
                score += 8
            elif diff > 60:
                score -= 15

        if score > best_score:
            best_score = score
            best_candidate = {
                "videoId": video_id,
                "title": cand_title,
                "artist": cand_artists,
                "album": (item.get("album") or {}).get("name", "") if isinstance(item.get("album"), dict) else "",
                "resultType": item.get("resultType", "song"),
                "duration": item.get("duration", ""),
                "score": score,
            }

    return best_candidate


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Switch Music UI is being prepared...</h1>")
    return FileResponse(str(index_file))


# --- YouTube Music Auth ---

@app.get("/api/ytm/status")
async def ytm_status():
    if not YTM_AUTH_FILE.exists():
        return {"connected": False, "message": "未连接"}
    try:
        ytm = YTMusic(str(YTM_AUTH_FILE))
        # Quick lightweight check: fetch library playlists (limit 5)
        playlists = ytm.get_library_playlists(limit=10)
        return {
            "connected": True,
            "message": "已成功连接 YouTube Music",
            "playlists_count": len(playlists) if playlists else 0,
        }
    except Exception as e:
        return {
            "connected": False,
            "message": f"认证文件无效或已过期: {str(e)}",
        }


def build_ytm_headers_from_any_input(raw: str) -> Dict[str, str]:
    raw = raw.strip()
    if raw.startswith("fetch(") and '"cookie"' not in raw.lower():
        raise ValueError("检测到你复制的是普通「Copy as fetch」（浏览器出于安全限制不会在其中包含 Cookie）。请右键请求选择「Copy → Copy as cURL」！")

    user_headers: Dict[str, str] = {}

    # 1. JSON array (Cookie-Editor export) or JSON dict
    if raw.startswith("[") or raw.startswith("{"):
        try:
            parsed_json = json.loads(raw)
            if isinstance(parsed_json, list):
                pairs = [
                    f"{item['name']}={item['value']}"
                    for item in parsed_json
                    if isinstance(item, dict) and "name" in item and "value" in item
                ]
                if pairs:
                    user_headers["cookie"] = "; ".join(pairs)
            elif isinstance(parsed_json, dict):
                for k, v in parsed_json.items():
                    if isinstance(v, str):
                        user_headers[k.lower().strip()] = v.strip()
        except Exception:
            pass

    # 2. Netscape cookies.txt format
    if "cookie" not in user_headers and ("\tTRUE\t" in raw or "\tFALSE\t" in raw or "# Netscape HTTP Cookie File" in raw):
        pairs = []
        for line in raw.splitlines():
            line_s = line.strip()
            if not line_s or line_s.startswith("#"):
                continue
            parts = line_s.split("\t")
            if len(parts) >= 7:
                pairs.append(f"{parts[5].strip()}={parts[6].strip()}")
        if pairs:
            user_headers["cookie"] = "; ".join(pairs)

    # 3. Copy as cURL (Chrome / Safari / Firefox / Edge)
    if "cookie" not in user_headers and raw.lstrip().startswith("curl "):
        joined = re.sub(r"\\\r?\n", " ", raw)
        joined = re.sub(r"(?<=\s)\$'", "'", joined)
        try:
            tokens = shlex.split(joined)
            i = 0
            while i < len(tokens):
                tok = tokens[i]
                if tok in ("-H", "--header") and i + 1 < len(tokens):
                    h = tokens[i + 1]
                    if ":" in h:
                        k, v = h.split(":", 1)
                        user_headers[k.strip().lower()] = v.strip()
                    i += 2
                    continue
                if tok in ("-b", "--cookie") and i + 1 < len(tokens):
                    user_headers["cookie"] = tokens[i + 1].strip()
                    i += 2
                    continue
                i += 1
        except ValueError:
            # Fallback regex if quotes were truncated while copying
            for m in re.finditer(r"(?:-H|--header)\s+(?:'([^']*)'|\"([^\"]*)\")", joined):
                h = m.group(1) or m.group(2) or ""
                if ":" in h:
                    k, v = h.split(":", 1)
                    user_headers[k.strip().lower()] = v.strip()
            for m in re.finditer(r"(?:-b|--cookie)\s+(?:'([^']*)'|\"([^\"]*)\")", joined):
                c = m.group(1) or m.group(2) or ""
                if c:
                    user_headers["cookie"] = c.strip()

    # 4. Copy as fetch (Node.js)
    if "cookie" not in user_headers and raw.startswith("fetch("):
        m = re.search(r'"cookie"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.IGNORECASE)
        if m:
            user_headers["cookie"] = bytes(m.group(1), "utf-8").decode("unicode_escape")
        m_auth = re.search(r'"x-goog-authuser"\s*:\s*"([^"]*)"', raw, re.IGNORECASE)
        if m_auth:
            user_headers["x-goog-authuser"] = m_auth.group(1)

    # 5. Raw Request Headers (1-line or Chrome 2-line format) or raw Cookie string
    if "cookie" not in user_headers:
        if "__Secure-3PAPISID=" in raw and "\n" not in raw and not raw.lower().startswith("cookie:"):
            user_headers["cookie"] = raw.strip()
        else:
            remembered_key = ""
            for line in raw.splitlines():
                line_s = line.strip()
                if not line_s or line_s.startswith(":"):
                    continue
                if ": " in line_s:
                    k, v = line_s.split(": ", 1)
                    user_headers[k.strip().lower()] = v.strip()
                    remembered_key = ""
                elif line_s.endswith(":"):
                    remembered_key = line_s[:-1].strip().lower()
                elif remembered_key:
                    user_headers[remembered_key] = line_s
                    remembered_key = ""
                elif ":" in line_s and not line_s.lower().startswith(("http:", "https:")):
                    k, v = line_s.split(":", 1)
                    user_headers[k.strip().lower()] = v.strip()

    cookie = user_headers.get("cookie", "").strip()
    if not cookie:
        raise ValueError("未能从粘贴的内容中提取到 Cookie。请在 Network 面板右键请求 → 选择「Copy → Copy as cURL」后重试。")

    if "__Secure-3PAPISID" not in cookie:
        raise ValueError("Cookie 中缺少登录凭据 (__Secure-3PAPISID)，请确认你已在 music.youtube.com 登录 Google 账号。")

    sapisid = sapisid_from_cookie(cookie)
    ignore_headers = {"host", "content-length", "accept-encoding", "priority"}
    cleaned_user_headers: Dict[str, str] = {}
    for k, v in user_headers.items():
        kl = k.lower().strip()
        if not kl or kl.startswith(":") or kl.startswith("sec-") or kl in ignore_headers:
            continue
        cleaned_user_headers[kl] = str(v).strip()

    final_headers: Dict[str, str] = dict(cleaned_user_headers)
    for k, v in dict(initialize_headers()).items():
        final_headers[k.lower()] = str(v)

    final_headers["cookie"] = cookie
    final_headers["x-goog-authuser"] = cleaned_user_headers.get("x-goog-authuser", "0")
    final_headers["origin"] = "https://music.youtube.com"
    final_headers["x-origin"] = "https://music.youtube.com"
    final_headers["authorization"] = get_authorization(f"{sapisid} https://music.youtube.com")
    return final_headers


@app.post("/api/ytm/auth")
async def ytm_setup_auth(payload: YTMAuthPayload):
    raw = payload.headers_raw.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="请粘贴有效的 Copy as cURL 命令、请求头或 Cookie。")

    try:
        final_headers = build_ytm_headers_from_any_input(raw)
        YTM_AUTH_FILE.write_text(json.dumps(final_headers, indent=2), encoding="utf-8")
        # Verify connection works
        ytm = YTMusic(str(YTM_AUTH_FILE))
        playlists = ytm.get_library_playlists(limit=5)
        return {
            "success": True,
            "message": "YouTube Music 连接成功！",
            "playlists_count": len(playlists) if playlists else 0,
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"验证 YouTube Music 连接失败: {str(e)}",
        )


@app.get("/api/ytm/playlists")
async def ytm_get_playlists():
    ytm = get_ytmusic()
    try:
        playlists = ytm.get_library_playlists(limit=100)
        cleaned = []
        for p in playlists or []:
            pid = p.get("playlistId", "")
            # Skip auto-playlists "LM" (Liked Music) and "SE" (Saved Episodes)
            if pid and pid not in ("LM", "SE"):
                cleaned.append(
                    {
                        "playlistId": pid,
                        "title": p.get("title", "Untitled"),
                        "count": p.get("count", ""),
                    }
                )
        return {"playlists": cleaned}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"获取 YouTube Music 歌单失败: {str(e)}")


@app.get("/api/ytm/playlist/{playlist_id}/duplicates")
async def ytm_scan_playlist_duplicates(playlist_id: str, mode: str = "standard"):
    ytm = get_ytmusic()
    try:
        pl = ytm.get_playlist(playlist_id, limit=None)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"读取歌单曲目失败: {str(e)}")

    raw_tracks = pl.get("tracks") or []
    seen_vid: Dict[str, Dict[str, Any]] = {}
    seen_sig: Dict[tuple, Dict[str, Any]] = {}
    seen_title_dur: Dict[str, List[Dict[str, Any]]] = {}
    groups_map: Dict[int, Dict[str, Any]] = {}
    pos_to_gid: Dict[int, int] = {}
    next_gid = 1
    duplicates_count = 0

    for idx, t in enumerate(raw_tracks):
        if not t:
            continue
        pos = idx + 1
        vid = t.get("videoId") or ""
        set_vid = t.get("setVideoId") or ""
        title = t.get("title") or "Unknown"
        artists_list = [a.get("name", "") for a in (t.get("artists") or []) if a.get("name")]
        artist_str = ", ".join(artists_list)
        primary_artist = artists_list[0] if artists_list else ""
        album_str = (t.get("album") or {}).get("name", "") if isinstance(t.get("album"), dict) else ""
        duration_str = t.get("duration") or ""
        dur_sec = t.get("duration_seconds") or parse_duration_seconds(duration_str)

        info = {
            "position": pos,
            "videoId": vid,
            "setVideoId": set_vid,
            "can_remove": bool(vid and set_vid),
            "title": title,
            "artist": artist_str,
            "album": album_str,
            "duration": duration_str,
            "duration_seconds": dur_sec,
        }

        norm_t = clean_str(title)
        norm_a = clean_str(primary_artist)

        kept = None
        reason = ""
        reason_code = ""

        if vid and vid in seen_vid:
            kept = seen_vid[vid]
            reason = "完全相同歌曲 (同 ID)"
            reason_code = "exact_id"
        elif mode in ("standard", "deep") and norm_t and norm_a and (norm_t, norm_a) in seen_sig:
            kept = seen_sig[(norm_t, norm_a)]
            reason = "同名同歌手 (不同版本/简繁体)"
            reason_code = "same_song"
        elif mode == "deep" and len(norm_t) >= 2 and dur_sec > 0 and norm_t in seen_title_dur:
            for prev in seen_title_dur[norm_t]:
                if prev["duration_seconds"] > 0 and abs(prev["duration_seconds"] - dur_sec) <= 3:
                    kept = prev
                    reason = "同名且时长一致 (疑似中英译名/多版本)"
                    reason_code = "title_duration"
                    break

        if kept is not None:
            duplicates_count += 1
            kpos = kept["position"]
            if kpos not in pos_to_gid:
                gid = next_gid
                next_gid += 1
                pos_to_gid[kpos] = gid
                groups_map[gid] = {
                    "group_id": gid,
                    "reason": reason,
                    "reason_code": reason_code,
                    "items": [
                        {
                            **kept,
                            "reason": "最早出现",
                            "reason_code": reason_code,
                            "default_remove": False,
                        }
                    ],
                }
            else:
                gid = pos_to_gid[kpos]

            pos_to_gid[pos] = gid
            groups_map[gid]["items"].append(
                {
                    **info,
                    "reason": reason,
                    "reason_code": reason_code,
                    "default_remove": True,
                }
            )
        else:
            if vid:
                seen_vid[vid] = info
            if norm_t and norm_a and (norm_t, norm_a) not in seen_sig:
                seen_sig[(norm_t, norm_a)] = info
            if len(norm_t) >= 2 and dur_sec > 0:
                seen_title_dur.setdefault(norm_t, []).append(info)

    groups = list(groups_map.values())
    return {
        "playlist_id": playlist_id,
        "playlist_title": pl.get("title", "Playlist"),
        "total_tracks": len(raw_tracks),
        "unique_count": len(raw_tracks) - duplicates_count,
        "duplicates_count": duplicates_count,
        "groups_count": len(groups),
        "groups": groups,
    }


@app.post("/api/ytm/playlist/{playlist_id}/remove-duplicates")
async def ytm_remove_playlist_duplicates(playlist_id: str, payload: RemoveDuplicatesRequest):
    ytm = get_ytmusic()
    valid_items = [
        {"videoId": it.videoId, "setVideoId": it.setVideoId}
        for it in payload.items
        if it.videoId and it.setVideoId
    ]
    if not valid_items:
        raise HTTPException(status_code=400, detail="没有可移除的有效歌曲项（请确认你是该歌单的创建者）。")

    removed = 0
    try:
        for i in range(0, len(valid_items), 50):
            batch = valid_items[i : i + 50]
            res = ytm.remove_playlist_items(playlist_id, batch)
            if isinstance(res, str) and "SUCCEEDED" in res:
                removed += len(batch)
            elif isinstance(res, dict) and "SUCCEEDED" in str(res.get("status", "")):
                removed += len(batch)
            else:
                # Fallback one-by-one if batch had stale setVideoId
                for single in batch:
                    try:
                        r1 = ytm.remove_playlist_items(playlist_id, [single])
                        if "SUCCEEDED" in str(r1):
                            removed += 1
                    except Exception:
                        pass
            time.sleep(0.15)
        return {"success": True, "removed_count": removed}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"移除重复曲目失败: {str(e)}")


# --- Spotify OAuth & CSV ---

@app.get("/api/spotify/status")
async def spotify_status():
    cfg = {}
    if SPOTIFY_CONFIG_FILE.exists():
        try:
            cfg = json.loads(SPOTIFY_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    auth_manager = get_spotify_oauth()
    if not auth_manager:
        return {
            "configured": False,
            "authenticated": False,
            "client_id": cfg.get("client_id", ""),
            "redirect_uri": cfg.get("redirect_uri", "http://127.0.0.1:8765/api/spotify/callback"),
        }

    try:
        token_info = auth_manager.validate_token(auth_manager.cache_handler.get_cached_token())
        if token_info:
            sp = spotipy.Spotify(auth_manager=auth_manager)
            me = sp.current_user()
            return {
                "configured": True,
                "authenticated": True,
                "user_name": me.get("display_name") or me.get("id"),
                "client_id": cfg.get("client_id", ""),
                "redirect_uri": cfg.get("redirect_uri", "http://127.0.0.1:8765/api/spotify/callback"),
            }
    except Exception:
        pass

    return {
        "configured": True,
        "authenticated": False,
        "client_id": cfg.get("client_id", ""),
        "redirect_uri": cfg.get("redirect_uri", "http://127.0.0.1:8765/api/spotify/callback"),
    }


@app.post("/api/spotify/config")
async def spotify_save_config(payload: SpotifyConfigPayload):
    if not payload.client_id.strip() or not payload.client_secret.strip():
        raise HTTPException(status_code=400, detail="请填写完整的 Client ID 和 Client Secret。")
    data = {
        "client_id": payload.client_id.strip(),
        "client_secret": payload.client_secret.strip(),
        "redirect_uri": payload.redirect_uri.strip() or "http://127.0.0.1:8765/api/spotify/callback",
    }
    SPOTIFY_CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    auth_manager = get_spotify_oauth()
    auth_url = auth_manager.get_authorize_url() if auth_manager else ""
    return {"success": True, "auth_url": auth_url}


@app.get("/api/spotify/callback")
async def spotify_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    if error:
        return HTMLResponse(f"<h3>Spotify 授权失败: {error}</h3><p><a href='/'>返回应用</a></p>")
    if not code:
        return RedirectResponse("/")
    auth_manager = get_spotify_oauth()
    if not auth_manager:
        return HTMLResponse("<h3>未找到 Spotify 配置</h3><p><a href='/'>返回应用</a></p>")
    try:
        auth_manager.get_access_token(code, as_dict=False)
        return RedirectResponse("/?spotify_connected=1")
    except Exception as e:
        return HTMLResponse(f"<h3>获取 Spotify Token 失败: {str(e)}</h3><p><a href='/'>返回应用</a></p>")


@app.get("/api/spotify/playlists")
async def spotify_playlists():
    sp = get_spotify_client()
    try:
        items = []
        # Add virtual entry for Liked Songs
        saved = sp.current_user_saved_tracks(limit=1)
        liked_total = saved.get("total", 0) if saved else 0
        items.append(
            {
                "id": "liked_songs",
                "name": "❤️ 我喜欢的音乐 (Liked Songs)",
                "tracks_total": liked_total,
                "owner": "Me",
                "is_liked": True,
            }
        )

        # Fetch user playlists
        offset = 0
        while True:
            res = sp.current_user_playlists(limit=50, offset=offset)
            batch = res.get("items", []) if res else []
            for p in batch:
                if not p:
                    continue
                items.append(
                    {
                        "id": p.get("id"),
                        "name": p.get("name", "Untitled"),
                        "tracks_total": (p.get("tracks") or {}).get("total", 0),
                        "owner": (p.get("owner") or {}).get("display_name", ""),
                        "is_liked": False,
                    }
                )
            if not res or not res.get("next") or len(batch) < 50:
                break
            offset += 50

        return {"playlists": items}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"拉取 Spotify 歌单列表失败: {str(e)}")


@app.get("/api/spotify/playlist/{playlist_id}/tracks")
async def spotify_playlist_tracks(playlist_id: str):
    sp = get_spotify_client()
    tracks = []
    playlist_name = "Spotify Liked Songs" if playlist_id == "liked_songs" else "Spotify Playlist"

    try:
        if playlist_id == "liked_songs":
            offset = 0
            while True:
                res = sp.current_user_saved_tracks(limit=50, offset=offset)
                batch = res.get("items", []) if res else []
                for item in batch:
                    t = (item or {}).get("track")
                    if not t or t.get("is_local"):
                        continue
                    artists = ", ".join([a.get("name", "") for a in t.get("artists", []) if a.get("name")])
                    tracks.append(
                        {
                            "title": t.get("name", ""),
                            "artist": artists,
                            "album": (t.get("album") or {}).get("name", ""),
                            "duration_ms": t.get("duration_ms", 0),
                            "isrc": (t.get("external_ids") or {}).get("isrc", ""),
                            "spotify_uri": t.get("uri", ""),
                        }
                    )
                if not res or not res.get("next") or len(batch) < 50:
                    break
                offset += 50
        else:
            pl_info = sp.playlist(playlist_id, fields="name")
            if pl_info and pl_info.get("name"):
                playlist_name = pl_info["name"]

            offset = 0
            while True:
                res = sp.playlist_items(playlist_id, limit=100, offset=offset)
                batch = res.get("items", []) if res else []
                for item in batch:
                    t = (item or {}).get("track")
                    if not t or t.get("is_local"):
                        continue
                    artists = ", ".join([a.get("name", "") for a in t.get("artists", []) if a.get("name")])
                    tracks.append(
                        {
                            "title": t.get("name", ""),
                            "artist": artists,
                            "album": (t.get("album") or {}).get("name", ""),
                            "duration_ms": t.get("duration_ms", 0),
                            "isrc": (t.get("external_ids") or {}).get("isrc", ""),
                            "spotify_uri": t.get("uri", ""),
                        }
                    )
                if not res or not res.get("next") or len(batch) < 100:
                    break
                offset += 100

        return {
            "playlist_name": playlist_name,
            "count": len(tracks),
            "tracks": tracks,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"获取歌单曲目失败: {str(e)}")


@app.post("/api/spotify/parse-csv")
async def spotify_parse_csv(files: List[UploadFile] = File(...)):
    all_tracks = []
    names = []
    for f in files:
        content = await f.read()
        parsed = parse_csv_tracks(content, f.filename or "")
        if parsed["playlist_name"] and parsed["playlist_name"] not in names:
            names.append(parsed["playlist_name"])
        all_tracks.extend(parsed["tracks"])

    if not all_tracks:
        raise HTTPException(status_code=400, detail="未能从 CSV 文件中解析出任何有效歌曲，请确认是否为 Exportify 导出的 CSV 格式。")

    combined_name = " + ".join(names[:2]) if names else "Spotify Imported Playlist"
    return {
        "playlist_name": combined_name,
        "count": len(all_tracks),
        "tracks": all_tracks,
    }


@app.post("/api/tracks/deduplicate")
async def deduplicate_source_tracks(payload: DeduplicateTracksRequest):
    seen_uris: Dict[str, Dict[str, Any]] = {}
    seen_isrcs: Dict[str, Dict[str, Any]] = {}
    seen_sigs: Dict[tuple, Dict[str, Any]] = {}
    unique_tracks = []
    removed_items = []
    groups_map: Dict[int, Dict[str, Any]] = {}
    idx_to_gid: Dict[int, int] = {}
    next_gid = 1

    for idx, t in enumerate(payload.tracks):
        uri = (t.spotify_uri or "").strip()
        isrc = (t.isrc or "").strip().upper()
        primary_artist = t.artist.split(",")[0].strip() if t.artist else ""
        if payload.mode == "strict":
            sig = (t.title.strip().lower(), primary_artist.lower())
        else:
            sig = (clean_str(t.title), clean_str(primary_artist))

        info = {
            "track_index": idx,
            "position": idx + 1,
            "title": t.title,
            "artist": t.artist,
            "album": t.album or "",
            "duration_ms": t.duration_ms or 0,
        }

        kept = None
        reason = ""
        if uri and uri in seen_uris:
            kept = seen_uris[uri]
            reason = "完全相同曲目 (同 URI)"
        elif payload.mode != "strict" and isrc and isrc in seen_isrcs:
            kept = seen_isrcs[isrc]
            reason = "相同录音编码 (同 ISRC)"
        elif sig[0] and sig in seen_sigs:
            kept = seen_sigs[sig]
            reason = "同名同歌手 (含简繁/不同专辑版)"

        if kept is not None:
            removed_items.append(info)
            k_idx = kept["track_index"]
            if k_idx not in idx_to_gid:
                gid = next_gid
                next_gid += 1
                idx_to_gid[k_idx] = gid
                groups_map[gid] = {
                    "group_id": gid,
                    "reason": reason,
                    "items": [{**kept, "reason": "最早出现", "default_remove": False}],
                }
            else:
                gid = idx_to_gid[k_idx]

            idx_to_gid[idx] = gid
            groups_map[gid]["items"].append({**info, "reason": reason, "default_remove": True})
        else:
            if uri:
                seen_uris[uri] = info
            if isrc:
                seen_isrcs[isrc] = info
            if sig[0]:
                seen_sigs[sig] = info
            unique_tracks.append(t.model_dump())

    return {
        "unique_tracks": unique_tracks,
        "unique_count": len(unique_tracks),
        "removed_count": len(removed_items),
        "removed_items": removed_items,
        "groups": list(groups_map.values()),
    }


# --- Migration Job Execution ---

def add_batch_to_ytm_playlist(
    ytm: YTMusic,
    playlist_id: str,
    video_ids: List[str],
    seen_vids: set,
    skip_duplicates: bool = True,
) -> None:
    if skip_duplicates:
        target_vids = []
        for vid in video_ids:
            if vid and vid not in seen_vids:
                seen_vids.add(vid)
                target_vids.append(vid)
    else:
        target_vids = [vid for vid in video_ids if vid]

    if not target_vids:
        return

    clean_pid = playlist_id[2:] if playlist_id.startswith("VL") else playlist_id
    dedupe_opt = "DEDUPE_OPTION_DROP_DUPLICATE" if skip_duplicates else "DEDUPE_OPTION_SKIP"
    body = {
        "playlistId": clean_pid,
        "actions": [
            {
                "action": "ACTION_ADD_VIDEO",
                "addedVideoId": vid,
                "dedupeOption": dedupe_opt,
            }
            for vid in target_vids
        ],
    }
    try:
        res = ytm._send_request("browse/edit_playlist", body)
        if isinstance(res, dict) and "SUCCEEDED" in res.get("status", ""):
            return
    except Exception:
        pass

    # Fallback one-by-one if batch request returned non-SUCCEEDED or raised error
    for single_vid in target_vids:
        try:
            ytm.add_playlist_items(clean_pid, [single_vid], duplicates=not skip_duplicates)
        except Exception:
            pass


def run_migration_worker(job_id: str, req: MigrationRequest):
    job = migration_jobs[job_id]
    try:
        ytm = YTMusic(str(YTM_AUTH_FILE))
    except Exception as e:
        job["status"] = "failed"
        job["error"] = f"无法初始化 YouTube Music 客户端: {str(e)}"
        return

    target_playlist_id = None
    if req.target_mode == "new_playlist":
        try:
            title = (req.playlist_title or "Imported Spotify Playlist").strip()
            desc = (req.playlist_description or "Imported from Spotify via Switch Music").strip()
            res = ytm.create_playlist(
                title=title,
                description=desc,
                privacy_status=req.privacy_status or "PRIVATE",
            )
            if isinstance(res, str):
                target_playlist_id = res
            elif isinstance(res, dict) and "playlistId" in res:
                target_playlist_id = res["playlistId"]
            else:
                raise RuntimeError(f"创建歌单返回异常: {res}")
            job["target_playlist_id"] = target_playlist_id
        except Exception as e:
            job["status"] = "failed"
            job["error"] = f"创建 YouTube Music 歌单失败: {str(e)}"
            return
    elif req.target_mode == "existing_playlist":
        target_playlist_id = req.existing_playlist_id
        if not target_playlist_id:
            job["status"] = "failed"
            job["error"] = "未选择要追加的现有歌单。"
            return
        job["target_playlist_id"] = target_playlist_id

    matched_video_ids: List[str] = []
    batch_buffer: List[str] = []
    seen_video_ids: set = set()

    for idx, track in enumerate(req.tracks):
        if job.get("cancel_requested"):
            job["status"] = "cancelled"
            break

        job["current_index"] = idx + 1
        job["current_track"] = f"{track.title} - {track.artist}"

        match = match_track_on_ytm(ytm, track)
        if match and match.get("videoId"):
            vid = match["videoId"]
            matched_video_ids.append(vid)
            batch_buffer.append(vid)

            # If mode is liked_songs, rate each song directly
            if req.target_mode == "liked_songs":
                try:
                    ytm.rate_song(vid, "LIKE")
                except Exception:
                    pass

            # Flush playlist additions in batches of 25 so user can see playlist grow in real-time
            if req.target_mode in ("new_playlist", "existing_playlist") and len(batch_buffer) >= 25:
                add_batch_to_ytm_playlist(
                    ytm, target_playlist_id, batch_buffer, seen_video_ids, skip_duplicates=req.skip_duplicates
                )
                batch_buffer.clear()

            job["matched_count"] += 1
            job["results"].append(
                {
                    "index": idx + 1,
                    "source_title": track.title,
                    "source_artist": track.artist,
                    "source_album": track.album,
                    "status": "matched",
                    "ytm_video_id": vid,
                    "ytm_title": match["title"],
                    "ytm_artist": match["artist"],
                    "ytm_duration": match["duration"],
                    "result_type": match["resultType"],
                }
            )
        else:
            job["unmatched_count"] += 1
            job["unmatched_tracks"].append(track.model_dump())
            job["results"].append(
                {
                    "index": idx + 1,
                    "source_title": track.title,
                    "source_artist": track.artist,
                    "source_album": track.album,
                    "status": "unmatched",
                }
            )

        # Gentle pacing to avoid rate limiting
        time.sleep(0.15)

    # Flush remaining items in batch_buffer
    if batch_buffer and req.target_mode in ("new_playlist", "existing_playlist") and target_playlist_id:
        add_batch_to_ytm_playlist(
            ytm, target_playlist_id, batch_buffer, seen_video_ids, skip_duplicates=req.skip_duplicates
        )
        batch_buffer.clear()

    if job["status"] == "running":
        job["status"] = "completed"
    job["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        (DATA_DIR / f"job_{job_id}.json").write_text(
            json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


@app.post("/api/migrate/start")
async def start_migration(req: MigrationRequest):
    if not req.tracks:
        raise HTTPException(status_code=400, detail="待迁移的歌曲列表为空。")
    # Ensure YTM is authenticated before starting thread
    _ = get_ytmusic()

    job_id = str(uuid.uuid4())[:8]
    migration_jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "target_mode": req.target_mode,
        "playlist_title": req.playlist_title,
        "target_playlist_id": req.existing_playlist_id,
        "total": len(req.tracks),
        "current_index": 0,
        "current_track": "准备开始...",
        "matched_count": 0,
        "unmatched_count": 0,
        "results": [],
        "unmatched_tracks": [],
        "error": None,
        "cancel_requested": False,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "completed_at": None,
    }

    thread = threading.Thread(target=run_migration_worker, args=(job_id, req), daemon=True)
    thread.start()
    return {"job_id": job_id}


@app.get("/api/migrate/status/{job_id}")
async def get_migration_status(job_id: str):
    job = migration_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="找不到该迁移任务。")
    return job


@app.post("/api/migrate/cancel/{job_id}")
async def cancel_migration(job_id: str):
    job = migration_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="找不到该迁移任务。")
    job["cancel_requested"] = True
    return {"success": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)
