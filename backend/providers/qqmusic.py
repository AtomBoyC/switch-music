from __future__ import annotations

import json
import random
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

from backend.config import (
    QQMUSIC_AUTH_FILE,
    make_retry_session,
    parse_cookie_and_headers,
    read_json_file,
    write_json_file,
)
from backend.providers.base import PlatformProvider
from backend.text_utils import format_duration_seconds


def calc_qq_gtk(skey: str) -> int:
    h = 5381
    for ch in skey or "":
        h += (h << 5) + ord(ch)
    return h & 0x7FFFFFFF


def extract_qq_uin_and_key(cookie_dict: Dict[str, str]) -> Tuple[str, str, int]:
    raw_uin = (
        cookie_dict.get("uin")
        or cookie_dict.get("wxuin")
        or cookie_dict.get("qqmusic_uin")
        or cookie_dict.get("p_uin")
        or cookie_dict.get("o_cookie")
        or ""
    ).strip()
    clean_uin = re.sub(r"^[oO]0*", "", raw_uin).strip()
    if not clean_uin.isdigit():
        digits = re.findall(r"\d+", raw_uin)
        clean_uin = digits[0] if digits else ""

    musickey = (
        cookie_dict.get("qm_keyst")
        or cookie_dict.get("qqmusic_key")
        or cookie_dict.get("p_skey")
        or cookie_dict.get("skey")
        or ""
    ).strip()

    login_type = 1 if (musickey.startswith("W_X") or "wxuin" in cookie_dict) else 2
    return clean_uin, musickey, login_type


