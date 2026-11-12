from __future__ import annotations

import html as html_lib
import json
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

from backend.config import make_retry_session
from backend.providers.base import PlatformProvider


_QISHUI_SHORT_RE = re.compile(r"https?://qishui\.douyin\.com/s/[A-Za-z0-9_-]+/?")
_QISHUI_FULL_RE = re.compile(r"https?://(?:music|qishui)\.douyin\.com/[^\s\"'<>]+")
_PLAYLIST_ID_RE = re.compile(r"playlist_id=(\d{8,25})")


def _split_artist_album(raw: str) -> Tuple[str, str]:
    text = (raw or "").strip()
    for sep in (" • ", "•", " · ", " - "):
        if sep in text:
            left, right = text.split(sep, 1)
            return left.strip(), right.strip()
    return text, ""


class _QishuiHtmlExtractor(HTMLParser):
    """Fallback HTML parser for Qishui SSR share pages using Python stdlib only."""

    def __init__(self) -> None:
        super().__init__()
        self._in_h1 = False
        self._in_title = False
        self._in_p = False
        self._in_script = False
        self._buf: List[str] = []
        self.h1_texts: List[str] = []
        self.page_title: str = ""
        self.p_texts: List[str] = []
        self.scripts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        if t == "h1":
            self._in_h1 = True
        elif t == "title":
            self._in_title = True
            self._buf = []
        elif t == "p":
            self._in_p = True
            self._buf = []
        elif t == "script":
            self._in_script = True
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "h1":
            self._in_h1 = False
        elif t == "title" and self._in_title:
            self._in_title = False
            self.page_title = "".join(self._buf).strip()
            self._buf = []
        elif t == "p" and self._in_p:
            self._in_p = False
            val = "".join(self._buf).strip()
            if val:
                if self._in_h1:
                    self.h1_texts.append(val)
                else:
                    self.p_texts.append(val)
            self._buf = []
        elif t == "script" and self._in_script:
            self._in_script = False
            val = "".join(self._buf).strip()
            if val:
                self.scripts.append(val)
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_title or self._in_p or self._in_script:
            self._buf.append(data)


def parse_qishui_html(html_text: str) -> Dict[str, Any]:
    """
    Extract playlist name and tracks from a Qishui Music (汽水音乐) share page.
    Strategy 1: Structured SSR JSON (`_ROUTER_DATA` / `__INITIAL_STATE__`).
    Strategy 2: Resilient `<p>` pair extraction (Title + `Artist • Album`).
    """
    parser = _QishuiHtmlExtractor()
    parser.feed(html_text or "")

    # 1. Try structured SSR JSON embedded in scripts
    for sc in parser.scripts:
        for marker in ("_ROUTER_DATA", "__INITIAL_STATE__", "__SSR_DATA__"):
            if marker not in sc:
                continue
            eq_idx = sc.find("=", sc.find(marker))
            if eq_idx < 0:
                continue
            raw_json = sc[eq_idx + 1 :].strip().rstrip(";")
            # Decode unicode escapes if wrapped in JSON.parse("...")
            if raw_json.startswith(("JSON.parse(", "window.")):
                m_str = re.search(r"JSON\.parse\(\s*(['\"])(.*?)\1\s*\)", raw_json, re.S)
                if m_str:
                    try:
                        raw_json = bytes(m_str.group(2), "utf-8").decode("unicode_escape")
                    except Exception:
                        pass
            try:
                obj = json.loads(raw_json)
            except Exception:
                # Try balanced brace slice
                brace_start = raw_json.find("{")
                brace_end = raw_json.rfind("}")
                if brace_start >= 0 and brace_end > brace_start:
                    try:
                        obj = json.loads(raw_json[brace_start : brace_end + 1])
                    except Exception:
                        obj = None
                else:
                    obj = None

            if isinstance(obj, dict):
                extracted = _extract_from_ssr_object(obj)
                if extracted and extracted["tracks"]:
                    return extracted

    # 2. Fallback: HTML paragraph extraction
    playlist_name = ""
    if parser.h1_texts:
        playlist_name = parser.h1_texts[0].strip()
    elif parser.page_title:
        playlist_name = re.sub(r"\s*[-|_]\s*汽水音乐.*$", "", parser.page_title).strip()
    playlist_name = html_lib.unescape(playlist_name) or "汽水音乐歌单"

    # In Qishui's share page, song rows contain pairs of <p>: [Song Title, "Artist • Album"]
    tracks: List[Dict[str, Any]] = []
    p_list = [html_lib.unescape(x).strip() for x in parser.p_texts if x.strip()]
    idx = 0
    noise_exact = {"汽水音乐", "打开汽水音乐", "打开App", "全部播放", "歌单", "评论", "收藏", "分享"}
    while idx + 1 < len(p_list):
        cur = p_list[idx]
        nxt = p_list[idx + 1]
        if " • " in nxt or "•" in nxt:
            if cur not in noise_exact and not re.fullmatch(r"\d+", cur):
                artist, album = _split_artist_album(nxt)
                tracks.append(
                    {
                        "title": cur,
                        "artist": artist,
                        "album": album,
                        "duration_ms": 0,
                        "isrc": "",
                        "spotify_uri": "",
                        "source_platform": "qishui",
                        "source_id": "",
                    }
                )
                idx += 2
                continue
        idx += 1

    return {
        "playlist_name": playlist_name,
        "count": len(tracks),
        "tracks": tracks,
    }


