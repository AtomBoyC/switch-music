from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from ytmusicapi import YTMusic
from ytmusicapi.helpers import get_authorization, initialize_headers, sapisid_from_cookie

from backend.config import YTM_AUTH_FILE, parse_cookie_and_headers, write_json_file
from backend.providers.base import PlatformProvider
from backend.text_utils import format_duration_seconds, parse_duration_seconds


def build_ytm_headers_from_any_input(raw: str) -> Dict[str, str]:
    cookie_str, cookie_dict, user_headers = parse_cookie_and_headers(raw)

    sapisid = sapisid_from_cookie(cookie_str)
    if not sapisid:
        sapisid = cookie_dict.get("__Secure-3PAPISID") or cookie_dict.get("SAPISID") or ""
    if not sapisid:
        raise ValueError(
            "Cookie 中缺少 YouTube Music 登录凭据 (__Secure-3PAPISID / SAPISID)，请确认已在 music.youtube.com 登录账号。"
        )

    ignore_headers = {"host", "content-length", "accept-encoding", "priority", "connection"}
    cleaned_user_headers: Dict[str, str] = {}
    for k, v in user_headers.items():
        kl = k.lower().strip()
        if not kl or kl.startswith(":") or kl.startswith("sec-") or kl in ignore_headers:
            continue
        cleaned_user_headers[kl] = str(v).strip()

    final_headers: Dict[str, str] = dict(cleaned_user_headers)
    for k, v in dict(initialize_headers()).items():
        final_headers[k.lower()] = str(v)

    final_headers["cookie"] = cookie_str
    final_headers["x-goog-authuser"] = cleaned_user_headers.get("x-goog-authuser", "0")
    final_headers["origin"] = "https://music.youtube.com"
    final_headers["x-origin"] = "https://music.youtube.com"
    final_headers["authorization"] = get_authorization(f"{sapisid} https://music.youtube.com")
    return final_headers