class QQMusicProvider(PlatformProvider):
    platform_id = "qqmusic"
    platform_name = "QQ音乐"

    MUSICU_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
    BASE_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://y.qq.com/",
        "Origin": "https://y.qq.com",
    }

    def _load_auth(self) -> Dict[str, Any]:
        data = read_json_file(QQMUSIC_AUTH_FILE, {})
        return data if isinstance(data, dict) else {}

    def _build_session(self, require_auth: bool = False) -> Tuple[requests.Session, Dict[str, Any]]:
        auth = self._load_auth()
        cookies_dict: Dict[str, str] = dict(auth.get("cookies") or {})
        uin = str(auth.get("uin") or "")
        musickey = str(auth.get("musickey") or "")
        if require_auth and (not uin or not musickey):
            raise ValueError("尚未连接 QQ 音乐账号（需包含 uin 与 qm_keyst / qqmusic_key 的 Cookie），请先在连接面板配置。")

        sess = make_retry_session()
        sess.headers.update(self.BASE_HEADERS)
        if cookies_dict:
            sess.headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies_dict.items() if k and v is not None)
        return sess, auth

    def _build_comm(self, auth: Dict[str, Any]) -> Dict[str, Any]:
        uin = str(auth.get("uin") or "0")
        musickey = str(auth.get("musickey") or "")
        login_type = int(auth.get("login_type") or 2)
        gtk = calc_qq_gtk(musickey)
        comm: Dict[str, Any] = {
            "ct": 24,
            "cv": 0,
            "format": "json",
            "uin": int(uin) if uin.isdigit() and len(uin) < 18 else uin,
            "g_tk": gtk,
            "g_tk_new_20200303": gtk,
        }
        if musickey:
            comm["authst"] = musickey
            comm["qqmusic_key"] = musickey
            comm["qm_keyst"] = musickey
            comm["tmeLoginType"] = str(login_type)
            comm["tmeAppID"] = "qqmusic"
        return comm

    def _post_musicu(
        self,
        req_map: Dict[str, Dict[str, Any]],
        require_auth: bool = False,
        session: Optional[requests.Session] = None,
    ) -> Dict[str, Any]:
        auth = self._load_auth()
        sess = session
        if sess is None:
            sess, auth = self._build_session(require_auth=require_auth)
        gtk = calc_qq_gtk(str(auth.get("musickey") or ""))
        payload = {"comm": self._build_comm(auth), **req_map}
        resp = sess.post(
            f"{self.MUSICU_URL}?g_tk={gtk}&format=json&inCharset=utf8&outCharset=utf-8",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json;charset=utf-8"},
            timeout=12,
        )
        resp.raise_for_status()
        return resp.json()

    def _fetch_profile_homepage(self, sess: requests.Session, uin: str, musickey: str) -> Dict[str, Any]:
        gtk = calc_qq_gtk(musickey)
        params = {
            "cid": "205360838",
            "ct": "20",
            "cv": "0",
            "userid": uin,
            "reqfrom": "1",
            "reqtype": "0",
            "hostUin": uin,
            "loginUin": uin,
            "format": "json",
            "inCharset": "utf8",
            "outCharset": "utf-8",
            "g_tk": str(gtk),
        }
        resp = sess.get(
            "https://c6.y.qq.com/rsc/fcgi-bin/fcg_get_profile_homepage.fcg",
            params=params,
            timeout=10,
        )
        text = resp.text.strip()
        if text.startswith("MusicJsonCallback(") and text.endswith(")"):
            text = text[len("MusicJsonCallback(") : -1]
        return json.loads(text)

    def save_auth(self, raw_input: str) -> Dict[str, Any]:
        _, cookie_dict, _ = parse_cookie_and_headers(raw_input)
        uin, musickey, login_type = extract_qq_uin_and_key(cookie_dict)
        if not uin or not musickey:
            raise ValueError(
                "未能从 Cookie 中提取到 QQ 音乐登录态 (uin/wxuin 与 qm_keyst/qqmusic_key)，请确认已在 y.qq.com 登录账号。"
            )

        sess = requests.Session()
        sess.headers.update(self.BASE_HEADERS)
        sess.headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())

        nickname = f"QQ音乐用户 ({uin})"
        verified = False
        try:
            prof = self._fetch_profile_homepage(sess, uin, musickey)
            creator = ((prof.get("data") or {}).get("creator")) or {}
            if creator.get("nick"):
                nickname = creator["nick"]
                verified = True
            elif (prof.get("data") or {}).get("mymusic") is not None:
                verified = True
        except Exception:
            pass

        if not verified:
            # Secondary check via PlaylistBaseRead
            gtk = calc_qq_gtk(musickey)
            payload = {
                "comm": {
                    "ct": 24,
                    "cv": 0,
                    "uin": uin,
                    "authst": musickey,
                    "tmeLoginType": str(login_type),
                    "g_tk": gtk,
                },
                "req_0": {
                    "module": "music.musicasset.PlaylistBaseRead",
                    "method": "GetPlaylistByUin",
                    "param": {"uin": uin},
                },
            }
            r = sess.post(
                f"{self.MUSICU_URL}?g_tk={gtk}",
                data=json.dumps(payload).encode("utf-8"),
                timeout=10,
            ).json()
            r0 = r.get("req_0") or {}
            if r0.get("code") == 0:
                verified = True

        if not verified:
            raise ValueError("QQ 音乐 Cookie 验证失败或已过期，请在 y.qq.com 刷新页面后重新复制 Copy as cURL。")

        saved = {
            "uin": uin,
            "musickey": musickey,
            "login_type": login_type,
            "nickname": nickname,
            "cookies": cookie_dict,
            "updated_at": int(time.time()),
        }
        write_json_file(QQMUSIC_AUTH_FILE, saved)
        return {
            "success": True,
            "connected": True,
            "user_id": uin,
            "user_name": nickname,
            "message": f"QQ 音乐连接成功 ({nickname})！",
        }

    def get_status(self) -> Dict[str, Any]:
        auth = self._load_auth()
        uin = str(auth.get("uin") or "")
        musickey = str(auth.get("musickey") or "")
        if not uin or not musickey:
            return {
                "platform": "qqmusic",
                "connected": False,
                "message": "未登录（支持免登录链接导入公开歌单）",
            }
        nickname = auth.get("nickname") or uin
        try:
            sess, _ = self._build_session(require_auth=True)
            prof = self._fetch_profile_homepage(sess, uin, musickey)
            if prof.get("code") in (0, None) and prof.get("data"):
                nick = ((prof.get("data") or {}).get("creator") or {}).get("nick")
                if nick:
                    nickname = nick
                return {
                    "platform": "qqmusic",
                    "connected": True,
                    "user_id": uin,
                    "user_name": nickname,
                    "message": f"已登录 ({nickname})",
                }
        except Exception:
            pass

        # Fallback check via PlaylistBaseRead
        try:
            res = self._post_musicu(
                {
                    "req_0": {
                        "module": "music.musicasset.PlaylistBaseRead",
                        "method": "GetPlaylistByUin",
                        "param": {"uin": uin},
                    }
                },
                require_auth=True,
            )
            if (res.get("req_0") or {}).get("code") == 0:
                return {
                    "platform": "qqmusic",
                    "connected": True,
                    "user_id": uin,
                    "user_name": nickname,
                    "message": f"已登录 ({nickname})",
                }
        except Exception:
            pass

        return {"platform": "qqmusic", "connected": False, "message": "QQ 音乐登录态已过期，请更新 Cookie"}

    def disconnect(self) -> Dict[str, Any]:
        if QQMUSIC_AUTH_FILE.exists():
            QQMUSIC_AUTH_FILE.unlink()
        return {"success": True, "message": "已断开 QQ 音乐连接"}

    def get_user_playlists(self) -> List[Dict[str, Any]]:
        sess, auth = self._build_session(require_auth=True)
        uin = str(auth.get("uin") or "")
        musickey = str(auth.get("musickey") or "")
        items: List[Dict[str, Any]] = []
        seen_keys: Set[str] = set()

        # 1. Try PlaylistBaseRead (gives both dirId AND tid!)
        try:
            res = self._post_musicu(
                {
                    "req_0": {
                        "module": "music.musicasset.PlaylistBaseRead",
                        "method": "GetPlaylistByUin",
                        "param": {"uin": uin},
                    }
                },
                require_auth=True,
                session=sess,
            )
            v_list = (((res.get("req_0") or {}).get("data")) or {}).get("v_playlist") or []
            for p in v_list:
                if not isinstance(p, dict):
                    continue
                dir_id = p.get("dirId")
                tid = p.get("tid")
                if not dir_id and not tid:
                    continue
                is_liked = int(dir_id or 0) == 201
                raw_name = p.get("dirName") or "未命名歌单"
                display_name = "❤️ 我喜欢" if is_liked else raw_name
                cnt = p.get("songNum", 0)
                compound_id = f"dir_{dir_id}|tid_{tid}" if (dir_id and tid) else str(tid or f"dir_{dir_id}")
                seen_keys.add(str(tid))
                seen_keys.add(str(dir_id))
                items.append(
                    {
                        "id": compound_id,
                        "playlistId": compound_id,
                        "dirId": dir_id,
                        "tid": tid,
                        "name": display_name,
                        "title": display_name,
                        "tracks_total": cnt,
                        "count": cnt,
                        "is_liked": is_liked,
                        "editable": True,
                    }
                )
        except Exception:
            pass

        # 2. Supplement from profile homepage if empty or missing tid
        if not items:
            prof = self._fetch_profile_homepage(sess, uin, musickey)
            data = prof.get("data") or {}
            for m in data.get("mymusic") or []:
                tid = m.get("id")
                if tid and str(tid) not in seen_keys:
                    cnt = m.get("num0", 0)
                    cid = f"dir_201|tid_{tid}"
                    items.append(
                        {
                            "id": cid,
                            "playlistId": cid,
                            "dirId": 201,
                            "tid": tid,
                            "name": "❤️ 我喜欢",
                            "title": "❤️ 我喜欢",
                            "tracks_total": cnt,
                            "count": cnt,
                            "is_liked": True,
                            "editable": True,
                        }
                    )
            for d in ((data.get("mydiss") or {}).get("list")) or []:
                tid = d.get("dissid")
                dir_id = d.get("dirid") or 0
                if not tid or str(tid) in seen_keys:
                    continue
                title = d.get("title") or "未命名歌单"
                subtitle = str(d.get("subtitle") or "")
                cnt_m = re.search(r"(\d+)\s*首", subtitle)
                cnt = int(cnt_m.group(1)) if cnt_m else ""
                cid = f"dir_{dir_id}|tid_{tid}" if dir_id else str(tid)
                items.append(
                    {
                        "id": cid,
                        "playlistId": cid,
                        "dirId": dir_id,
                        "tid": tid,
                        "name": title,
                        "title": title,
                        "tracks_total": cnt,
                        "count": cnt,
                        "is_liked": False,
                        "editable": True,
                    }
                )

        # Ensure "liked_songs" entry exists at top
        if not any(it.get("is_liked") for it in items):
            items.insert(
                0,
                {
                    "id": "liked_songs",
                    "playlistId": "liked_songs",
                    "dirId": 201,
                    "name": "❤️ 我喜欢 (QQ音乐)",
                    "title": "❤️ 我喜欢 (QQ音乐)",
                    "tracks_total": "",
                    "count": "",
                    "is_liked": True,
                    "editable": True,
                },
            )
        return items

    @staticmethod
    def _parse_compound_id(raw_id: str) -> Tuple[Optional[int], Optional[str]]:
        """Extract (dirId, tid/disstid) from compound ID like 'dir_12|tid_801491460' or plain tid."""
        s = (raw_id or "").strip()
        if s == "liked_songs":
            return 201, None
        m = re.match(r"^dir_(\d+)\|tid_(\d+)$", s)
        if m:
            d = int(m.group(1))
            t = m.group(2)
            return (d if d > 0 else None), (t if t != "0" else None)
        if s.startswith("dir_") and s[4:].isdigit():
            return int(s[4:]), None
        if s.isdigit():
            return None, s
        return None, None

    def _resolve_dir_id(self, playlist_id: Optional[str], target_mode: str) -> int:
        if target_mode == "liked_songs" or playlist_id == "liked_songs":
            return 201
        if not playlist_id:
            raise ValueError("未指定目标 QQ 音乐歌单。")
        dir_id, tid = self._parse_compound_id(playlist_id)
        if dir_id:
            return dir_id
        # Look up dirId from user's playlists via tid
        for p in self.get_user_playlists():
            if str(p.get("tid")) == str(tid) and p.get("dirId"):
                return int(p["dirId"])
        if str(playlist_id).isdigit() and int(playlist_id) < 100000:
            return int(playlist_id)
        raise ValueError("无法定位该 QQ 音乐歌单的目录 ID (dirId)，请确认这是你本人创建的歌单并刷新歌单列表。")

    @staticmethod
    def _extract_disstid(url_or_id: str) -> str:
        s = url_or_id.strip()
        if s.isdigit():
            return s
        if s.startswith("dir_"):
            _, tid = QQMusicProvider._parse_compound_id(s)
            if tid:
                return tid

        url_match = re.search(r"https?://[^\s\"'<>]+", s)
        if url_match:
            target_url = url_match.group(0)
            if "fcgi-bin/u" in target_url or "url.cn" in target_url:
                try:
                    r = requests.get(
                        target_url,
                        headers=QQMusicProvider.BASE_HEADERS,
                        allow_redirects=True,
                        timeout=8,
                    )
                    target_url = r.url
                except Exception:
                    pass
            s = target_url

        for pat in (r"/playlist/(\d+)", r"[?&](?:id|disstid|tid)=(\d+)"):
            m = re.search(pat, s)
            if m:
                return m.group(1)
        raise ValueError("无法识别 QQ 音乐歌单链接或 ID（示例：https://y.qq.com/n/ryqq/playlist/8014914608）。")

    @staticmethod
    def _song_obj_to_track(song: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not song:
            return None
        title = (song.get("name") or song.get("songname") or song.get("title") or "").strip()
        if not title:
            return None
        singers = song.get("singer") or []
        artists = ", ".join([s.get("name", "") for s in singers if isinstance(s, dict) and s.get("name")])
        album_obj = song.get("album")
        if isinstance(album_obj, dict):
            album = album_obj.get("name") or album_obj.get("title") or ""
        else:
            album = str(song.get("albumname") or "")

        interval_sec = int(song.get("interval") or 0)
        song_id = song.get("id") or song.get("songid") or 0
        song_mid = song.get("mid") or song.get("songmid") or ""
        song_type = int(song.get("type") if song.get("type") is not None else (song.get("songtype") or 0))
        compound_track_id = f"{song_id}:{song_mid}:{song_type}"

        return {
            "title": title,
            "artist": artists,
            "album": album,
            "duration_ms": interval_sec * 1000,
            "isrc": "",
            "spotify_uri": "",
            "source_platform": "qqmusic",
            "source_id": compound_track_id,
            "extra": {
                "songId": int(song_id) if str(song_id).isdigit() else 0,
                "songMid": song_mid,
                "songType": song_type,
                "url": f"https://y.qq.com/n/ryqq/songDetail/{song_mid}" if song_mid else "",
            },
        }

    def get_playlist_tracks(self, playlist_id: str) -> Dict[str, Any]:
        dir_id, tid = self._parse_compound_id(playlist_id)
        if not tid and dir_id == 201:
            # Resolve "我喜欢" tid from user playlists
            for p in self.get_user_playlists():
                if p.get("is_liked") and p.get("tid"):
                    tid = str(p["tid"])
                    break
        if not tid:
            tid = self._extract_disstid(playlist_id)

        sess, _ = self._build_session(require_auth=False)
        tracks: List[Dict[str, Any]] = []
        playlist_name = "QQ音乐歌单"

        # Channel 1: musicu.fcg srfDissInfo with pagination for large playlists
        try:
            begin = 0
            page_size = 500
            while True:
                res = self._post_musicu(
                    {
                        "req_0": {
                            "module": "music.srfDissInfo.aiDissInfo",
                            "method": "uniform_get_Dissinfo",
                            "param": {
                                "disstid": int(tid),
                                "song_begin": begin,
                                "song_num": page_size,
                                "tag": 1,
                                "userinfo": 1,
                                "orderlist": 1,
                            },
                        }
                    },
                    require_auth=False,
                    session=sess,
                )
                r0 = res.get("req_0") or {}
                data = r0.get("data") or {}
                dirinfo = data.get("dirinfo") or {}
                if dirinfo.get("title") or data.get("dissname"):
                    playlist_name = dirinfo.get("title") or data.get("dissname") or playlist_name
                batch = data.get("songlist") or []
                for s in batch:
                    parsed = self._song_obj_to_track(s)
                    if parsed:
                        tracks.append(parsed)
                total_num = int(dirinfo.get("songnum") or data.get("total_song_num") or len(batch))
                begin += len(batch)
                if not batch or len(batch) < page_size or begin >= total_num:
                    break
        except Exception:
            pass

        # Channel 2 fallback: fcg_ucc_getcdinfo_byids_cp.fcg
        if not tracks:
            params = {
                "type": 1,
                "json": 1,
                "utf8": 1,
                "onlysong": 0,
                "new_format": 1,
                "disstid": str(tid),
                "format": "json",
                "inCharset": "utf8",
                "outCharset": "utf-8",
                "platform": "yqq.json",
                "needNewCode": 0,
            }
            resp = sess.get(
                "https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg",
                params=params,
                headers={"Referer": f"https://y.qq.com/n/ryqq/playlist/{tid}"},
                timeout=12,
            )
            data = resp.json()
            cdlist = data.get("cdlist") or []
            if cdlist:
                playlist_name = cdlist[0].get("dissname") or playlist_name
                for s in cdlist[0].get("songlist") or []:
                    parsed = self._song_obj_to_track(s)
                    if parsed:
                        tracks.append(parsed)

        if not tracks:
            raise ValueError("未能从该 QQ 音乐歌单读取到曲目（若为私密歌单，请先粘贴 QQ 音乐 Cookie 登录）。")

        return {
            "playlist_name": playlist_name,
            "count": len(tracks),
            "tracks": tracks,
        }

    def import_from_url(self, url_or_id: str) -> Dict[str, Any]:
        tid = self._extract_disstid(url_or_id)
        return self.get_playlist_tracks(tid)

    def search_candidates(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        sess, _ = self._build_session(require_auth=False)
        raw_songs: List[Dict[str, Any]] = []
        search_id = str(random.randint(10000000000000000, 89999999999999999))

        for method_name in ("DoSearchForQQMusicDesktop", "DoSearchForQQMusicLite"):
            try:
                res = self._post_musicu(
                    {
                        "req_1": {
                            "module": "music.search.SearchCgiService",
                            "method": method_name,
                            "param": {
                                "query": query,
                                "search_type": 0,
                                "page_num": 1,
                                "num_per_page": limit,
                                "remoteplace": "txt.yqq.song",
                                "searchid": search_id,
                            },
                        }
                    },
                    require_auth=False,
                    session=sess,
                )
                body = (((res.get("req_1") or {}).get("data")) or {}).get("body") or {}
                song_block = body.get("song") or {}
                raw_songs = body.get("item_list") or song_block.get("list") or []
                if raw_songs:
                    break
            except Exception:
                continue

        # Fallback: client_search_cp
        if not raw_songs:
            try:
                r = sess.get(
                    "https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
                    params={"w": query, "p": 1, "n": limit, "format": "json", "new_json": 1},
                    timeout=10,
                ).json()
                raw_songs = (((r.get("data") or {}).get("song")) or {}).get("list") or []
            except Exception:
                pass

        candidates: List[Dict[str, Any]] = []
        for s in raw_songs[:limit]:
            song_id = s.get("id") or s.get("songid") or 0
            song_mid = s.get("mid") or s.get("songmid") or ""
            song_type = int(s.get("type") if s.get("type") is not None else (s.get("songtype") or 0))
            if not song_id and not song_mid:
                continue
            singers = s.get("singer") or []
            artists = ", ".join([a.get("name", "") for a in singers if isinstance(a, dict) and a.get("name")])
            album_obj = s.get("album")
            album = album_obj.get("name", "") if isinstance(album_obj, dict) else str(s.get("albumname") or "")
            interval_sec = int(s.get("interval") or 0)
            track_id = f"{song_id}:{song_mid}:{song_type}"
            candidates.append(
                {
                    "platform": "qqmusic",
                    "track_id": track_id,
                    "display_id": song_mid or str(song_id),
                    "title": s.get("name") or s.get("songname") or "",
                    "artist": artists,
                    "album": album,
                    "duration": format_duration_seconds(interval_sec),
                    "duration_seconds": interval_sec,
                    "resultType": "song",
                    "url": f"https://y.qq.com/n/ryqq/songDetail/{song_mid}" if song_mid else "",
                    "extra": {
                        "songId": int(song_id) if str(song_id).isdigit() else 0,
                        "songMid": song_mid,
                        "songType": song_type,
                    },
                }
            )
        return candidates

    def create_playlist(
        self,
        title: str,
        description: str = "",
        privacy_status: str = "PRIVATE",
    ) -> str:
        clean_title = (title or "Switch Music 歌单").strip()[:40]
        res = self._post_musicu(
            {
                "req_0": {
                    "module": "music.musicasset.PlaylistBaseWrite",
                    "method": "AddPlaylist",
                    "param": {"dirName": clean_title},
                }
            },
            require_auth=True,
        )
        r0 = res.get("req_0") or {}
        data = r0.get("data") or {}
        dir_id = data.get("dirId") or ((data.get("result") or {}).get("dirId"))
        tid = data.get("tid") or ((data.get("result") or {}).get("tid")) or 0
        if r0.get("code") == 0 and dir_id:
            return f"dir_{dir_id}|tid_{tid}"
        raise RuntimeError(f"创建 QQ 音乐歌单失败 (可能 Cookie 已过期或名称受限): {data or r0}")

    def get_existing_track_ids(
        self,
        playlist_id: Optional[str],
        target_mode: str = "existing_playlist",
    ) -> Set[str]:
        ids: Set[str] = set()
        try:
            pid = "liked_songs" if target_mode == "liked_songs" else (playlist_id or "")
            if not pid:
                return ids
            data = self.get_playlist_tracks(pid)
            for t in data.get("tracks") or []:
                ex = t.get("extra") or {}
                if ex.get("songId"):
                    ids.add(str(ex["songId"]))
        except Exception:
            pass
        return ids

    @staticmethod
    def _extract_song_id_and_type(cand: Dict[str, Any]) -> Tuple[int, int]:
        ex = cand.get("extra") or {}
        if ex.get("songId"):
            return int(ex["songId"]), int(ex.get("songType") or 0)
        tid = str(cand.get("track_id") or "")
        parts = tid.split(":")
        if parts and parts[0].isdigit():
            s_id = int(parts[0])
            s_type = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            return s_id, s_type
        return 0, 0

    def add_tracks(
        self,
        playlist_id: Optional[str],
        target_mode: str,
        candidates: List[Dict[str, Any]],
        seen_ids: Set[str],
        skip_duplicates: bool = True,
    ) -> int:
        sess, _ = self._build_session(require_auth=True)
        dir_id = self._resolve_dir_id(playlist_id, target_mode)

        song_infos: List[Dict[str, int]] = []
        for c in candidates:
            s_id, s_type = self._extract_song_id_and_type(c)
            if s_id <= 0:
                continue
            sid_key = str(s_id)
            if skip_duplicates:
                if sid_key in seen_ids:
                    continue
                seen_ids.add(sid_key)
            song_infos.append({"songId": s_id, "songType": s_type})

        if not song_infos:
            return 0

        added = 0
        for i in range(0, len(song_infos), 40):
            batch = song_infos[i : i + 40]
            res = self._post_musicu(
                {
                    "req_0": {
                        "module": "music.musicasset.PlaylistDetailWrite",
                        "method": "AddSonglist",
                        "param": {
                            "dirId": int(dir_id),
                            "tid": 0,
                            "bFmtUtf8": True,
                            "v_songInfo": batch,
                        },
                    }
                },
                require_auth=True,
                session=sess,
            )
            r0 = res.get("req_0") or {}
            data = r0.get("data") or {}
            if r0.get("code") == 0 and data.get("retCode", 0) == 0:
                added += len(batch)
            else:
                for single in batch:
                    try:
                        rs = self._post_musicu(
                            {
                                "req_0": {
                                    "module": "music.musicasset.PlaylistDetailWrite",
                                    "method": "AddSonglist",
                                    "param": {
                                        "dirId": int(dir_id),
                                        "tid": 0,
                                        "bFmtUtf8": True,
                                        "v_songInfo": [single],
                                    },
                                }
                            },
                            require_auth=True,
                            session=sess,
                        )
                        if (rs.get("req_0") or {}).get("code") == 0:
                            added += 1
                    except Exception:
                        pass
            time.sleep(0.15)
        return added

    def get_dedupe_raw_items(self, playlist_id: str) -> Tuple[str, List[Dict[str, Any]]]:
        data = self.get_playlist_tracks(playlist_id)
        items: List[Dict[str, Any]] = []
        for idx, t in enumerate(data.get("tracks") or []):
            ex = t.get("extra") or {}
            song_id = ex.get("songId") or 0
            song_mid = ex.get("songMid") or ""
            song_type = ex.get("songType") or 0
            dur_ms = int(t.get("duration_ms") or 0)
            artist_str = t.get("artist") or ""
            sid_str = str(song_id) if song_id else song_mid
            items.append(
                {
                    "position": idx + 1,
                    "item_id": sid_str,
                    "videoId": sid_str,
                    "setVideoId": f"{song_id}:{song_type}",
                    "can_remove": bool(song_id),
                    "title": t.get("title") or "Unknown",
                    "artist": artist_str,
                    "primary_artist": artist_str.split(",")[0].strip() if artist_str else "",
                    "album": t.get("album") or "",
                    "duration": format_duration_seconds(dur_ms // 1000),
                    "duration_seconds": dur_ms // 1000,
                    "url": f"https://y.qq.com/n/ryqq/songDetail/{song_mid}" if song_mid else "",
                    "extra": {"songId": song_id, "songType": song_type},
                }
            )
        return data.get("playlist_name") or "QQ音乐歌单", items

    def remove_playlist_duplicates(self, playlist_id: str, items: List[Dict[str, Any]]) -> int:
        sess, _ = self._build_session(require_auth=True)
        dir_id = self._resolve_dir_id(playlist_id, "existing_playlist")
        song_infos: List[Dict[str, int]] = []
        for it in items:
            ex = it.get("extra") or {}
            sid = ex.get("songId")
            stype = ex.get("songType", 0)
            if not sid and it.get("setVideoId") and ":" in str(it["setVideoId"]):
                p0, p1 = str(it["setVideoId"]).split(":", 1)
                if p0.isdigit():
                    sid = int(p0)
                    stype = int(p1) if p1.isdigit() else 0
            elif not sid and str(it.get("item_id") or "").isdigit():
                sid = int(it["item_id"])
            if sid:
                song_infos.append({"songId": int(sid), "songType": int(stype)})

        if not song_infos:
            raise ValueError("没有可移除的有效 QQ 音乐歌曲项。")

        removed = 0
        for i in range(0, len(song_infos), 40):
            batch = song_infos[i : i + 40]
            res = self._post_musicu(
                {
                    "req_0": {
                        "module": "music.musicasset.PlaylistDetailWrite",
                        "method": "DelSonglist",
                        "param": {
                            "dirId": int(dir_id),
                            "v_songInfo": batch,
                        },
                    }
                },
                require_auth=True,
                session=sess,
            )
            if (res.get("req_0") or {}).get("code") == 0:
                removed += len(batch)
            time.sleep(0.15)
        return removed

    def build_playlist_url(self, playlist_id: Optional[str], target_mode: str = "new_playlist") -> str:
        if playlist_id:
            _, tid = self._parse_compound_id(playlist_id)
            if tid and tid != "0":
                return f"https://y.qq.com/n/ryqq/playlist/{tid}"
        return "https://y.qq.com/n/ryqq/profile"
