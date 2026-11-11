from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

from backend.config import (
    KUGOU_AUTH_FILE,
    KUGOU_DEVICE_FILE,
    make_retry_session,
    parse_cookie_and_headers,
    read_json_file,
    write_json_file,
)
from backend.providers.base import PlatformProvider
from backend.text_utils import format_duration_seconds

# Kugou Android client protocol (same parameters as the open-source KuGouMusicApi project).
KUGOU_APPID = 1005
KUGOU_CLIENTVER = 20489
KUGOU_SRCAPPID = 2919
KUGOU_ANDROID_SALT = "OIlwieks28dk2k092lksi2UIkp"
KUGOU_WEB_SALT = "NVPh5oo715z5DIWAeQlhMDsWXXQV4hwt"
KUGOU_GATEWAY = "https://gateway.kugou.com"
KUGOU_LOGIN_HOST = "https://login-user.kugou.com"

# Default playlist created for every Kugou account; "我喜欢" is the liked-songs list.
KUGOU_LIKED_NAMES = ("我喜欢", "我喜欢的音乐", "我的喜欢")
KUGOU_LIKED_FALLBACK_LISTID = 2


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _param_str(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def kugou_android_signature(params: Dict[str, Any], body: str = "") -> str:
    """signature = md5(salt + sorted('k=v'...) + body + salt) — Kugou Android gateway protocol."""
    joined = "".join(f"{k}={_param_str(params[k])}" for k in sorted(params))
    return _md5(f"{KUGOU_ANDROID_SALT}{joined}{body}{KUGOU_ANDROID_SALT}")


def kugou_web_signature(params: Dict[str, Any], body: str = "") -> str:
    joined = "".join(sorted(f"{k}={_param_str(v)}" for k, v in params.items()))
    return _md5(f"{KUGOU_WEB_SALT}{joined}{body}{KUGOU_WEB_SALT}")


def kugou_calc_mid(guid: str) -> str:
    """Device MID = decimal value of md5(guid) (KuGouMusicApi calculateMid)."""
    return str(int(_md5(guid), 16))


def _b35(chunk: str) -> int:
    value = 0
    for ch in chunk:
        value = value * 35 + int(ch, 36)
    return value


def decode_kugou_gcid(code: str) -> Optional[str]:
    """
    Decode a web share code (gcid_3z15kqlufz87z048) into a global_collection_id
    (collection_3_2132029040_287_0). Format: base-35 fields separated by 'z':
    {type}z{userid}z{listid}z{flag}{2-char checksum}.
    """
    raw = (code or "").strip().lower()
    if raw.startswith("gcid_"):
        raw = raw[5:]
    parts = raw.split("z")
    if len(parts) != 4 or not all(parts) or not re.fullmatch(r"[0-9a-y]+", "".join(parts)):
        return None
    try:
        ctype, uid, listid = _b35(parts[0]), _b35(parts[1]), _b35(parts[2])
        flag = _b35(parts[3][0])
    except ValueError:
        return None
    return f"collection_{ctype}_{uid}_{listid}_{flag}"


def _split_kugou_name(name: str, singers: str) -> Tuple[str, str]:
    """Kugou file names look like '周杰伦 - 晴天'. Return (title, artist)."""
    name = (name or "").strip()
    if " - " in name:
        left, right = name.split(" - ", 1)
        if not singers or left.strip() == singers or any(s.strip() and s.strip() in left for s in singers.split(",")):
            return right.strip(), singers or left.strip()
    return name, singers


class KugouProvider(PlatformProvider):
    platform_id = "kugou"
    platform_name = "酷狗音乐"

    ANDROID_UA = "Android15-1070-11083-46-0-DiscoveryDRADProtocol-wifi"
    BROWSER_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # ------------------------------------------------------------------
    # Device / auth state
    # ------------------------------------------------------------------

    def _device(self) -> Dict[str, str]:
        dev = read_json_file(KUGOU_DEVICE_FILE, {})
        if not isinstance(dev, dict) or not dev.get("guid"):
            guid = str(uuid.uuid4())
            dev = {"guid": guid, "mid": kugou_calc_mid(guid)}
            write_json_file(KUGOU_DEVICE_FILE, dev)
        return dev

    def _load_auth(self) -> Dict[str, Any]:
        data = read_json_file(KUGOU_AUTH_FILE, {})
        return data if isinstance(data, dict) else {}

    def _require_auth(self) -> Tuple[str, str]:
        auth = self._load_auth()
        userid = str(auth.get("userid") or "")
        token = str(auth.get("token") or "")
        if not userid or not token:
            raise ValueError("尚未连接酷狗音乐账号，请先在顶部「酷狗音乐」卡片扫码登录或粘贴 token。")
        return userid, token

    # ------------------------------------------------------------------
    # Signed request helper
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        router: Optional[str] = None,
        base: str = KUGOU_GATEWAY,
        sign: str = "android",
        auth: Optional[Tuple[str, str]] = None,
        timeout: int = 15,
    ) -> Dict[str, Any]:
        dev = self._device()
        clienttime = int(time.time())
        query: Dict[str, Any] = {
            "dfid": "-",
            "mid": dev["mid"],
            "uuid": "-",
            "appid": KUGOU_APPID,
            "clientver": KUGOU_CLIENTVER,
            "clienttime": clienttime,
        }
        if auth:
            query["userid"] = auth[0]
            query["token"] = auth[1]
        query.update(params or {})
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")) if data is not None else ""
        query["signature"] = (
            kugou_web_signature(query, body) if sign == "web" else kugou_android_signature(query, body)
        )
        headers = {
            "User-Agent": self.ANDROID_UA,
            "dfid": "-",
            "mid": dev["mid"],
            "clienttime": str(clienttime),
            "kg-rc": "1",
            "kg-thash": "5d816a0",
            "kg-rec": "1",
            "kg-rf": "B9EDA08A64250DEFFBCADDEE00F8F25F",
        }
        if router:
            headers["x-router"] = router
        if body:
            headers["Content-Type"] = "application/json"
        sess = make_retry_session()
        resp = sess.request(
            method,
            base + path,
            params={k: _param_str(v) for k, v in query.items()},
            data=body.encode("utf-8") if body else None,
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            raise RuntimeError(f"酷狗接口返回了非 JSON 数据 (HTTP {resp.status_code})")

    @staticmethod
    def _ok(res: Dict[str, Any]) -> bool:
        if res.get("error_code") not in (None, 0, "0"):
            return False
        return res.get("status") in (None, 1, "1")

    @staticmethod
    def _err(res: Dict[str, Any]) -> str:
        return str(res.get("error_msg") or res.get("errmsg") or res.get("error_code") or res)[:200]

    # ------------------------------------------------------------------
    # QR-code login (scan with the Kugou mobile app)
    # ------------------------------------------------------------------

    def create_login_qrcode(self) -> Dict[str, Any]:
        res = self._request(
            "GET",
            "/v2/qrcode",
            params={
                "appid": 1001,
                "type": 1,
                "plat": 4,
                "qrcode_txt": f"https://h5.kugou.com/apps/loginQRCode/html/index.html?appid={KUGOU_APPID}&",
                "srcappid": KUGOU_SRCAPPID,
            },
            base=KUGOU_LOGIN_HOST,
            sign="web",
        )
        data = res.get("data") or {}
        if not data.get("qrcode"):
            raise RuntimeError(f"生成酷狗登录二维码失败: {self._err(res)}")
        return {"key": data["qrcode"], "qrcode_img": data.get("qrcode_img") or ""}

    def check_login_qrcode(self, key: str) -> Dict[str, Any]:
        res = self._request(
            "GET",
            "/v2/get_userinfo_qrcode",
            params={"plat": 4, "appid": KUGOU_APPID, "srcappid": KUGOU_SRCAPPID, "qrcode": key},
            base=KUGOU_LOGIN_HOST,
            sign="web",
        )
        data = res.get("data") or {}
        status = int(data.get("status") or 0)
        labels = {0: "二维码已过期，请刷新", 1: "等待扫码", 2: "已扫码，请在手机上确认登录", 4: "登录成功"}
        out: Dict[str, Any] = {"status": status, "message": labels.get(status, f"未知状态 {status}")}
        if status == 4 and data.get("token") and data.get("userid"):
            nickname = data.get("nickname") or f"酷狗用户 ({data['userid']})"
            self._persist_auth(str(data["userid"]), str(data["token"]), nickname)
            out.update({"connected": True, "user_name": nickname, "message": f"酷狗音乐连接成功 ({nickname})！"})
        return out

    def _persist_auth(self, userid: str, token: str, nickname: str) -> None:
        write_json_file(
            KUGOU_AUTH_FILE,
            {"userid": userid, "token": token, "nickname": nickname, "updated_at": int(time.time())},
        )

    @staticmethod
    def _extract_token_userid(raw: str) -> Tuple[str, str]:
        raw = (raw or "").strip()
        # 1. JSON {"token": "...", "userid": 123}
        if raw.startswith("{"):
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    data = obj.get("data") if isinstance(obj.get("data"), dict) else obj
                    tok = str(data.get("token") or "")
                    uid = str(data.get("userid") or data.get("user_id") or "")
                    if tok and uid:
                        return tok, uid
            except ValueError:
                pass
        # 2. Cookie / cURL (token=...; userid=... or kugou.com web cookie KuGoo=KugooID=..&t=..)
        try:
            _, cookies, _ = parse_cookie_and_headers(raw)
        except ValueError:
            cookies = {}
        tok = cookies.get("token") or ""
        uid = cookies.get("userid") or cookies.get("KugooID") or ""
        kugoo = cookies.get("KuGoo") or ""
        if kugoo:
            inner = urllib.parse.parse_qs(urllib.parse.unquote(kugoo))
            tok = tok or (inner.get("t") or [""])[0]
            uid = uid or (inner.get("KugooID") or [""])[0]
        if not (tok and uid):
            m_tok = re.search(r"token[\"'=:\s]+([0-9a-fA-F]{32,})", raw)
            m_uid = re.search(r"(?:userid|KugooID)[\"'=:\s]+(\d{4,})", raw)
            tok = tok or (m_tok.group(1) if m_tok else "")
            uid = uid or (m_uid.group(1) if m_uid else "")
        return tok.strip(), str(uid).strip()

    def save_auth(self, raw_input: str) -> Dict[str, Any]:
        token, userid = self._extract_token_userid(raw_input)
        if not token or not userid:
            raise ValueError(
                "未能提取到酷狗音乐 token 与 userid。推荐直接使用「扫码登录」；"
                "或粘贴形如 {\"token\": \"...\", \"userid\": 123} 的内容。"
            )
        try:
            self._fetch_all_lists(userid, token, pagesize=1)
        except Exception as exc:
            raise ValueError(
                f"酷狗 token 验证失败（{exc}）。网页版 kugou.com 的 Cookie 通常不能用于客户端接口，请改用「扫码登录」。"
            )
        nickname = f"酷狗用户 ({userid})"
        self._persist_auth(userid, token, nickname)
        return {
            "success": True,
            "connected": True,
            "user_id": userid,
            "user_name": nickname,
            "message": f"酷狗音乐连接成功 ({nickname})！",
        }

    def get_status(self) -> Dict[str, Any]:
        auth = self._load_auth()
        userid = str(auth.get("userid") or "")
        token = str(auth.get("token") or "")
        if not userid or not token:
            return {"platform": "kugou", "connected": False, "message": "未登录（支持免登录链接导入公开歌单）"}
        nickname = auth.get("nickname") or userid
        try:
            self._fetch_all_lists(userid, token, pagesize=1)
            return {
                "platform": "kugou",
                "connected": True,
                "user_id": userid,
                "user_name": nickname,
                "message": f"已登录 ({nickname})",
            }
        except Exception:
            return {"platform": "kugou", "connected": False, "message": "酷狗登录态已过期，请重新扫码登录"}

    def disconnect(self) -> Dict[str, Any]:
        if KUGOU_AUTH_FILE.exists():
            KUGOU_AUTH_FILE.unlink()
        return {"success": True, "message": "已断开酷狗音乐连接"}

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    def _fetch_all_lists(self, userid: str, token: str, page: int = 1, pagesize: int = 30) -> Dict[str, Any]:
        res = self._request(
            "POST",
            "/v7/get_all_list",
            params={"plat": 1, "userid": userid, "token": token},
            data={"userid": int(userid), "token": token, "total_ver": 979, "type": 2, "page": page, "pagesize": pagesize},
            router="cloudlist.service.kugou.com",
        )
        if not self._ok(res):
            raise RuntimeError(f"读取酷狗歌单列表失败: {self._err(res)}")
        return res.get("data") or {}

    @staticmethod
    def _compound_id(listid: Any, gcid: str) -> str:
        return f"lid_{listid}|gid_{gcid}" if gcid else f"lid_{listid}"

    @staticmethod
    def _parse_compound_id(raw_id: str) -> Tuple[Optional[int], str]:
        s = (raw_id or "").strip()
        m = re.match(r"^lid_(\d+)(?:\|gid_(\S+))?$", s)
        if m:
            return int(m.group(1)), m.group(2) or ""
        if s.startswith("collection_"):
            return None, s
        return None, ""

    def get_user_playlists(self) -> List[Dict[str, Any]]:
        userid, token = self._require_auth()
        items: List[Dict[str, Any]] = []
        page = 1
        while page <= 20:
            data = self._fetch_all_lists(userid, token, page=page, pagesize=30)
            batch = data.get("info") or data.get("list") or []
            for p in batch:
                if not isinstance(p, dict):
                    continue
                listid = p.get("listid")
                gcid = str(p.get("global_collection_id") or "")
                if listid is None and not gcid:
                    continue
                name = str(p.get("name") or "未命名歌单")
                is_liked = name in KUGOU_LIKED_NAMES
                own = str(p.get("list_create_userid") or userid) == str(userid)
                display = "❤️ 我喜欢" if is_liked else name
                cid = self._compound_id(listid, gcid)
                cnt = p.get("count", "")
                items.append(
                    {
                        "id": cid,
                        "playlistId": cid,
                        "listid": listid,
                        "global_collection_id": gcid,
                        "name": display,
                        "title": display,
                        "tracks_total": cnt,
                        "count": cnt,
                        "is_liked": is_liked,
                        "editable": own,
                    }
                )
            total = int(data.get("list_count") or data.get("total") or 0)
            if not batch or len(batch) < 30 or (total and len(items) >= total):
                break
            page += 1
        items.sort(key=lambda it: 0 if it.get("is_liked") else 1)
        return items

    def _liked_listid(self) -> int:
        for p in self.get_user_playlists():
            if p.get("is_liked") and p.get("listid") is not None:
                return int(p["listid"])
        return KUGOU_LIKED_FALLBACK_LISTID

    def _resolve_gcid(self, playlist_id: str) -> str:
        listid, gcid = self._parse_compound_id(playlist_id)
        if gcid:
            return gcid
        if playlist_id == "liked_songs" or listid is not None:
            want = self._liked_listid() if playlist_id == "liked_songs" else listid
            for p in self.get_user_playlists():
                if p.get("listid") == want and p.get("global_collection_id"):
                    return str(p["global_collection_id"])
            raise ValueError("无法定位该酷狗歌单的 global_collection_id，请刷新歌单列表后重试。")
        return self._extract_gcid(playlist_id)

    def _resolve_listid(self, playlist_id: Optional[str], target_mode: str) -> int:
        if target_mode == "liked_songs" or playlist_id == "liked_songs":
            return self._liked_listid()
        if not playlist_id:
            raise ValueError("未指定目标酷狗歌单。")
        listid, gcid = self._parse_compound_id(playlist_id)
        if listid is not None:
            return listid
        for p in self.get_user_playlists():
            if gcid and p.get("global_collection_id") == gcid and p.get("listid") is not None:
                return int(p["listid"])
        raise ValueError("无法定位该酷狗歌单的 listid，请确认这是你本人创建的歌单并刷新歌单列表。")

    def _extract_gcid(self, url_or_id: str) -> str:
        s = (url_or_id or "").strip()
        m = re.search(r"collection_\d+_\d+_\d+_\d+", s)
        if m:
            return m.group(0)
        m = re.search(r"gcid_[0-9a-z]+", s, re.IGNORECASE)
        if m:
            decoded = decode_kugou_gcid(m.group(0))
            if decoded:
                return decoded
        url_match = re.search(r"https?://[^\s\"'<>]+", s)
        if url_match:
            # Short links (t1.kugou.com / m.kugou.com/share) redirect to a URL carrying the id.
            try:
                r = requests.get(
                    url_match.group(0),
                    headers={"User-Agent": self.BROWSER_UA},
                    allow_redirects=True,
                    timeout=10,
                )
                for hop in [h.url for h in r.history] + [r.url]:
                    m = re.search(r"collection_\d+_\d+_\d+_\d+", urllib.parse.unquote(hop))
                    if m:
                        return m.group(0)
                    m = re.search(r"gcid_[0-9a-z]+", hop, re.IGNORECASE)
                    if m and decode_kugou_gcid(m.group(0)):
                        return decode_kugou_gcid(m.group(0)) or ""
                m = re.search(r"collection_\d+_\d+_\d+_\d+", r.text)
                if m:
                    return m.group(0)
            except requests.RequestException:
                pass
            m = re.search(r"/special/single/(\d+)", s)
            if m:
                return self._specialid_to_gcid(m.group(1))
        if s.isdigit():
            return self._specialid_to_gcid(s)
        raise ValueError(
            "无法识别酷狗歌单链接（支持 https://www.kugou.com/songlist/gcid_xxx/ 、"
            "App 分享链接或 collection_3_xxx_xx_0 形式的歌单 ID）。"
        )

    def _specialid_to_gcid(self, specialid: str) -> str:
        try:
            r = requests.get(
                f"https://www.kugou.com/yy/special/single/{specialid}.html",
                headers={"User-Agent": self.BROWSER_UA},
                timeout=10,
            )
            m = re.search(r"collection_\d+_\d+_\d+_\d+", r.text)
            if m:
                return m.group(0)
        except requests.RequestException:
            pass
        raise ValueError(f"未能解析酷狗歌单 ID {specialid}，请改为粘贴歌单分享链接。")

    @staticmethod
    def _song_to_track(song: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(song, dict):
            return None
        singers = ", ".join(
            s.get("name", "") for s in (song.get("singerinfo") or []) if isinstance(s, dict) and s.get("name")
        )
        title, artist = _split_kugou_name(str(song.get("name") or ""), singers)
        if not title:
            return None
        album = ((song.get("albuminfo") or {}).get("name")) or ""
        mixsongid = song.get("mixsongid") or song.get("add_mixsongid") or 0
        sh = str(song.get("hash") or "")
        album_id = song.get("album_id") or (song.get("albuminfo") or {}).get("id") or 0
        return {
            "title": title,
            "artist": artist,
            "album": album,
            "duration_ms": int(song.get("timelen") or 0),
            "isrc": "",
            "spotify_uri": "",
            "source_platform": "kugou",
            "source_id": str(mixsongid or sh),
            "extra": {
                "hash": sh,
                "mixsongid": int(mixsongid or 0),
                "album_id": int(album_id or 0) if str(album_id).isdigit() else 0,
                "fileid": song.get("fileid") or 0,
                "name": song.get("name") or "",
                "url": f"https://www.kugou.com/song/#hash={sh}&album_id={album_id}" if sh else "",
            },
        }

    def get_playlist_tracks(self, playlist_id: str) -> Dict[str, Any]:
        gcid = self._resolve_gcid(playlist_id)
        auth = None
        a = self._load_auth()
        if a.get("userid") and a.get("token"):
            auth = (str(a["userid"]), str(a["token"]))

        tracks: List[Dict[str, Any]] = []
        playlist_name = "酷狗歌单"
        begin, page_size = 0, 500
        while True:
            res = self._request(
                "GET",
                "/pubsongs/v2/get_other_list_file_nofilt",
                params={
                    "area_code": 1,
                    "begin_idx": begin,
                    "plat": 1,
                    "type": 1,
                    "mode": 1,
                    "personal_switch": 1,
                    "extend_fields": "",
                    "pagesize": page_size,
                    "global_collection_id": gcid,
                },
                auth=auth,
            )
            if not self._ok(res):
                if tracks:
                    break
                raise ValueError(
                    f"未能读取该酷狗歌单（{self._err(res)}）。若为私密歌单，请先扫码登录酷狗账号。"
                )
            data = res.get("data") or {}
            info = data.get("list_info") or {}
            playlist_name = info.get("name") or playlist_name
            batch = data.get("songs") or []
            for s in batch:
                parsed = self._song_to_track(s)
                if parsed:
                    tracks.append(parsed)
            total = int(data.get("count") or info.get("count") or 0)
            begin += len(batch)
            if not batch or len(batch) < page_size or (total and begin >= total):
                break

        if not tracks:
            raise ValueError("该酷狗歌单为空，或无权读取（私密歌单需先扫码登录）。")
        return {"playlist_name": playlist_name, "count": len(tracks), "tracks": tracks}

    def import_from_url(self, url_or_id: str) -> Dict[str, Any]:
        return self.get_playlist_tracks(self._extract_gcid(url_or_id))

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_candidates(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        res = self._request(
            "GET",
            "/v2/search/song",
            params={
                "keyword": query,
                "page": 1,
                "pagesize": max(1, min(30, limit)),
                "platform": "AndroidFilter",
                "iscorrection": 1,
                "privilegefilter": 0,
                "area_code": 1,
            },
            router="complexsearch.kugou.com",
        )
        if not self._ok(res):
            raise RuntimeError(f"酷狗搜索失败: {self._err(res)}")
        out: List[Dict[str, Any]] = []
        for s in ((res.get("data") or {}).get("lists") or [])[:limit]:
            mixsongid = s.get("MixSongID") or s.get("ID") or 0
            sh = str(s.get("FileHash") or "")
            if not mixsongid and not sh:
                continue
            singers = ", ".join(
                x.get("name", "") for x in (s.get("Singers") or []) if isinstance(x, dict) and x.get("name")
            ) or str(s.get("SingerName") or "").replace("、", ", ")
            title = re.sub(r"</?em>", "", str(s.get("SongName") or s.get("OriSongName") or ""))
            dur = int(s.get("Duration") or 0)
            album_id = str(s.get("AlbumID") or "0")
            out.append(
                {
                    "platform": "kugou",
                    "track_id": str(mixsongid or sh),
                    "display_id": str(mixsongid or sh),
                    "title": title,
                    "artist": singers,
                    "album": str(s.get("AlbumName") or ""),
                    "duration": format_duration_seconds(dur),
                    "duration_seconds": dur,
                    "resultType": "song",
                    "url": f"https://www.kugou.com/song/#hash={sh}&album_id={album_id}" if sh else "",
                    "extra": {
                        "hash": sh,
                        "mixsongid": int(mixsongid or 0) if str(mixsongid).isdigit() else 0,
                        "album_id": int(album_id) if album_id.isdigit() else 0,
                        "name": s.get("FileName") or f"{singers} - {title}",
                    },
                }
            )
        return out

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def create_playlist(self, title: str, description: str = "", privacy_status: str = "PRIVATE") -> str:
        userid, token = self._require_auth()
        name = (title or "Switch Music 歌单").strip()[:40]
        res = self._request(
            "POST",
            "/cloudlist.service/v5/add_list",
            params={"last_time": int(time.time()), "last_area": "gztx", "userid": userid, "token": token},
            data={
                "userid": int(userid),
                "token": token,
                "total_ver": 0,
                "name": name,
                "type": 0,
                "source": 1,
                "is_pri": 1 if str(privacy_status).upper() == "PRIVATE" else 0,
                "list_create_gid": "",
                "from_shupinmv": 0,
            },
            auth=(userid, token),
        )
        if not self._ok(res):
            raise RuntimeError(f"创建酷狗歌单失败: {self._err(res)}")
        data = res.get("data") or {}
        if isinstance(data, list):
            data = data[0] if data else {}
        listid = data.get("listid") or (data.get("info") or {}).get("listid")
        gcid = str(data.get("global_collection_id") or "")
        if not listid:
            # Fall back to locating the freshly created playlist by name.
            for p in self.get_user_playlists():
                if p.get("name") == name:
                    listid, gcid = p.get("listid"), str(p.get("global_collection_id") or "")
                    break
        if not listid:
            raise RuntimeError(f"酷狗歌单已提交创建，但未返回歌单 ID: {data}")
        return self._compound_id(listid, gcid)

    def get_existing_track_ids(self, playlist_id: Optional[str], target_mode: str = "existing_playlist") -> Set[str]:
        pid = "liked_songs" if target_mode == "liked_songs" else (playlist_id or "")
        if not pid:
            return set()
        try:
            data = self.get_playlist_tracks(pid)
        except ValueError as exc:
            if "为空" in str(exc):
                return set()
            raise
        return {str(t.get("source_id")) for t in data.get("tracks") or [] if t.get("source_id")}

    def add_tracks(
        self,
        playlist_id: Optional[str],
        target_mode: str,
        candidates: List[Dict[str, Any]],
        seen_ids: Set[str],
        skip_duplicates: bool = True,
    ) -> int:
        userid, token = self._require_auth()
        listid = self._resolve_listid(playlist_id, target_mode)
        resources: List[Dict[str, Any]] = []
        for c in candidates:
            ex = c.get("extra") or {}
            sh = str(ex.get("hash") or "")
            tid = str(c.get("track_id") or "")
            if not sh:
                continue
            if skip_duplicates:
                if tid in seen_ids:
                    continue
                seen_ids.add(tid)
            resources.append(
                {
                    "number": 1,
                    "name": ex.get("name") or f"{c.get('artist', '')} - {c.get('title', '')}",
                    "hash": sh,
                    "size": 0,
                    "sort": 0,
                    "timelen": 0,
                    "bitrate": 0,
                    "album_id": int(ex.get("album_id") or 0),
                    "mixsongid": int(ex.get("mixsongid") or (tid if tid.isdigit() else 0)),
                }
            )
        added = 0
        for i in range(0, len(resources), 100):
            batch = resources[i : i + 100]
            res = self._request(
                "POST",
                "/cloudlist.service/v6/add_song",
                params={"last_time": int(time.time()), "last_area": "gztx", "userid": userid, "token": token},
                data={
                    "userid": int(userid),
                    "token": token,
                    "listid": listid,
                    "list_ver": 0,
                    "type": 0,
                    "slow_upload": 1,
                    "scene": "false;null",
                    "data": batch,
                },
                auth=(userid, token),
            )
            if not self._ok(res):
                raise RuntimeError(f"写入酷狗歌单失败: {self._err(res)}")
            added += len(batch)
            time.sleep(0.2)
        return added

    def get_dedupe_raw_items(self, playlist_id: str) -> Tuple[str, List[Dict[str, Any]]]:
        data = self.get_playlist_tracks(playlist_id)
        items: List[Dict[str, Any]] = []
        for idx, t in enumerate(data.get("tracks") or []):
            ex = t.get("extra") or {}
            dur_s = int(t.get("duration_ms") or 0) // 1000
            artist = t.get("artist") or ""
            items.append(
                {
                    "position": idx + 1,
                    "item_id": str(t.get("source_id") or ""),
                    "videoId": str(t.get("source_id") or ""),
                    "setVideoId": str(ex.get("fileid") or ""),
                    "can_remove": bool(ex.get("fileid")),
                    "title": t.get("title") or "Unknown",
                    "artist": artist,
                    "primary_artist": artist.split(",")[0].strip() if artist else "",
                    "album": t.get("album") or "",
                    "duration": format_duration_seconds(dur_s),
                    "duration_seconds": dur_s,
                    "url": ex.get("url") or "",
                    "extra": {"fileid": ex.get("fileid"), "hash": ex.get("hash")},
                }
            )
        return data.get("playlist_name") or "酷狗歌单", items

    def remove_playlist_duplicates(self, playlist_id: str, items: List[Dict[str, Any]]) -> int:
        userid, token = self._require_auth()
        listid = self._resolve_listid(playlist_id, "existing_playlist")
        fileids: List[int] = []
        for it in items:
            fid = (it.get("extra") or {}).get("fileid") or it.get("setVideoId")
            if str(fid or "").isdigit() and int(fid) > 0:
                fileids.append(int(fid))
        if not fileids:
            raise ValueError("没有可移除的有效酷狗歌曲项。")
        removed = 0
        for i in range(0, len(fileids), 100):
            batch = fileids[i : i + 100]
            res = self._request(
                "POST",
                "/v4/delete_songs",
                data={
                    "listid": listid,
                    "userid": int(userid),
                    "data": [{"fileid": f} for f in batch],
                    "type": 0,
                    "token": token,
                    "list_ver": 0,
                },
                router="cloudlist.service.kugou.com",
                auth=(userid, token),
            )
            if not self._ok(res):
                raise RuntimeError(f"从酷狗歌单移除曲目失败: {self._err(res)}")
            removed += len(batch)
            time.sleep(0.2)
        return removed

    def build_playlist_url(self, playlist_id: Optional[str], target_mode: str = "new_playlist") -> str:
        return "https://www.kugou.com/"