class YTMProvider(PlatformProvider):
    platform_id = "ytm"
    platform_name = "YouTube Music"

    def get_client(self, require_auth: bool = True) -> YTMusic:
        if YTM_AUTH_FILE.exists():
            try:
                return YTMusic(str(YTM_AUTH_FILE))
            except Exception as e:
                if require_auth:
                    raise ValueError(f"YouTube Music 认证加载失败: {str(e)}")
        if require_auth:
            raise ValueError("尚未配置 YouTube Music 认证信息，请先完成 YouTube Music 连接。")
        return YTMusic()

    def save_auth(self, raw_headers: str) -> Dict[str, Any]:
        final_headers = build_ytm_headers_from_any_input(raw_headers)
        write_json_file(YTM_AUTH_FILE, final_headers)
        ytm = YTMusic(str(YTM_AUTH_FILE))
        playlists = ytm.get_library_playlists(limit=10)
        return {
            "success": True,
            "connected": True,
            "message": "YouTube Music 连接成功！",
            "playlists_count": len(playlists) if playlists else 0,
        }

    def get_status(self) -> Dict[str, Any]:
        if not YTM_AUTH_FILE.exists():
            return {"platform": "ytm", "connected": False, "message": "未连接"}
        try:
            ytm = YTMusic(str(YTM_AUTH_FILE))
            playlists = ytm.get_library_playlists(limit=10)
            return {
                "platform": "ytm",
                "connected": True,
                "message": "已连接 YouTube Music",
                "playlists_count": len(playlists) if playlists else 0,
            }
        except Exception as e:
            return {
                "platform": "ytm",
                "connected": False,
                "message": f"认证无效或已过期: {str(e)}",
            }

    def disconnect(self) -> Dict[str, Any]:
        if YTM_AUTH_FILE.exists():
            YTM_AUTH_FILE.unlink()
        return {"success": True, "message": "已断开 YouTube Music 连接并清除本地凭据"}

    def get_user_playlists(self, include_liked: bool = False) -> List[Dict[str, Any]]:
        ytm = self.get_client(require_auth=True)
        playlists = ytm.get_library_playlists(limit=150) or []
        cleaned: List[Dict[str, Any]] = []
        if include_liked:
            cleaned.append(
                {
                    "id": "LM",
                    "playlistId": "LM",
                    "title": "❤️ 我喜欢的音乐 (Liked Music)",
                    "name": "❤️ 我喜欢的音乐 (Liked Music)",
                    "count": "自动同步",
                    "is_liked": True,
                    "editable": False,
                }
            )
        for p in playlists:
            pid = p.get("playlistId", "")
            if pid and pid not in ("LM", "SE"):
                title = p.get("title", "Untitled")
                cnt = p.get("count", "")
                cleaned.append(
                    {
                        "id": pid,
                        "playlistId": pid,
                        "title": title,
                        "name": title,
                        "count": cnt,
                        "tracks_total": cnt,
                        "is_liked": False,
                        "editable": True,
                    }
                )
        return cleaned

    def _raw_track_to_item(self, t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not t:
            return None
        title = (t.get("title") or "").strip()
        if not title:
            return None
        vid = t.get("videoId") or ""
        artists = ", ".join([a.get("name", "") for a in (t.get("artists") or []) if a.get("name")])
        album = (t.get("album") or {}).get("name", "") if isinstance(t.get("album"), dict) else ""
        dur_sec = int(t.get("duration_seconds") or parse_duration_seconds(t.get("duration")) or 0)
        return {
            "title": title,
            "artist": artists,
            "album": album,
            "duration_ms": dur_sec * 1000,
            "isrc": "",
            "spotify_uri": "",
            "source_platform": "ytm",
            "source_id": vid,
            "extra": {
                "videoId": vid,
                "url": f"https://music.youtube.com/watch?v={vid}" if vid else "",
            },
        }

    def get_playlist_tracks(self, playlist_id: str) -> Dict[str, Any]:
        clean_id = playlist_id.strip()
        if clean_id in ("LM", "liked_songs"):
            ytm = self.get_client(require_auth=True)
            pl = ytm.get_liked_songs(limit=None)
            pl_name = "YouTube Music Liked Songs"
        else:
            if clean_id.startswith("VL"):
                clean_id = clean_id[2:]
            ytm = self.get_client(require_auth=False)
            pl = ytm.get_playlist(clean_id, limit=None)
            pl_name = pl.get("title") or "YouTube Music Playlist"

        tracks: List[Dict[str, Any]] = []
        for raw_t in pl.get("tracks") or []:
            parsed = self._raw_track_to_item(raw_t)
            if parsed:
                tracks.append(parsed)
        return {
            "playlist_name": pl_name,
            "count": len(tracks),
            "tracks": tracks,
        }

    def import_from_url(self, url_or_id: str) -> Dict[str, Any]:
        s = url_or_id.strip()
        m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", s)
        pid = m.group(1) if m else s
        if not pid:
            raise ValueError("无法识别的 YouTube Music 歌单链接或 ID。")
        return self.get_playlist_tracks(pid)

    def search_candidates(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        ytm = self.get_client(require_auth=False)
        raw_items: List[Dict[str, Any]] = []
        try:
            songs = ytm.search(query, filter="songs", limit=limit) or []
            raw_items.extend(songs)
        except Exception:
            pass

        if len(raw_items) < 2:
            try:
                videos = ytm.search(query, filter="videos", limit=max(3, limit // 2)) or []
                raw_items.extend(videos)
            except Exception:
                pass

        candidates: List[Dict[str, Any]] = []
        seen = set()
        for item in raw_items:
            vid = item.get("videoId")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            cand_artists = ", ".join([a.get("name", "") for a in (item.get("artists") or []) if a.get("name")])
            album = (item.get("album") or {}).get("name", "") if isinstance(item.get("album"), dict) else ""
            dur_str = item.get("duration") or ""
            dur_sec = int(item.get("duration_seconds") or parse_duration_seconds(dur_str) or 0)
            if not dur_str and dur_sec > 0:
                dur_str = format_duration_seconds(dur_sec)
            candidates.append(
                {
                    "platform": "ytm",
                    "track_id": vid,
                    "videoId": vid,
                    "title": item.get("title", ""),
                    "artist": cand_artists,
                    "album": album,
                    "duration": dur_str,
                    "duration_seconds": dur_sec,
                    "resultType": item.get("resultType", "song"),
                    "url": f"https://music.youtube.com/watch?v={vid}",
                }
            )
        return candidates[:limit]

    def create_playlist(
        self,
        title: str,
        description: str = "",
        privacy_status: str = "PRIVATE",
    ) -> str:
        ytm = self.get_client(require_auth=True)
        res = ytm.create_playlist(
            title=title or "Imported Playlist",
            description=description or "Imported via Switch Music",
            privacy_status=privacy_status if privacy_status in ("PRIVATE", "PUBLIC", "UNLISTED") else "PRIVATE",
        )
        if isinstance(res, str):
            return res
        if isinstance(res, dict) and "playlistId" in res:
            return str(res["playlistId"])
        raise RuntimeError(f"创建 YouTube Music 歌单返回异常: {res}")

    def get_existing_track_ids(
        self,
        playlist_id: Optional[str],
        target_mode: str = "existing_playlist",
    ) -> Set[str]:
        ytm = self.get_client(require_auth=True)
        ids: Set[str] = set()
        try:
            if target_mode == "liked_songs":
                liked = ytm.get_liked_songs(limit=2000)
                for t in (liked or {}).get("tracks") or []:
                    if t and t.get("videoId"):
                        ids.add(t["videoId"])
            elif playlist_id:
                clean_pid = playlist_id[2:] if playlist_id.startswith("VL") else playlist_id
                pl = ytm.get_playlist(clean_pid, limit=None)
                for t in (pl or {}).get("tracks") or []:
                    if t and t.get("videoId"):
                        ids.add(t["videoId"])
        except Exception:
            pass
        return ids

    def add_tracks(
        self,
        playlist_id: Optional[str],
        target_mode: str,
        candidates: List[Dict[str, Any]],
        seen_ids: Set[str],
        skip_duplicates: bool = True,
    ) -> int:
        ytm = self.get_client(require_auth=True)
        vids: List[str] = []
        for c in candidates:
            vid = str(c.get("track_id") or c.get("videoId") or "").strip()
            if not vid:
                continue
            if skip_duplicates:
                if vid in seen_ids:
                    continue
                seen_ids.add(vid)
            vids.append(vid)

        if not vids:
            return 0

        if target_mode == "liked_songs":
            added = 0
            for vid in vids:
                try:
                    ytm.rate_song(vid, "LIKE")
                    added += 1
                except Exception:
                    pass
                time.sleep(0.08)
            return added

        if not playlist_id:
            raise ValueError("未指定目标 YouTube Music 歌单 ID。")

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
                for vid in vids
            ],
        }
        try:
            res = ytm._send_request("browse/edit_playlist", body)
            if isinstance(res, dict) and "SUCCEEDED" in str(res.get("status", "")):
                return len(vids)
        except Exception:
            pass

        added = 0
        for single_vid in vids:
            try:
                ytm.add_playlist_items(clean_pid, [single_vid], duplicates=not skip_duplicates)
                added += 1
            except Exception:
                pass
        return added

    def get_dedupe_raw_items(self, playlist_id: str) -> Tuple[str, List[Dict[str, Any]]]:
        ytm = self.get_client(require_auth=True)
        clean_pid = playlist_id[2:] if playlist_id.startswith("VL") else playlist_id
        pl = ytm.get_playlist(clean_pid, limit=None)
        raw_tracks = pl.get("tracks") or []
        items: List[Dict[str, Any]] = []
        for idx, t in enumerate(raw_tracks):
            if not t:
                continue
            vid = t.get("videoId") or ""
            set_vid = t.get("setVideoId") or ""
            artists_list = [a.get("name", "") for a in (t.get("artists") or []) if a.get("name")]
            dur_str = t.get("duration") or ""
            dur_sec = int(t.get("duration_seconds") or parse_duration_seconds(dur_str) or 0)
            items.append(
                {
                    "position": idx + 1,
                    "item_id": vid,
                    "videoId": vid,
                    "setVideoId": set_vid,
                    "can_remove": bool(vid and set_vid),
                    "title": t.get("title") or "Unknown",
                    "artist": ", ".join(artists_list),
                    "primary_artist": artists_list[0] if artists_list else "",
                    "album": (t.get("album") or {}).get("name", "") if isinstance(t.get("album"), dict) else "",
                    "duration": dur_str,
                    "duration_seconds": dur_sec,
                    "url": f"https://music.youtube.com/watch?v={vid}" if vid else "",
                    "extra": {},
                }
            )
        return pl.get("title") or "YouTube Music Playlist", items

    def remove_playlist_duplicates(self, playlist_id: str, items: List[Dict[str, Any]]) -> int:
        ytm = self.get_client(require_auth=True)
        clean_pid = playlist_id[2:] if playlist_id.startswith("VL") else playlist_id
        valid_items = [
            {
                "videoId": str(it.get("videoId") or it.get("item_id") or ""),
                "setVideoId": str(it.get("setVideoId") or ""),
            }
            for it in items
            if (it.get("videoId") or it.get("item_id")) and it.get("setVideoId")
        ]
        if not valid_items:
            raise ValueError("没有可移除的有效歌曲项（请确认你是该歌单的创建者）。")

        removed = 0
        for i in range(0, len(valid_items), 50):
            batch = valid_items[i : i + 50]
            res = ytm.remove_playlist_items(clean_pid, batch)
            if isinstance(res, str) and "SUCCEEDED" in res:
                removed += len(batch)
            elif isinstance(res, dict) and "SUCCEEDED" in str(res.get("status", "")):
                removed += len(batch)
            else:
                for single in batch:
                    try:
                        r1 = ytm.remove_playlist_items(clean_pid, [single])
                        if "SUCCEEDED" in str(r1):
                            removed += 1
                    except Exception:
                        pass
            time.sleep(0.15)
        return removed

    def build_playlist_url(self, playlist_id: Optional[str], target_mode: str = "new_playlist") -> str:
        if target_mode == "liked_songs" or playlist_id == "LM":
            return "https://music.youtube.com/playlist?list=LM"
        if playlist_id:
            return f"https://music.youtube.com/playlist?list={playlist_id}"
        return "https://music.youtube.com/library/playlists"
