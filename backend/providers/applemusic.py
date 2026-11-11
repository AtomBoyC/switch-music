from __future__ import annotations

import base64
import json
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.config import (
    APPLEMUSIC_AUTH_FILE,
    APPLEMUSIC_TOKEN_CACHE_FILE,
    make_retry_session,
    parse_cookie_and_headers,
    read_json_file,
    write_json_file,
)
from backend.providers.base import PlatformProvider
from backend.text_utils import format_duration_seconds

AMP_API = "https://amp-api.music.apple.com"
WEB_ORIGIN = "https://music.apple.com"
DEFAULT_STOREFRONT = "cn"
LIBRARY_SONGS_ID = "library_songs"


def _jwt_payload(token: str) -> Dict[str, Any]:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


class AppleMusicProvider(PlatformProvider):
    """
    Apple Music via the music.apple.com web player API (amp-api).

    * Developer token: the public JWT shipped in the music.apple.com web bundle (auto-fetched
      and cached), or the `authorization: Bearer ...` header from the user's pasted cURL.
    * User token: the `media-user-token` header / cookie of a logged-in music.apple.com session.
    """

    platform_id = "applemusic"
    platform_name = "Apple Music"

    UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    )

    # ------------------------------------------------------------------
    # Tokens
    # ------------------------------------------------------------------

    def _load_auth(self) -> Dict[str, Any]:
        data = read_json_file(APPLEMUSIC_AUTH_FILE, {})
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _token_valid(token: str, margin: int = 3600) -> bool:
        exp = _jwt_payload(token).get("exp")
        return bool(token) and (not exp or int(exp) - margin > time.time())

    def _scrape_developer_token(self) -> str:
        sess = make_retry_session()
        sess.headers["User-Agent"] = self.UA
        home = sess.get(f"{WEB_ORIGIN}/us/browse", timeout=20)
        home.raise_for_status()
        scripts = re.findall(r'<script[^>]+src="([^"]+\.js)"', home.text)
        for src in scripts:
            if "/assets/" not in src:
                continue
            url = src if src.startswith("http") else WEB_ORIGIN + src
            js = sess.get(url, timeout=30).text
            for m in re.finditer(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", js):
                tok = m.group(0)
                payload = _jwt_payload(tok)
                if payload.get("root_https_origin") and self._token_valid(tok, margin=0):
                    return tok
        raise RuntimeError("未能从 music.apple.com 获取 Apple Music 开发者令牌，请稍后重试或粘贴登录后的 cURL。")

    def _developer_token(self, force_refresh: bool = False) -> str:
        auth = self._load_auth()
        user_dev = str(auth.get("developer_token") or "")
        if user_dev and not force_refresh and self._token_valid(user_dev):
            return user_dev
        cache = read_json_file(APPLEMUSIC_TOKEN_CACHE_FILE, {})
        cached = str((cache or {}).get("token") or "")
        if cached and not force_refresh and self._token_valid(cached):
            return cached
        tok = self._scrape_developer_token()
        write_json_file(APPLEMUSIC_TOKEN_CACHE_FILE, {"token": tok, "fetched_at": int(time.time())})
        return tok

    def _storefront(self) -> str:
        return str(self._load_auth().get("storefront") or DEFAULT_STOREFRONT)

    def _require_user(self) -> str:
        mut = str(self._load_auth().get("media_user_token") or "")
        if not mut:
            raise ValueError("尚未连接 Apple Music 账号，请先在顶部「Apple Music」卡片粘贴 music.apple.com 的 cURL。")
        return mut

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _api(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
        user: bool = False,
        media_user_token: Optional[str] = None,
        dev_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        last_status = 0
        for attempt in range(2):
            token = dev_token or self._developer_token(force_refresh=attempt > 0)
            headers = {
                "Authorization": f"Bearer {token}",
                "Origin": WEB_ORIGIN,
                "Referer": WEB_ORIGIN + "/",
                "User-Agent": self.UA,
                "Accept": "application/json",
            }
            if user or media_user_token:
                headers["Media-User-Token"] = media_user_token or self._require_user()
            if body is not None:
                headers["Content-Type"] = "application/json"
            sess = make_retry_session()
            resp = sess.request(
                method,
                AMP_API + path,
                params=params,
                data=json.dumps(body).encode("utf-8") if body is not None else None,
                headers=headers,
                timeout=20,
            )
            last_status = resp.status_code
            if resp.status_code == 401 and attempt == 0 and not dev_token:
                continue  # developer token rotated: refetch once
            if resp.status_code in (401, 403) and (user or media_user_token):
                raise PermissionError("Apple Music 登录态无效或已过期，请重新在 music.apple.com 复制 cURL 连接。")
            if resp.status_code >= 400:
                detail = ""
                try:
                    errs = resp.json().get("errors") or []
                    detail = "; ".join(str(e.get("detail") or e.get("title") or "") for e in errs)
                except ValueError:
                    detail = resp.text[:200]
                raise RuntimeError(f"Apple Music 接口错误 HTTP {resp.status_code}: {detail}")
            if resp.status_code == 204 or not resp.content:
                return {}
            return resp.json()
        raise RuntimeError(f"Apple Music 接口鉴权失败 (HTTP {last_status})")

    def _paginate(self, path: str, params: Optional[Dict[str, Any]] = None, user: bool = False, cap: int = 20000) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        next_path: Optional[str] = path
        q = dict(params or {})
        while next_path and len(out) < cap:
            if "?" in next_path:
                base, qs = next_path.split("?", 1)
                merged = {**q, **dict(urllib.parse.parse_qsl(qs))}
                res = self._api("GET", base, params=merged, user=user)
            else:
                res = self._api("GET", next_path, params=q, user=user)
            out.extend(res.get("data") or [])
            next_path = res.get("next")
        return out

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def save_auth(self, raw_input: str) -> Dict[str, Any]:
        raw = (raw_input or "").strip()
        headers: Dict[str, str] = {}
        cookies: Dict[str, str] = {}
        try:
            _, cookies, headers = parse_cookie_and_headers(raw)
        except ValueError:
            # Request without cookies but with headers (amp-api requests carry the token as a header).
            for m in re.finditer(r"(?:-H|--header)\s+['\"]([^:'\"]+):\s*([^'\"]*)['\"]", raw):
                headers[m.group(1).strip().lower()] = m.group(2).strip()
            for line in raw.splitlines():
                if ":" in line and not line.strip().lower().startswith(("curl", "http")):
                    k, v = line.split(":", 1)
                    headers.setdefault(k.strip().lower(), v.strip())

        mut = headers.get("media-user-token") or cookies.get("media-user-token") or ""
        if not mut:
            m = re.search(r"media-user-token[\"'=:\s]+([A-Za-z0-9+/=_\-]{40,})", raw)
            mut = m.group(1) if m else ""
        if not mut:
            raise ValueError(
                "未找到 media-user-token。请确认已在 music.apple.com 登录，并复制一条发往 amp-api.music.apple.com 的请求 cURL。"
            )

        dev = ""
        bearer = headers.get("authorization", "")
        if bearer.lower().startswith("bearer "):
            cand = bearer[7:].strip()
            if self._token_valid(cand, margin=0):
                dev = cand

        res = self._api("GET", "/v1/me/storefront", media_user_token=mut, dev_token=dev or None)
        sf_list = res.get("data") or []
        storefront = (sf_list[0].get("id") if sf_list else "") or DEFAULT_STOREFRONT
        sf_name = ((sf_list[0].get("attributes") or {}).get("name") if sf_list else "") or storefront.upper()
        nickname = f"Apple Music 用户 ({sf_name})"

        write_json_file(
            APPLEMUSIC_AUTH_FILE,
            {
                "media_user_token": mut,
                "developer_token": dev,
                "storefront": storefront,
                "nickname": nickname,
                "updated_at": int(time.time()),
            },
        )
        return {
            "success": True,
            "connected": True,
            "user_id": storefront,
            "user_name": nickname,
            "message": f"Apple Music 连接成功（商店地区: {sf_name}）！",
        }

    def get_status(self) -> Dict[str, Any]:
        auth = self._load_auth()
        if not auth.get("media_user_token"):
            return {"platform": "applemusic", "connected": False, "message": "未登录（支持免登录链接导入公开歌单）"}
        nickname = auth.get("nickname") or "Apple Music"
        try:
            self._api("GET", "/v1/me/storefront", user=True)
            return {
                "platform": "applemusic",
                "connected": True,
                "user_id": auth.get("storefront") or "",
                "user_name": nickname,
                "message": f"已登录 ({nickname})",
            }
        except Exception:
            return {"platform": "applemusic", "connected": False, "message": "Apple Music 登录态已过期，请更新 cURL"}

    def disconnect(self) -> Dict[str, Any]:
        if APPLEMUSIC_AUTH_FILE.exists():
            APPLEMUSIC_AUTH_FILE.unlink()
        return {"success": True, "message": "已断开 Apple Music 连接"}

    # ------------------------------------------------------------------
    # Conversions
    # ------------------------------------------------------------------

    @staticmethod
    def _catalog_id(item: Dict[str, Any]) -> str:
        attrs = item.get("attributes") or {}
        pp = attrs.get("playParams") or {}
        if item.get("type") == "songs":
            return str(item.get("id") or "")
        return str(pp.get("catalogId") or pp.get("purchasedId") or "")

    def _item_to_track(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        attrs = item.get("attributes") or {}
        title = (attrs.get("name") or "").strip()
        if not title:
            return None
        catalog = ((item.get("relationships") or {}).get("catalog") or {}).get("data") or []
        cat_attrs = (catalog[0].get("attributes") or {}) if catalog else {}
        cid = self._catalog_id(item) or (str(catalog[0].get("id")) if catalog else "")
        return {
            "title": title,
            "artist": attrs.get("artistName") or "",
            "album": attrs.get("albumName") or "",
            "duration_ms": int(attrs.get("durationInMillis") or 0),
            "isrc": attrs.get("isrc") or cat_attrs.get("isrc") or "",
            "spotify_uri": "",
            "source_platform": "applemusic",
            "source_id": cid,
            "extra": {
                "catalog_id": cid,
                "library_id": item.get("id") if str(item.get("id", "")).startswith("i.") else "",
                "url": attrs.get("url") or cat_attrs.get("url") or "",
            },
        }

    @staticmethod
    def _song_to_candidate(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        attrs = item.get("attributes") or {}
        sid = str(item.get("id") or "")
        if not sid or not attrs.get("name"):
            return None
        dur = int(attrs.get("durationInMillis") or 0) // 1000
        return {
            "platform": "applemusic",
            "track_id": sid,
            "display_id": sid,
            "title": attrs.get("name") or "",
            "artist": attrs.get("artistName") or "",
            "album": attrs.get("albumName") or "",
            "duration": format_duration_seconds(dur),
            "duration_seconds": dur,
            "isrc": attrs.get("isrc") or "",
            "resultType": "song",
            "url": attrs.get("url") or "",
            "extra": {"catalog_id": sid},
        }

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    def get_user_playlists(self) -> List[Dict[str, Any]]:
        self._require_user()
        items: List[Dict[str, Any]] = [
            {
                "id": LIBRARY_SONGS_ID,
                "playlistId": LIBRARY_SONGS_ID,
                "name": "❤️ 资料库全部歌曲",
                "title": "❤️ 资料库全部歌曲",
                "tracks_total": "",
                "count": "",
                "is_liked": True,
                "editable": True,
            }
        ]
        for p in self._paginate("/v1/me/library/playlists", {"limit": 100}, user=True, cap=2000):
            attrs = p.get("attributes") or {}
            pid = str(p.get("id") or "")
            if not pid:
                continue
            name = attrs.get("name") or "未命名歌单"
            items.append(
                {
                    "id": pid,
                    "playlistId": pid,
                    "name": name,
                    "title": name,
                    "tracks_total": "",
                    "count": "",
                    "is_liked": False,
                    "editable": bool(attrs.get("canEdit", True)),
                }
            )
        return items

    @staticmethod
    def _parse_url(url_or_id: str) -> Tuple[str, str, str]:
        """Return (kind, id, storefront) where kind in playlist | library_playlist | album."""
        s = (url_or_id or "").strip()
        m = re.search(
            r"music\.apple\.com/([a-z]{2})/(playlist|album)/(?:[^/?#\s]+/)?((?:pl\.[A-Za-z0-9\-.]+)|\d+)(?:[/?#\s]|$)", s
        )
        if m:
            return ("album" if m.group(2) == "album" else "playlist"), m.group(3), m.group(1)
        m = re.search(r"music\.apple\.com/(?:[a-z]{2}/)?library/playlist/(p\.[A-Za-z0-9]+)", s)
        if m:
            return "library_playlist", m.group(1), ""
        m = re.search(r"\b(pl\.[A-Za-z0-9\-.]+)", s)
        if m:
            return "playlist", m.group(1), ""
        m = re.search(r"\b(p\.[A-Za-z0-9]{6,})\b", s)
        if m:
            return "library_playlist", m.group(1), ""
        raise ValueError(
            "无法识别 Apple Music 链接（示例：https://music.apple.com/cn/playlist/xxx/pl.xxxxxx 或专辑链接）。"
        )

    def _catalog_collection(self, kind: str, cid: str, storefront: str) -> Dict[str, Any]:
        sf = storefront or self._storefront()
        coll = "albums" if kind == "album" else "playlists"
        meta = self._api("GET", f"/v1/catalog/{sf}/{coll}/{cid}")
        data = (meta.get("data") or [{}])[0]
        name = (data.get("attributes") or {}).get("name") or "Apple Music 歌单"
        raw = self._paginate(f"/v1/catalog/{sf}/{coll}/{cid}/tracks", {"limit": 100 if kind == "album" else 300})
        tracks = [t for t in (self._item_to_track(it) for it in raw if it.get("type") == "songs") if t]
        if not tracks:
            raise ValueError("该 Apple Music 歌单为空或在当前商店地区不可用。")
        return {"playlist_name": name, "count": len(tracks), "tracks": tracks}

    def get_playlist_tracks(self, playlist_id: str) -> Dict[str, Any]:
        pid = (playlist_id or "").strip()
        if pid == LIBRARY_SONGS_ID:
            raw = self._paginate("/v1/me/library/songs", {"limit": 100, "include": "catalog"}, user=True)
            tracks = [t for t in (self._item_to_track(it) for it in raw) if t]
            return {"playlist_name": "Apple Music 资料库", "count": len(tracks), "tracks": tracks}
        if pid.startswith("p."):
            meta = self._api("GET", f"/v1/me/library/playlists/{pid}", user=True)
            name = (((meta.get("data") or [{}])[0]).get("attributes") or {}).get("name") or "Apple Music 歌单"
            raw = self._paginate(
                f"/v1/me/library/playlists/{pid}/tracks", {"limit": 100, "include": "catalog"}, user=True
            )
            tracks = [t for t in (self._item_to_track(it) for it in raw) if t]
            return {"playlist_name": name, "count": len(tracks), "tracks": tracks}
        kind, cid, sf = self._parse_url(pid)
        if kind == "library_playlist":
            return self.get_playlist_tracks(cid)
        return self._catalog_collection(kind, cid, sf)

    def import_from_url(self, url_or_id: str) -> Dict[str, Any]:
        m = re.search(r"https?://apple\.co/[^\s\"'<>]+", url_or_id or "")
        if m:  # short share link -> follow redirect to music.apple.com
            try:
                r = make_retry_session().get(m.group(0), headers={"User-Agent": self.UA}, allow_redirects=True, timeout=10)
                url_or_id = r.url
            except Exception:
                pass
        kind, cid, sf = self._parse_url(url_or_id)
        if kind == "library_playlist":
            return self.get_playlist_tracks(cid)
        return self._catalog_collection(kind, cid, sf)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_candidates(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        res = self._api(
            "GET",
            f"/v1/catalog/{self._storefront()}/search",
            params={"term": query, "types": "songs", "limit": max(1, min(25, limit))},
        )
        items = (((res.get("results") or {}).get("songs") or {}).get("data")) or []
        return [c for c in (self._song_to_candidate(it) for it in items) if c]

    def search_by_isrc(self, isrc: str) -> List[Dict[str, Any]]:
        res = self._api("GET", f"/v1/catalog/{self._storefront()}/songs", params={"filter[isrc]": isrc})
        return [c for c in (self._song_to_candidate(it) for it in res.get("data") or []) if c][:3]

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def create_playlist(self, title: str, description: str = "", privacy_status: str = "PRIVATE") -> str:
        body = {
            "attributes": {"name": (title or "Switch Music Playlist").strip()[:100], "description": description or ""},
            "relationships": {"tracks": {"data": []}},
        }
        res = self._api("POST", "/v1/me/library/playlists", body=body, user=True)
        data = res.get("data") or []
        if not data or not data[0].get("id"):
            raise RuntimeError(f"创建 Apple Music 歌单返回异常: {res}")
        return str(data[0]["id"])

    def get_existing_track_ids(self, playlist_id: Optional[str], target_mode: str = "existing_playlist") -> Set[str]:
        if target_mode == "liked_songs":
            raw = self._paginate("/v1/me/library/songs", {"limit": 100}, user=True)
        elif playlist_id:
            raw = self._paginate(f"/v1/me/library/playlists/{playlist_id}/tracks", {"limit": 100}, user=True)
        else:
            return set()
        return {cid for cid in (self._catalog_id(it) for it in raw) if cid}

    def add_tracks(
        self,
        playlist_id: Optional[str],
        target_mode: str,
        candidates: List[Dict[str, Any]],
        seen_ids: Set[str],
        skip_duplicates: bool = True,
    ) -> int:
        song_ids: List[str] = []
        for c in candidates:
            sid = str((c.get("extra") or {}).get("catalog_id") or c.get("track_id") or "").strip()
            if not sid.isdigit():
                continue
            if skip_duplicates:
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)
            song_ids.append(sid)
        added = 0
        for i in range(0, len(song_ids), 50):
            batch = song_ids[i : i + 50]
            if target_mode == "liked_songs":
                # Add to library, then mark each song as Loved (Apple's equivalent of "liked").
                self._api("POST", "/v1/me/library", params={"ids[songs]": ",".join(batch)}, user=True)
                for sid in batch:
                    try:
                        self._api(
                            "PUT",
                            f"/v1/me/ratings/songs/{sid}",
                            body={"type": "rating", "attributes": {"value": 1}},
                            user=True,
                        )
                    except Exception:
                        pass  # library add already succeeded; loving is best-effort
            else:
                if not playlist_id:
                    raise ValueError("未指定目标 Apple Music 歌单。")
                self._api(
                    "POST",
                    f"/v1/me/library/playlists/{playlist_id}/tracks",
                    body={"data": [{"id": sid, "type": "songs"} for sid in batch]},
                    user=True,
                )
            added += len(batch)
            time.sleep(0.25)
        return added

    def get_dedupe_raw_items(self, playlist_id: str) -> Tuple[str, List[Dict[str, Any]]]:
        data = self.get_playlist_tracks(playlist_id)
        items: List[Dict[str, Any]] = []
        for idx, t in enumerate(data.get("tracks") or []):
            dur_s = int(t.get("duration_ms") or 0) // 1000
            artist = t.get("artist") or ""
            ex = t.get("extra") or {}
            items.append(
                {
                    "position": idx + 1,
                    "item_id": t.get("source_id") or "",
                    "videoId": t.get("source_id") or "",
                    "setVideoId": ex.get("library_id") or "",
                    "can_remove": False,
                    "title": t.get("title") or "Unknown",
                    "artist": artist,
                    "primary_artist": artist.split(",")[0].strip() if artist else "",
                    "album": t.get("album") or "",
                    "duration": format_duration_seconds(dur_s),
                    "duration_seconds": dur_s,
                    "url": ex.get("url") or "",
                    "extra": {},
                }
            )
        return data.get("playlist_name") or "Apple Music 歌单", items

    def remove_playlist_duplicates(self, playlist_id: str, items: List[Dict[str, Any]]) -> int:
        raise ValueError("Apple Music 官方接口不支持从歌单中移除单曲，请根据扫描结果在「音乐」App 中手动删除重复曲目。")

    def build_playlist_url(self, playlist_id: Optional[str], target_mode: str = "new_playlist") -> str:
        if playlist_id and str(playlist_id).startswith("p."):
            return f"{WEB_ORIGIN}/library/playlist/{playlist_id}"
        return f"{WEB_ORIGIN}/library/songs" if target_mode == "liked_songs" else f"{WEB_ORIGIN}/library"