def _extract_from_ssr_object(root: Any) -> Optional[Dict[str, Any]]:
    playlist_title = ""
    found_tracks: List[Dict[str, Any]] = []

    def _walk(node: Any) -> None:
        nonlocal playlist_title
        if isinstance(node, dict):
            # Playlist title candidates
            for tk in ("title_name", "playlist_name", "playlistName"):
                if not playlist_title and isinstance(node.get(tk), str) and node[tk].strip():
                    playlist_title = node[tk].strip()
            for pk in ("playlistInfo", "playlist_info", "playlist"):
                pobj = node.get(pk)
                if not playlist_title and isinstance(pobj, dict):
                    cand_t = str(pobj.get("name") or pobj.get("title") or pobj.get("title_name") or "").strip()
                    if cand_t:
                        playlist_title = cand_t
            if (
                not playlist_title
                and isinstance(node.get("title"), str)
                and any(k in node for k in ("track_list", "trackList", "tracks", "song_list", "count_tracks"))
            ):
                playlist_title = node["title"].strip()

            # Track array candidates
            for lk in ("track_list", "trackList", "song_list", "songList", "tracks", "medias"):
                arr = node.get(lk)
                if isinstance(arr, list) and arr and all(isinstance(x, dict) for x in arr[:3]):
                    parsed_batch = [_parse_ssr_track(x) for x in arr]
                    valid_batch = [t for t in parsed_batch if t is not None]
                    if len(valid_batch) > len(found_tracks):
                        found_tracks.clear()
                        found_tracks.extend(valid_batch)  # type: ignore[arg-type]

            for v in node.values():
                if isinstance(v, (dict, list)):
                    _walk(v)
        elif isinstance(node, list):
            for it in node:
                if isinstance(it, (dict, list)):
                    _walk(it)

    _walk(root)
    if not found_tracks:
        return None
    return {
        "playlist_name": playlist_title or "汽水音乐歌单",
        "count": len(found_tracks),
        "tracks": found_tracks,
    }


def _parse_ssr_track(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    inner = raw.get("track") if isinstance(raw.get("track"), dict) else raw
    title = str(inner.get("name") or inner.get("title") or inner.get("track_name") or "").strip()
    if not title:
        return None

    artist = ""
    artists_val = inner.get("artists") or inner.get("artist_list") or inner.get("authors")
    if isinstance(artists_val, list):
        names = [
            str(a.get("name") or a.get("nick_name") or "").strip()
            for a in artists_val
            if isinstance(a, dict) and (a.get("name") or a.get("nick_name"))
        ]
        artist = ", ".join(names)
    if not artist:
        artist = str(
            inner.get("artist")
            or inner.get("artistName")
            or inner.get("artist_name")
            or inner.get("author")
            or inner.get("singer")
            or ""
        ).strip()

    album = ""
    album_val = inner.get("album")
    if isinstance(album_val, dict):
        album = str(album_val.get("name") or album_val.get("title") or "").strip()
    elif isinstance(album_val, str):
        album = album_val.strip()
    if not album:
        album = str(inner.get("albumName") or inner.get("album_name") or "").strip()

    dur_raw = inner.get("duration") or inner.get("duration_ms") or 0
    dur_ms = 0
    try:
        dur_int = int(float(dur_raw))
        # Qishui SSR durations are usually ms (>1000) or seconds (<1000)
        dur_ms = dur_int if dur_int > 1500 else dur_int * 1000
    except (ValueError, TypeError):
        dur_ms = 0

    tid = str(inner.get("id") or inner.get("track_id") or inner.get("id_str") or "").strip()
    return {
        "title": title,
        "artist": artist,
        "album": album,
        "duration_ms": dur_ms,
        "isrc": str(inner.get("isrc") or "").strip(),
        "spotify_uri": "",
        "source_platform": "qishui",
        "source_id": tid,
    }


class QishuiProvider(PlatformProvider):
    """
    汽水音乐 (Soda Music by Douyin) public playlist link importer.
    Supports share short links (qishui.douyin.com/s/...) and playlist_id URLs without login.
    """

    platform_id = "qishui"
    platform_name = "汽水音乐"

    UA = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
    )

    @staticmethod
    def resolve_share_target(raw_input: str) -> str:
        text = (raw_input or "").strip()
        if not text:
            raise ValueError("请输入汽水音乐歌单分享链接（如 https://qishui.douyin.com/s/...）。")
        m_short = _QISHUI_SHORT_RE.search(text)
        if m_short:
            return m_short.group(0)
        m_full = _QISHUI_FULL_RE.search(text)
        if m_full:
            return m_full.group(0)
        m_id = _PLAYLIST_ID_RE.search(text)
        if m_id:
            return f"https://music.douyin.com/qishui/share/playlist?playlist_id={m_id.group(1)}"
        if re.fullmatch(r"\d{12,25}", text):
            return f"https://music.douyin.com/qishui/share/playlist?playlist_id={text}"
        raise ValueError("未能识别有效的汽水音乐歌单链接，请粘贴包含 qishui.douyin.com 或 playlist_id 的分享内容。")

    def get_status(self) -> Dict[str, Any]:
        return {
            "platform": "qishui",
            "connected": False,
            "source_only": True,
            "message": "支持免登录粘贴公开歌单分享链接导入",
        }

    def disconnect(self) -> Dict[str, Any]:
        return {"success": True, "message": "汽水音乐仅使用免登录公开链接导入，无需断开"}

    def import_from_url(self, url_or_id: str) -> Dict[str, Any]:
        target_url = self.resolve_share_target(url_or_id)
        sess = make_retry_session()
        sess.headers.update(
            {
                "User-Agent": self.UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        resp = sess.get(target_url, allow_redirects=True, timeout=15)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        parsed = parse_qishui_html(resp.text)
        if not parsed["tracks"]:
            raise ValueError(
                "未能从该汽水音乐链接中提取到歌曲（可能该歌单已被设为私密、已删除，或分享页结构变化）。"
            )
        return parsed
