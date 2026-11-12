from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from backend.config import (
    DEFAULT_SPOTIFY_REDIRECT_URI,
    SPOTIFY_CACHE_FILE,
    SPOTIFY_CONFIG_FILE,
    SPOTIFY_REDIRECT_URI_ENV,
    read_json_file,
    write_json_file,
)
from backend.providers.base import PlatformProvider
from backend.text_utils import format_duration_ms

SPOTIFY_READ_SCOPES = "user-library-read playlist-read-private playlist-read-collaborative"
SPOTIFY_FULL_SCOPES = (
    "user-library-read user-library-modify "
    "playlist-read-private playlist-read-collaborative "
    "playlist-modify-public playlist-modify-private"
)


class SpotifyProvider(PlatformProvider):
    platform_id = "spotify"
    platform_name = "Spotify"

    def get_oauth(self, require_write: bool = False) -> Optional[SpotifyOAuth]:
        cfg = read_json_file(SPOTIFY_CONFIG_FILE, {})
        if not isinstance(cfg, dict):
            return None
        client_id = str(cfg.get("client_id") or "").strip()
        client_secret = str(cfg.get("client_secret") or "").strip()
        redirect_uri = SPOTIFY_REDIRECT_URI_ENV or str(cfg.get("redirect_uri") or DEFAULT_SPOTIFY_REDIRECT_URI).strip()
        if not client_id or not client_secret:
            return None

        # Always request full scopes for new auth URLs; if an older read-only cache exists and
        # require_write is False, inspect cached scope so existing sessions stay valid for reads.
        scope = SPOTIFY_FULL_SCOPES
        if not require_write and SPOTIFY_CACHE_FILE.exists():
            cached = read_json_file(SPOTIFY_CACHE_FILE, {})
            if isinstance(cached, dict) and cached.get("scope") and "playlist-modify" not in str(cached.get("scope")):
                scope = str(cached["scope"])

        return SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=scope,
            cache_path=str(SPOTIFY_CACHE_FILE),
            open_browser=False,
        )

    def get_client(self, require_write: bool = False) -> spotipy.Spotify:
        auth_manager = self.get_oauth(require_write=require_write)
        if not auth_manager:
            raise ValueError("尚未配置 Spotify Client ID & Secret。")
        token_info = auth_manager.validate_token(auth_manager.cache_handler.get_cached_token())
        if not token_info:
            if require_write:
                raise ValueError("Spotify 尚未授权写入权限，请在连接面板点击「授权登录 Spotify」更新权限。")
            raise ValueError("Spotify 尚未完成 OAuth 授权登录或登录已过期。")
        return spotipy.Spotify(auth_manager=auth_manager)

    def save_config(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str = DEFAULT_SPOTIFY_REDIRECT_URI,
    ) -> Dict[str, Any]:
        cid = client_id.strip()
        sec = client_secret.strip()
        if not cid or not sec:
            raise ValueError("请填写完整的 Spotify Client ID 和 Client Secret。")
        data = {
            "client_id": cid,
            "client_secret": sec,
            "redirect_uri": SPOTIFY_REDIRECT_URI_ENV or redirect_uri.strip() or DEFAULT_SPOTIFY_REDIRECT_URI,
        }
        write_json_file(SPOTIFY_CONFIG_FILE, data)
        # Build OAuth with full read + write scopes so user gets bidirectional capability
        oauth = SpotifyOAuth(
            client_id=cid,
            client_secret=sec,
            redirect_uri=data["redirect_uri"],
            scope=SPOTIFY_FULL_SCOPES,
            cache_path=str(SPOTIFY_CACHE_FILE),
            open_browser=False,
        )
        return {"success": True, "auth_url": oauth.get_authorize_url()}

    def get_status(self) -> Dict[str, Any]:
        cfg = read_json_file(SPOTIFY_CONFIG_FILE, {})
        if not isinstance(cfg, dict):
            cfg = {}
        auth_manager = self.get_oauth(require_write=False)
        if not auth_manager:
            return {
                "platform": "spotify",
                "configured": False,
                "authenticated": False,
                "connected": False,
                "has_write_scope": False,
                "client_id": cfg.get("client_id", ""),
                "redirect_uri": SPOTIFY_REDIRECT_URI_ENV or cfg.get("redirect_uri", DEFAULT_SPOTIFY_REDIRECT_URI),
            }

        try:
            token_info = auth_manager.validate_token(auth_manager.cache_handler.get_cached_token())
            if token_info:
                sp = spotipy.Spotify(auth_manager=auth_manager)
                me = sp.current_user()
                scope_str = str(token_info.get("scope") or "")
                has_write = "playlist-modify" in scope_str
                user_name = me.get("display_name") or me.get("id") or "Spotify User"
                return {
                    "platform": "spotify",
                    "configured": True,
                    "authenticated": True,
                    "connected": True,
                    "has_write_scope": has_write,
                    "user_name": user_name,
                    "user_id": me.get("id", ""),
                    "message": f"已登录 ({user_name})",
                    "client_id": cfg.get("client_id", ""),
                    "redirect_uri": SPOTIFY_REDIRECT_URI_ENV or cfg.get("redirect_uri", DEFAULT_SPOTIFY_REDIRECT_URI),
                }
        except Exception:
            pass

        return {
            "platform": "spotify",
            "configured": True,
            "authenticated": False,
            "connected": False,
            "has_write_scope": False,
            "client_id": cfg.get("client_id", ""),
            "redirect_uri": SPOTIFY_REDIRECT_URI_ENV or cfg.get("redirect_uri", DEFAULT_SPOTIFY_REDIRECT_URI),
        }

    def disconnect(self) -> Dict[str, Any]:
        if SPOTIFY_CACHE_FILE.exists():
            SPOTIFY_CACHE_FILE.unlink()
        return {"success": True, "message": "已退出 Spotify OAuth 登录会话"}

    def get_user_playlists(self) -> List[Dict[str, Any]]:
        sp = self.get_client(require_write=False)
        me = sp.current_user() or {}
        my_id = me.get("id", "")
        items: List[Dict[str, Any]] = []

        saved = sp.current_user_saved_tracks(limit=1)
        liked_total = saved.get("total", 0) if saved else 0
        items.append(
            {
                "id": "liked_songs",
                "playlistId": "liked_songs",
                "name": "❤️ 我喜欢的音乐 (Liked Songs)",
                "title": "❤️ 我喜欢的音乐 (Liked Songs)",
                "tracks_total": liked_total,
                "count": liked_total,
                "owner": "Me",
                "is_liked": True,
                "editable": False,
            }
        )

        offset = 0
        while True:
            res = sp.current_user_playlists(limit=50, offset=offset)
            batch = res.get("items", []) if res else []
            for p in batch:
                if not p:
                    continue
                owner_obj = p.get("owner") or {}
                owner_id = owner_obj.get("id", "")
                editable = bool(p.get("collaborative") or (my_id and owner_id == my_id))
                # Feb 2026 API: playlist "tracks" field renamed to "items"
                total = (p.get("items") or p.get("tracks") or {}).get("total", "")
                name = p.get("name", "Untitled")
                items.append(
                    {
                        "id": p.get("id"),
                        "playlistId": p.get("id"),
                        "name": name,
                        "title": name,
                        "tracks_total": total,
                        "count": total,
                        "owner": owner_obj.get("display_name") or owner_id,
                        "is_liked": False,
                        "editable": editable,
                    }
                )
            if not res or not res.get("next") or len(batch) < 50:
                break
            offset += 50
        return items

    @staticmethod
    def _parse_sp_track(t: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not t or t.get("is_local"):
            return None
        title = (t.get("name") or "").strip()
        if not title:
            return None
        artists = ", ".join([a.get("name", "") for a in (t.get("artists") or []) if a.get("name")])
        uri = t.get("uri") or ""
        tid = t.get("id") or ""
        return {
            "title": title,
            "artist": artists,
            "album": (t.get("album") or {}).get("name", ""),
            "duration_ms": int(t.get("duration_ms") or 0),
            "isrc": (t.get("external_ids") or {}).get("isrc", ""),
            "spotify_uri": uri,
            "source_platform": "spotify",
            "source_id": uri or tid,
            "extra": {
                "url": (t.get("external_urls") or {}).get("spotify", ""),
            },
        }

    # ------------------------------------------------------------------
    # Spotify Web API February 2026 changes (Development-mode apps):
    #   GET/POST/DELETE /playlists/{id}/tracks  ->  /playlists/{id}/items  (old ones return 403)
    #   playlist item field "track"             ->  "item"
    #   POST /users/{id}/playlists              ->  POST /me/playlists
    #   PUT /me/tracks                          ->  PUT /me/library?uris=... (max 40)
    #   GET /search limit max 50                ->  max 10
    # Spotipy's helpers still call the removed endpoints, so we call the new ones directly.
    # ------------------------------------------------------------------

    @staticmethod
    def _item_track(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        raw = raw or {}
        return raw.get("item") or raw.get("track")

    @staticmethod
    def _iter_playlist_items(sp: spotipy.Spotify, playlist_id: str, fields: Optional[str] = None):
        offset = 0
        while True:
            kwargs: Dict[str, Any] = {"limit": 50, "offset": offset}
            if fields:
                kwargs["fields"] = fields
            try:
                res = sp._get(f"playlists/{playlist_id}/items", **kwargs)
            except spotipy.SpotifyException as exc:
                if exc.http_status == 403:
                    raise PermissionError(
                        "Spotify 只允许读取你本人创建或协作的歌单内容（2026 年起开发模式应用的限制）。"
                        "如需读取他人歌单，请先在 Spotify 中「复制到新歌单」再读取。"
                    )
                raise
            batch = (res or {}).get("items") or []
            for raw in batch:
                yield raw
            if not res or not res.get("next") or not batch:
                break
            offset += len(batch)

    def get_playlist_tracks(self, playlist_id: str) -> Dict[str, Any]:
        sp = self.get_client(require_write=False)
        tracks: List[Dict[str, Any]] = []
        playlist_name = "Spotify Liked Songs" if playlist_id == "liked_songs" else "Spotify Playlist"

        if playlist_id == "liked_songs":
            offset = 0
            while True:
                res = sp.current_user_saved_tracks(limit=50, offset=offset)
                batch = res.get("items", []) if res else []
                for item in batch:
                    parsed = self._parse_sp_track(self._item_track(item))
                    if parsed:
                        tracks.append(parsed)
                if not res or not res.get("next") or len(batch) < 50:
                    break
                offset += 50
        else:
            pl_info = sp.playlist(playlist_id, fields="name")
            if pl_info and pl_info.get("name"):
                playlist_name = pl_info["name"]

            for item in self._iter_playlist_items(sp, playlist_id):
                parsed = self._parse_sp_track(self._item_track(item))
                if parsed:
                    tracks.append(parsed)

        return {
            "playlist_name": playlist_name,
            "count": len(tracks),
            "tracks": tracks,
        }

    def import_from_url(self, url_or_id: str) -> Dict[str, Any]:
        s = url_or_id.strip()
        m = re.search(r"playlist[/:]([A-Za-z0-9]+)", s)
        pid = m.group(1) if m else s
        if not pid:
            raise ValueError("无法识别 Spotify 歌单链接或 ID。")
        return self.get_playlist_tracks(pid)

    @staticmethod
    def _track_to_candidate(t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        uri = t.get("uri") or ""
        tid = t.get("id") or ""
        if not uri and not tid:
            return None
        artists = ", ".join([a.get("name", "") for a in (t.get("artists") or []) if a.get("name")])
        dur_ms = int(t.get("duration_ms") or 0)
        return {
            "platform": "spotify",
            "track_id": uri or f"spotify:track:{tid}",
            "display_id": tid,
            "title": t.get("name", ""),
            "artist": artists,
            "album": (t.get("album") or {}).get("name", ""),
            "duration": format_duration_ms(dur_ms),
            "duration_seconds": dur_ms // 1000,
            "isrc": (t.get("external_ids") or {}).get("isrc", ""),
            "resultType": "song",
            "url": (t.get("external_urls") or {}).get("spotify", f"https://open.spotify.com/track/{tid}"),
        }

    def search_by_isrc(self, isrc: str) -> List[Dict[str, Any]]:
        sp = self.get_client(require_write=False)
        res = sp.search(q=f"isrc:{isrc}", type="track", limit=3)
        items = ((res or {}).get("tracks") or {}).get("items") or []
        out = []
        for t in items:
            c = self._track_to_candidate(t)
            if c:
                out.append(c)
        return out

    def search_candidates(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        sp = self.get_client(require_write=False)
        res = sp.search(q=query, type="track", limit=max(1, min(10, limit)))
        items = ((res or {}).get("tracks") or {}).get("items") or []
        out = []
        for t in items:
            c = self._track_to_candidate(t)
            if c:
                out.append(c)
        return out

    def create_playlist(
        self,
        title: str,
        description: str = "",
        privacy_status: str = "PRIVATE",
    ) -> str:
        sp = self.get_client(require_write=True)
        is_public = privacy_status == "PUBLIC"
        pl = sp._post(
            "me/playlists",
            payload={
                "name": title or "Switch Music Playlist",
                "public": is_public,
                "description": description or "Imported via Switch Music",
            },
        )
        return str(pl["id"])

    def get_existing_track_ids(
        self,
        playlist_id: Optional[str],
        target_mode: str = "existing_playlist",
    ) -> Set[str]:
        sp = self.get_client(require_write=False)
        ids: Set[str] = set()
        # Errors propagate: silently returning an empty set would disable duplicate protection.
        if target_mode == "liked_songs":
            offset = 0
            while offset < 50000:
                res = sp.current_user_saved_tracks(limit=50, offset=offset)
                batch = (res or {}).get("items") or []
                for it in batch:
                    t = self._item_track(it) or {}
                    if t.get("uri"):
                        ids.add(t["uri"])
                if not res or not res.get("next") or len(batch) < 50:
                    break
                offset += 50
        elif playlist_id:
            for it in self._iter_playlist_items(sp, playlist_id, fields="items(item(uri)),next"):
                t = self._item_track(it) or {}
                if t.get("uri"):
                    ids.add(t["uri"])
        return ids

    def add_tracks(
        self,
        playlist_id: Optional[str],
        target_mode: str,
        candidates: List[Dict[str, Any]],
        seen_ids: Set[str],
        skip_duplicates: bool = True,
    ) -> int:
        sp = self.get_client(require_write=True)
        uris: List[str] = []
        for c in candidates:
            uri = str(c.get("track_id") or "").strip()
            if not uri:
                continue
            if not uri.startswith("spotify:track:") and ":" not in uri:
                uri = f"spotify:track:{uri}"
            if skip_duplicates:
                if uri in seen_ids:
                    continue
                seen_ids.add(uri)
            uris.append(uri)

        if not uris:
            return 0

        added = 0
        if target_mode == "liked_songs":
            for i in range(0, len(uris), 40):
                chunk = uris[i : i + 40]
                sp._put("me/library", uris=",".join(chunk))
                added += len(chunk)
                time.sleep(0.1)
            return added

        if not playlist_id:
            raise ValueError("未指定目标 Spotify 歌单 ID。")

        for i in range(0, len(uris), 100):
            chunk = uris[i : i + 100]
            sp._post(f"playlists/{playlist_id}/items", payload={"uris": chunk})
            added += len(chunk)
            time.sleep(0.1)
        return added

    def get_dedupe_raw_items(self, playlist_id: str) -> Tuple[str, List[Dict[str, Any]]]:
        if playlist_id == "liked_songs":
            raise ValueError("Spotify「我喜欢的音乐」本身不允许重复收藏同一 URI，请选择普通自建歌单进行去重。")
        sp = self.get_client(require_write=False)
        pl_info = sp.playlist(playlist_id, fields="name")
        pl_title = (pl_info or {}).get("name") or "Spotify Playlist"

        items: List[Dict[str, Any]] = []
        pos = 0
        for raw in self._iter_playlist_items(sp, playlist_id):
            pos += 1
            t = self._item_track(raw)
            if not t or t.get("is_local"):
                continue
            uri = t.get("uri") or ""
            tid = t.get("id") or ""
            artists_list = [a.get("name", "") for a in (t.get("artists") or []) if a.get("name")]
            dur_ms = int(t.get("duration_ms") or 0)
            items.append(
                {
                    "position": pos,
                    "item_id": uri,
                    "videoId": uri,
                    "setVideoId": str(pos - 1),  # 0-based position in Spotify playlist
                    "can_remove": bool(uri),
                    "title": t.get("name") or "Unknown",
                    "artist": ", ".join(artists_list),
                    "primary_artist": artists_list[0] if artists_list else "",
                    "album": (t.get("album") or {}).get("name", ""),
                    "duration": format_duration_ms(dur_ms),
                    "duration_seconds": dur_ms // 1000,
                    "url": f"https://open.spotify.com/track/{tid}" if tid else "",
                    "extra": {"zero_index": pos - 1, "uri": uri},
                }
            )
        return pl_title, items

    def remove_playlist_duplicates(self, playlist_id: str, items: List[Dict[str, Any]]) -> int:
        """
        The Feb 2026 DELETE /playlists/{id}/items only accepts URIs (no positions) and removes
        EVERY occurrence of each URI. To delete only the selected copies we:
          1. re-read the playlist and compute the desired final order,
          2. delete all occurrences of every affected URI,
          3. re-insert the copies that should be kept at their exact final positions.
        """
        sp = self.get_client(require_write=True)
        remove_positions: Set[int] = set()
        for it in items:
            z_raw = it.get("setVideoId") if it.get("setVideoId") not in (None, "") else (it.get("extra") or {}).get("zero_index")
            if z_raw is not None and str(z_raw).isdigit():
                remove_positions.add(int(z_raw))
        if not remove_positions:
            raise ValueError("没有可移除的有效 Spotify 曲目位置项。")

        current: List[str] = []
        for raw in self._iter_playlist_items(sp, playlist_id, fields="items(item(uri)),next"):
            current.append(str((self._item_track(raw) or {}).get("uri") or ""))

        # Guard against the playlist having changed since the scan.
        requested = {str(it.get("item_id") or (it.get("extra") or {}).get("uri") or ""): None for it in items}
        for z in remove_positions:
            if z >= len(current) or (current[z] not in requested):
                raise ValueError("Spotify 歌单在扫描后已发生变化，请重新扫描后再移除。")

        affected = sorted({current[z] for z in remove_positions if current[z]})
        final = [u for i, u in enumerate(current) if i not in remove_positions]

        for i in range(0, len(affected), 100):
            sp._delete(f"playlists/{playlist_id}/items", payload={"items": [{"uri": u} for u in affected[i : i + 100]]})
            time.sleep(0.15)

        affected_set = set(affected)
        for j, uri in enumerate(final):
            if uri in affected_set:
                sp._post(f"playlists/{playlist_id}/items", payload={"uris": [uri], "position": j})
                time.sleep(0.1)
        return len(remove_positions)

    def build_playlist_url(self, playlist_id: Optional[str], target_mode: str = "new_playlist") -> str:
        if target_mode == "liked_songs" or playlist_id == "liked_songs":
            return "https://open.spotify.com/collection/tracks"
        if playlist_id:
            return f"https://open.spotify.com/playlist/{playlist_id}"
        return "https://open.spotify.com/"
