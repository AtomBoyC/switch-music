from __future__ import annotations

import hashlib
import os
import secrets
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from backend.config import (
    DATA_DIR,
    make_retry_session,
    read_json_file,
    write_json_file,
)
from backend.providers.base import PlatformProvider
from backend.text_utils import format_duration_seconds

SUBSONIC_AUTH_FILE = DATA_DIR / "subsonic_auth.json"
SUBSONIC_LIKED_ID = "STARRED"
SUBSONIC_API_VERSION = "1.16.1"
SUBSONIC_CLIENT_NAME = "SwitchMusic"


def _as_list(val: Any) -> List[Any]:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return [val]
    return []


def normalize_subsonic_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if not url:
        raise ValueError("请输入 Navidrome / Subsonic 服务器地址（例如 http://192.168.1.10:4533）。")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("服务器地址必须以 http:// 或 https:// 开头（例如 http://192.168.1.10:4533）。")
    clean = url.rstrip("/")
    if clean.lower().endswith("/rest"):
        clean = clean[:-5].rstrip("/")
    return clean


def make_subsonic_auth_params(username: str, password: str, salt: Optional[str] = None) -> Dict[str, str]:
    s = salt or secrets.token_hex(6)
    token = hashlib.md5(f"{password}{s}".encode("utf-8")).hexdigest()
    return {
        "u": username,
        "t": token,
        "s": s,
        "v": SUBSONIC_API_VERSION,
        "c": SUBSONIC_CLIENT_NAME,
        "f": "json",
    }


def _extract_song_artist(song: Dict[str, Any]) -> str:
    artists = _as_list(song.get("artists"))
    if artists:
        names = [str(a.get("name") or "").strip() for a in artists if isinstance(a, dict) and a.get("name")]
        if names:
            return ", ".join(names)
    return str(song.get("artist") or "").strip()


def _extract_song_isrc(song: Dict[str, Any]) -> str:
    raw = song.get("isrc")
    if isinstance(raw, list):
        for item in raw:
            if item and str(item).strip():
                return str(item).strip()
        return ""
    if isinstance(raw, str):
        return raw.strip()
    return ""


class SubsonicProvider(PlatformProvider):
    """
    Navidrome / Subsonic / OpenSubsonic compatible music server provider.
    Supports Navidrome, Airsonic, Gonic, Ampache, LMS, Funkwhale, etc.
    """

    platform_id = "subsonic"
    platform_name = "Navidrome / Subsonic"

    def _load_auth(self) -> Dict[str, Any]:
        saved = read_json_file(SUBSONIC_AUTH_FILE, {})
        if isinstance(saved, dict) and saved.get("server_url") and saved.get("username") and saved.get("password"):
            return saved
        env_url = (os.environ.get("SUBSONIC_URL") or "").strip()
        env_user = (os.environ.get("SUBSONIC_USER") or "").strip()
        env_pass = os.environ.get("SUBSONIC_PASSWORD") or ""
        if env_url and env_user and env_pass:
            return {
                "server_url": normalize_subsonic_url(env_url),
                "username": env_user,
                "password": env_pass,
                "server_type": "Subsonic",
            }
        return saved if isinstance(saved, dict) else {}

    def _require_auth(self) -> Tuple[str, str, str]:
        auth = self._load_auth()
        url = str(auth.get("server_url") or "").strip()
        user = str(auth.get("username") or "").strip()
        pwd = str(auth.get("password") or "")
        if not url or not user or not pwd:
            raise ValueError("尚未配置 Navidrome / Subsonic 服务器连接，请先点击顶部「Navidrome」卡片完成连接。")
        return normalize_subsonic_url(url), user, pwd

    def _request(
        self,
        endpoint: str,
        params: Optional[Union[Dict[str, Any], Sequence[Tuple[str, Any]]]] = None,
        creds: Optional[Tuple[str, str, str]] = None,
        method: str = "GET",
    ) -> Dict[str, Any]:
        base_url, user, pwd = creds or self._require_auth()
        ep = endpoint.lstrip("/")
        if not ep.endswith(".view"):
            ep = f"{ep}.view"
        auth_pairs = list(make_subsonic_auth_params(user, pwd).items())
        extra_pairs: List[Tuple[str, Any]] = []
        if isinstance(params, dict):
            extra_pairs = [(k, v) for k, v in params.items() if v is not None]
        elif params:
            extra_pairs = [(k, v) for k, v in params if v is not None]

        all_params = auth_pairs + extra_pairs
        sess = make_retry_session()
        url = f"{base_url}/rest/{ep}"
        if method.upper() == "POST":
            resp = sess.post(url, data=all_params, timeout=15)
        else:
            resp = sess.get(url, params=all_params, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        sr = payload.get("subsonic-response") if isinstance(payload, dict) else None
        if not isinstance(sr, dict):
            raise RuntimeError("服务器返回的不是有效的 Subsonic JSON 响应，请检查服务器地址是否正确。")
        if sr.get("status") != "ok":
            err = sr.get("error") or {}
            code = err.get("code")
            msg = err.get("message") or "未知 Subsonic 错误"
            if code in (40, 41):
                raise PermissionError(f"Navidrome / Subsonic 认证失败 ({code}): {msg}")
            raise RuntimeError(f"Navidrome / Subsonic 接口报错 ({code}): {msg}")
        return sr

    def save_config(self, server_url: str, username: str, password: str = "") -> Dict[str, Any]:
        clean_url = normalize_subsonic_url(server_url)
        clean_user = (username or "").strip()
        if not clean_user:
            raise ValueError("请输入登录用户名。")
        existing = self._load_auth()
        effective_pwd = password if password else str(existing.get("password") or "")
        if not effective_pwd:
            raise ValueError("请输入登录密码。")

        sr = self._request("ping", creds=(clean_url, clean_user, effective_pwd))
        server_type = str(sr.get("type") or "Subsonic").strip()
        server_ver = str(sr.get("serverVersion") or sr.get("version") or "").strip()
        label = f"{clean_user} @ {server_type}" + (f" {server_ver}" if server_ver else "")

        write_json_file(
            SUBSONIC_AUTH_FILE,
            {
                "server_url": clean_url,
                "username": clean_user,
                "password": effective_pwd,
                "server_type": server_type,
                "server_version": server_ver,
                "updated_at": int(time.time()),
            },
        )
        return {
            "success": True,
            "connected": True,
            "user_name": label,
            "server_url": clean_url,
            "username": clean_user,
            "message": f"成功连接 {server_type} 服务器 ({clean_url})！",
        }

    def get_status(self) -> Dict[str, Any]:
        auth = self._load_auth()
        url = str(auth.get("server_url") or "").strip()
        user = str(auth.get("username") or "").strip()
        pwd = str(auth.get("password") or "")
        if not url or not user or not pwd:
            return {
                "platform": "subsonic",
                "connected": False,
                "server_url": url,
                "username": user,
                "has_password": False,
                "message": "未连接（支持 Navidrome / Subsonic 私有音乐服）",
            }
        try:
            sr = self._request("ping", creds=(normalize_subsonic_url(url), user, pwd))
            stype = str(sr.get("type") or auth.get("server_type") or "Subsonic")
            return {
                "platform": "subsonic",
                "connected": True,
                "user_name": f"{user} @ {stype}",
                "server_url": url,
                "username": user,
                "has_password": True,
                "message": f"已连接 {stype} ({user})",
            }
        except Exception as e:
            return {
                "platform": "subsonic",
                "connected": False,
                "server_url": url,
                "username": user,
                "has_password": True,
                "message": f"连接异常: {str(e)}",
            }

    def disconnect(self) -> Dict[str, Any]:
        if SUBSONIC_AUTH_FILE.exists():
            SUBSONIC_AUTH_FILE.unlink()
        return {"success": True, "message": "已断开 Navidrome / Subsonic 连接并清除本地凭据"}

    def _song_to_track(self, song: Dict[str, Any]) -> Dict[str, Any]:
        sid = str(song.get("id") or "").strip()
        dur_sec = int(song.get("duration") or 0)
        return {
            "title": str(song.get("title") or "").strip(),
            "artist": _extract_song_artist(song),
            "album": str(song.get("album") or "").strip(),
            "duration_ms": dur_sec * 1000 if dur_sec > 0 else 0,
            "isrc": _extract_song_isrc(song),
            "spotify_uri": "",
            "source_platform": "subsonic",
            "source_id": sid,
            "extra": {"path": str(song.get("path") or "").strip()},
        }

    def get_user_playlists(self) -> List[Dict[str, Any]]:
        _, current_user, _ = self._require_auth()
        sr = self._request("getPlaylists")
        raw_playlists = _as_list((sr.get("playlists") or {}).get("playlist"))
        out: List[Dict[str, Any]] = [
            {
                "id": SUBSONIC_LIKED_ID,
                "playlistId": SUBSONIC_LIKED_ID,
                "title": "❤️ 星标收藏歌曲 (Starred Songs)",
                "name": "❤️ 星标收藏歌曲 (Starred Songs)",
                "count": "自动同步",
                "is_liked": True,
                "editable": False,
            }
        ]
        for p in raw_playlists:
            if not isinstance(p, dict) or not p.get("id"):
                continue
            owner = str(p.get("owner") or "").strip()
            editable = (not owner) or (owner.lower() == current_user.lower())
            pid = str(p["id"])
            name = str(p.get("name") or "Untitled Playlist")
            out.append(
                {
                    "id": pid,
                    "playlistId": pid,
                    "title": name,
                    "name": name,
                    "count": int(p.get("songCount") or 0),
                    "is_liked": False,
                    "editable": editable,
                }
            )
        return out

    def get_playlist_tracks(self, playlist_id: str) -> Dict[str, Any]:
        pid = (playlist_id or "").strip()
        if pid == SUBSONIC_LIKED_ID:
            try:
                sr = self._request("getStarred2")
                songs = _as_list((sr.get("starred2") or {}).get("song"))
            except Exception:
                sr = self._request("getStarred")
                songs = _as_list((sr.get("starred") or {}).get("song"))
            tracks = [self._song_to_track(s) for s in songs if isinstance(s, dict) and s.get("title")]
            return {
                "playlist_name": "Starred Songs",
                "count": len(tracks),
                "tracks": tracks,
            }

        sr = self._request("getPlaylist", {"id": pid})
        pl = sr.get("playlist") or {}
        entries = _as_list(pl.get("entry"))
        tracks = [self._song_to_track(s) for s in entries if isinstance(s, dict) and s.get("title")]
        return {
            "playlist_name": str(pl.get("name") or "Subsonic Playlist"),
            "count": len(tracks),
            "tracks": tracks,
        }

    def search_candidates(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        base_url, _, _ = self._require_auth()
        q = (query or "").strip()
        if not q:
            return []
        sr = self._request(
            "search3",
            {
                "query": q,
                "songCount": max(limit, 10),
                "artistCount": 0,
                "albumCount": 0,
            },
        )
        songs = _as_list((sr.get("searchResult3") or {}).get("song"))
        candidates: List[Dict[str, Any]] = []
        for s in songs[: max(limit, 10)]:
            if not isinstance(s, dict) or not s.get("id"):
                continue
            sid = str(s["id"])
            dur_sec = int(s.get("duration") or 0)
            album_id = str(s.get("albumId") or "").strip()
            web_url = f"{base_url}/app/#/album/{album_id}/show" if album_id else base_url
            candidates.append(
                {
                    "platform": "subsonic",
                    "track_id": sid,
                    "title": str(s.get("title") or "").strip(),
                    "artist": _extract_song_artist(s),
                    "album": str(s.get("album") or "").strip(),
                    "duration": format_duration_seconds(dur_sec) if dur_sec > 0 else "",
                    "duration_seconds": dur_sec,
                    "isrc": _extract_song_isrc(s),
                    "resultType": "song",
                    "url": web_url,
                    "path": str(s.get("path") or "").strip(),
                }
            )
        return candidates[:limit]

    def create_playlist(
        self,
        title: str,
        description: str = "",
        privacy_status: str = "PRIVATE",
    ) -> str:
        clean_title = (title or "Switch Music Playlist").strip()
        sr = self._request("createPlaylist", {"name": clean_title}, method="POST")
        pid = str((sr.get("playlist") or {}).get("id") or "").strip()
        if not pid:
            # Older Subsonic servers return empty <subsonic-response status="ok"/> on createPlaylist
            pls = self.get_user_playlists()
            matched = [p for p in pls if not p.get("is_liked") and p.get("name") == clean_title]
            if matched:
                pid = str(matched[-1]["id"])
        if not pid:
            raise RuntimeError("创建 Navidrome / Subsonic 歌单后未能获取到歌单 ID。")

        try:
            self._request(
                "updatePlaylist",
                {
                    "playlistId": pid,
                    "name": clean_title,
                    "comment": description or "",
                    "public": "true" if privacy_status == "PUBLIC" else "false",
                },
                method="POST",
            )
        except Exception:
            pass
        return pid

    def get_existing_track_ids(
        self,
        playlist_id: Optional[str],
        target_mode: str = "existing_playlist",
    ) -> Set[str]:
        pid = SUBSONIC_LIKED_ID if target_mode == "liked_songs" else (playlist_id or "")
        if not pid:
            return set()
        data = self.get_playlist_tracks(pid)
        return {str(t.get("source_id")) for t in (data.get("tracks") or []) if t.get("source_id")}

    def add_tracks(
        self,
        playlist_id: Optional[str],
        target_mode: str,
        candidates: List[Dict[str, Any]],
        seen_ids: Set[str],
        skip_duplicates: bool = True,
    ) -> int:
        to_add: List[str] = []
        for c in candidates:
            tid = str(c.get("track_id") or "").strip()
            if not tid:
                continue
            if skip_duplicates and tid in seen_ids:
                continue
            to_add.append(tid)
            seen_ids.add(tid)

        if not to_add:
            return 0

        if target_mode == "liked_songs":
            params = [("id", tid) for tid in to_add]
            self._request("star", params=params, method="POST")
            return len(to_add)

        if not playlist_id:
            raise ValueError("缺少目标 Navidrome / Subsonic 歌单 ID。")
        params = [("playlistId", playlist_id)] + [("songIdToAdd", tid) for tid in to_add]
        self._request("updatePlaylist", params=params, method="POST")
        return len(to_add)

    def get_dedupe_raw_items(self, playlist_id: str) -> Tuple[str, List[Dict[str, Any]]]:
        base_url, _, _ = self._require_auth()
        sr = self._request("getPlaylist", {"id": playlist_id})
        pl = sr.get("playlist") or {}
        title = str(pl.get("name") or "Subsonic Playlist")
        entries = _as_list(pl.get("entry"))
        items: List[Dict[str, Any]] = []
        for idx, s in enumerate(entries):
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id") or "")
            dur_sec = int(s.get("duration") or 0)
            album_id = str(s.get("albumId") or "").strip()
            items.append(
                {
                    "position": idx + 1,
                    "item_id": sid,
                    "videoId": sid,
                    "setVideoId": str(idx),
                    "can_remove": True,
                    "title": str(s.get("title") or "").strip(),
                    "artist": _extract_song_artist(s),
                    "album": str(s.get("album") or "").strip(),
                    "duration": format_duration_seconds(dur_sec) if dur_sec > 0 else "",
                    "duration_seconds": dur_sec,
                    "url": f"{base_url}/app/#/album/{album_id}/show" if album_id else base_url,
                    "extra": {"index": idx, "song_id": sid},
                }
            )
        return title, items

    def remove_playlist_duplicates(self, playlist_id: str, items: List[Dict[str, Any]]) -> int:
        if not items:
            return 0
        sr = self._request("getPlaylist", {"id": playlist_id})
        entries = _as_list((sr.get("playlist") or {}).get("entry"))
        if not entries:
            return 0

        indices_to_remove: Set[int] = set()
        for req_it in items:
            extra = req_it.get("extra") or {}
            want_id = str(extra.get("song_id") or req_it.get("item_id") or req_it.get("videoId") or "").strip()
            hint_idx = extra.get("index")
            if hint_idx is None and str(req_it.get("setVideoId") or "").isdigit():
                hint_idx = int(req_it["setVideoId"])

            if isinstance(hint_idx, int) and 0 <= hint_idx < len(entries):
                entry_id = str((entries[hint_idx] or {}).get("id") or "")
                if (not want_id or entry_id == want_id) and hint_idx not in indices_to_remove:
                    indices_to_remove.add(hint_idx)
                    continue

            if want_id:
                # Fallback: pick the last non-selected occurrence of want_id
                for r_idx in range(len(entries) - 1, -1, -1):
                    if r_idx not in indices_to_remove and str((entries[r_idx] or {}).get("id") or "") == want_id:
                        indices_to_remove.add(r_idx)
                        break

        if not indices_to_remove:
            return 0

        params: List[Tuple[str, Any]] = [("playlistId", playlist_id)]
        for idx in sorted(indices_to_remove, reverse=True):
            params.append(("songIndexToRemove", str(idx)))
        self._request("updatePlaylist", params=params, method="POST")
        return len(indices_to_remove)

    def build_playlist_url(self, playlist_id: Optional[str], target_mode: str = "new_playlist") -> str:
        auth = self._load_auth()
        base = str(auth.get("server_url") or "").rstrip("/")
        if not base:
            return ""
        if target_mode == "liked_songs" or playlist_id == SUBSONIC_LIKED_ID:
            return f"{base}/app/#/song"
        if playlist_id:
            return f"{base}/app/#/playlist/{playlist_id}/show"
        return base
