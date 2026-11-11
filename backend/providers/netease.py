from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

from backend.config import (
    NETEASE_AUTH_FILE,
    make_retry_session,
    parse_cookie_and_headers,
    read_json_file,
    write_json_file,
)
from backend.providers.base import PlatformProvider
from backend.text_utils import format_duration_ms

# ---------------------------------------------------------------------------
# Pure-Python FIPS-197 AES-128-CBC + RSA Encryptor for NetEase `weapi`
# (Zero C/Rust compilation dependencies, <0.2ms per API call)
# ---------------------------------------------------------------------------

_SBOX = (
    0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
    0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
    0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
    0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
    0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
    0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
    0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
    0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
    0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
    0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
    0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
    0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
    0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
    0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
    0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
    0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16,
)
_RCON = (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)
_XTIME = tuple(((i << 1) ^ 0x1B) & 0xFF if (i & 0x80) else (i << 1) for i in range(256))


def _expand_key_128(key: bytes) -> List[List[int]]:
    w: List[List[int]] = [list(key[i : i + 4]) for i in range(0, 16, 4)]
    for i in range(4, 44):
        temp = list(w[i - 1])
        if i % 4 == 0:
            temp = [
                _SBOX[temp[1]] ^ _RCON[i // 4],
                _SBOX[temp[2]],
                _SBOX[temp[3]],
                _SBOX[temp[0]],
            ]
        w.append([w[i - 4][j] ^ temp[j] for j in range(4)])
    return [[w[r * 4 + c][row] for c in range(4) for row in range(4)] for r in range(11)]


def _aes128_encrypt_block(block: List[int], round_keys: List[List[int]]) -> List[int]:
    s = [block[i] ^ round_keys[0][i] for i in range(16)]
    for rnd in range(1, 10):
        # SubBytes + ShiftRows combined (column-major state)
        s = [
            _SBOX[s[0]], _SBOX[s[5]], _SBOX[s[10]], _SBOX[s[15]],
            _SBOX[s[4]], _SBOX[s[9]], _SBOX[s[14]], _SBOX[s[3]],
            _SBOX[s[8]], _SBOX[s[13]], _SBOX[s[2]], _SBOX[s[7]],
            _SBOX[s[12]], _SBOX[s[1]], _SBOX[s[6]], _SBOX[s[11]],
        ]
        # MixColumns + AddRoundKey
        rk = round_keys[rnd]
        for c in range(0, 16, 4):
            a0, a1, a2, a3 = s[c], s[c + 1], s[c + 2], s[c + 3]
            t = a0 ^ a1 ^ a2 ^ a3
            s[c] = a0 ^ t ^ _XTIME[a0 ^ a1] ^ rk[c]
            s[c + 1] = a1 ^ t ^ _XTIME[a1 ^ a2] ^ rk[c + 1]
            s[c + 2] = a2 ^ t ^ _XTIME[a2 ^ a3] ^ rk[c + 2]
            s[c + 3] = a3 ^ t ^ _XTIME[a3 ^ a0] ^ rk[c + 3]

    rk10 = round_keys[10]
    return [
        _SBOX[s[0]] ^ rk10[0], _SBOX[s[5]] ^ rk10[1], _SBOX[s[10]] ^ rk10[2], _SBOX[s[15]] ^ rk10[3],
        _SBOX[s[4]] ^ rk10[4], _SBOX[s[9]] ^ rk10[5], _SBOX[s[14]] ^ rk10[6], _SBOX[s[3]] ^ rk10[7],
        _SBOX[s[8]] ^ rk10[8], _SBOX[s[13]] ^ rk10[9], _SBOX[s[2]] ^ rk10[10], _SBOX[s[7]] ^ rk10[11],
        _SBOX[s[12]] ^ rk10[12], _SBOX[s[1]] ^ rk10[13], _SBOX[s[6]] ^ rk10[14], _SBOX[s[11]] ^ rk10[15],
    ]


def aes128_cbc_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    pad_len = 16 - (len(data) % 16)
    padded = data + bytes([pad_len] * pad_len)
    round_keys = _expand_key_128(key)
    prev = list(iv)
    out = bytearray()
    for i in range(0, len(padded), 16):
        xored = [padded[i + j] ^ prev[j] for j in range(16)]
        prev = _aes128_encrypt_block(xored, round_keys)
        out.extend(prev)
    return bytes(out)


_WEAPI_NONCE = b"0CoJUm6Qyw8W8jud"
_WEAPI_IV = b"0102030405060708"
_WEAPI_PUBKEY = 0x010001
_WEAPI_MODULUS = int(
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7"
    "b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280"
    "104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932"
    "575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b"
    "3ece0462db0a22b8e7",
    16,
)
_ALPHABET = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def weapi_encrypt(payload: Dict[str, Any]) -> Dict[str, str]:
    raw_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    rand_bytes = os.urandom(16)
    sec_key = bytes(_ALPHABET[b % 62] for b in rand_bytes)

    first_b64 = base64.b64encode(aes128_cbc_encrypt(raw_json, _WEAPI_NONCE, _WEAPI_IV))
    params_b64 = base64.b64encode(aes128_cbc_encrypt(first_b64, sec_key, _WEAPI_IV)).decode("ascii")

    rev_int = int.from_bytes(sec_key[::-1], "big")
    enc_sec_key = format(pow(rev_int, _WEAPI_PUBKEY, _WEAPI_MODULUS), "0256x")
    return {"params": params_b64, "encSecKey": enc_sec_key}


class NetEaseProvider(PlatformProvider):
    platform_id = "netease"
    platform_name = "网易云音乐"

    BASE_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://music.163.com/",
        "Origin": "https://music.163.com",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    def _load_auth(self) -> Dict[str, Any]:
        data = read_json_file(NETEASE_AUTH_FILE, {})
        return data if isinstance(data, dict) else {}

    def _build_session(self, require_auth: bool = False) -> Tuple[requests.Session, Dict[str, Any]]:
        auth = self._load_auth()
        cookies_dict: Dict[str, str] = dict(auth.get("cookies") or {})
        if require_auth and not cookies_dict.get("MUSIC_U"):
            raise ValueError("尚未连接网易云音乐账号（需要包含 MUSIC_U 的 Cookie），请先在连接面板配置。")

        # Desktop flags ensure full playlist access without mobile-web 10-track truncation
        cookies_dict.setdefault("os", "pc")
        cookies_dict.setdefault("appver", "2.9.7")

        sess = make_retry_session()
        sess.headers.update(self.BASE_HEADERS)
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookies_dict.items() if k and v is not None)
        if cookie_header:
            sess.headers["Cookie"] = cookie_header
        return sess, auth

    # NetEase signals throttling inside HTTP 200 JSON bodies (e.g. code 405 / -460 "操作频繁").
    THROTTLE_CODES = {405, -460, -462, 406}

    def _post_weapi(
        self,
        path: str,
        payload: Dict[str, Any],
        require_auth: bool = False,
        session: Optional[requests.Session] = None,
    ) -> Dict[str, Any]:
        sess = session
        auth = self._load_auth()
        if sess is None:
            sess, auth = self._build_session(require_auth=require_auth)
        csrf = ((auth.get("cookies") or {}).get("__csrf")) or ""
        body = dict(payload)
        body.setdefault("csrf_token", csrf)
        url = f"https://music.163.com{path}?csrf_token={csrf}"
        data: Dict[str, Any] = {}
        for attempt in range(3):
            encrypted = weapi_encrypt(body)
            resp = sess.post(url, data=encrypted, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("code") in self.THROTTLE_CODES and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        return data

    def save_auth(self, raw_input: str) -> Dict[str, Any]:
        _, cookie_dict, _ = parse_cookie_and_headers(raw_input)
        if "MUSIC_U" not in cookie_dict:
            raise ValueError("Cookie 中缺少网易云音乐登录凭据 (MUSIC_U)，请确认已在 music.163.com 登录账号。")

        sess = requests.Session()
        sess.headers.update(self.BASE_HEADERS)
        cookie_dict.setdefault("os", "pc")
        cookie_dict.setdefault("appver", "2.9.7")
        sess.headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())

        csrf = cookie_dict.get("__csrf", "")
        encrypted = weapi_encrypt({"csrf_token": csrf})
        resp = sess.post(f"https://music.163.com/weapi/nuser/account/get?csrf_token={csrf}", data=encrypted, timeout=12)
        data = resp.json()
        profile = data.get("profile") or {}
        account = data.get("account") or {}
        uid = profile.get("userId") or account.get("id")
        if not uid:
            raise ValueError("网易云 Cookie 无效或已过期，未能获取到登录用户信息。")

        nickname = profile.get("nickname") or str(uid)
        saved = {
            "user_id": str(uid),
            "nickname": nickname,
            "cookies": cookie_dict,
            "updated_at": int(time.time()),
        }
        write_json_file(NETEASE_AUTH_FILE, saved)
        return {
            "success": True,
            "connected": True,
            "user_id": str(uid),
            "user_name": nickname,
            "message": f"网易云音乐连接成功 ({nickname})！",
        }

    def get_status(self) -> Dict[str, Any]:
        auth = self._load_auth()
        cookies = auth.get("cookies") or {}
        if not cookies.get("MUSIC_U"):
            return {
                "platform": "netease",
                "connected": False,
                "message": "未登录（支持免登录链接导入公开歌单）",
            }
        try:
            res = self._post_weapi("/weapi/nuser/account/get", {}, require_auth=True)
            profile = res.get("profile") or {}
            account = res.get("account") or {}
            uid = profile.get("userId") or account.get("id")
            if not uid:
                return {"platform": "netease", "connected": False, "message": "网易云登录已过期"}
            nickname = profile.get("nickname") or auth.get("nickname") or str(uid)
            return {
                "platform": "netease",
                "connected": True,
                "user_id": str(uid),
                "user_name": nickname,
                "message": f"已登录 ({nickname})",
            }
        except Exception as e:
            return {"platform": "netease", "connected": False, "message": f"连接检查失败: {str(e)}"}

    def disconnect(self) -> Dict[str, Any]:
        if NETEASE_AUTH_FILE.exists():
            NETEASE_AUTH_FILE.unlink()
        return {"success": True, "message": "已断开网易云音乐账号连接"}

    def get_user_playlists(self) -> List[Dict[str, Any]]:
        sess, auth = self._build_session(require_auth=True)
        uid = str(auth.get("user_id") or "")
        if not uid:
            acct = self._post_weapi("/weapi/nuser/account/get", {}, require_auth=True, session=sess)
            uid = str(((acct.get("profile") or {}).get("userId")) or "")
        if not uid:
            raise ValueError("无法获取当前网易云音乐用户 UID。")

        res = self._post_weapi(
            "/weapi/user/playlist",
            {"uid": uid, "limit": 1000, "offset": 0, "includeVideo": True},
            require_auth=True,
            session=sess,
        )
        raw_list = res.get("playlist") or []
        items: List[Dict[str, Any]] = []
        for p in raw_list:
            if not p:
                continue
            pid = str(p.get("id") or "")
            is_liked = p.get("specialType") == 5
            creator_uid = str(((p.get("creator") or {}).get("userId")) or "")
            editable = creator_uid == uid
            raw_name = p.get("name") or "未命名歌单"
            display_name = "❤️ 我喜欢的音乐" if is_liked else raw_name
            cnt = p.get("trackCount", 0)
            items.append(
                {
                    "id": pid,
                    "playlistId": pid,
                    "name": display_name,
                    "title": display_name,
                    "tracks_total": cnt,
                    "count": cnt,
                    "owner": ((p.get("creator") or {}).get("nickname")) or "",
                    "is_liked": is_liked,
                    "editable": editable,
                }
            )
        return items

    def _get_liked_playlist_id(self) -> str:
        playlists = self.get_user_playlists()
        for p in playlists:
            if p.get("is_liked") and p.get("id"):
                return str(p["id"])
        if playlists:
            return str(playlists[0]["id"])
        raise ValueError("未找到网易云音乐「我喜欢的音乐」歌单。")

    @staticmethod
    def _extract_playlist_id(url_or_id: str) -> str:
        s = url_or_id.strip()
        if s.isdigit():
            return s
        # Extract URL from shared message if mixed with Chinese text
        url_match = re.search(r"https?://[^\s\"'<>]+", s)
        if url_match:
            target_url = url_match.group(0)
            # Resolve short link like 163cn.tv/xxxx
            if "163cn.tv" in target_url:
                try:
                    r = requests.head(target_url, allow_redirects=True, timeout=8)
                    target_url = r.url
                except Exception:
                    try:
                        r = requests.get(target_url, allow_redirects=True, timeout=8)
                        target_url = r.url
                    except Exception:
                        pass
            s = target_url

        m = re.search(r"(?:[?&]id=|/playlist/)(\d+)", s)
        if m:
            return m.group(1)
        raise ValueError("无法识别网易云音乐歌单链接或 ID（示例：https://music.163.com/#/playlist?id=123456）。")

    @staticmethod
    def _song_obj_to_track(song: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not song:
            return None
        title = (song.get("name") or "").strip()
        if not title:
            return None
        sid = str(song.get("id") or "")
        ar_list = song.get("ar") or song.get("artists") or []
        artists = ", ".join([a.get("name", "") for a in ar_list if isinstance(a, dict) and a.get("name")])
        al_obj = song.get("al") or song.get("album") or {}
        album = al_obj.get("name", "") if isinstance(al_obj, dict) else ""
        dur_ms = int(song.get("dt") or song.get("duration") or 0)
        return {
            "title": title,
            "artist": artists,
            "album": album,
            "duration_ms": dur_ms,
            "isrc": "",
            "spotify_uri": "",
            "source_platform": "netease",
            "source_id": sid,
            "extra": {
                "url": f"https://music.163.com/#/song?id={sid}" if sid else "",
            },
        }

    def get_playlist_tracks(self, playlist_id: str) -> Dict[str, Any]:
        pid = self._get_liked_playlist_id() if playlist_id == "liked_songs" else self._extract_playlist_id(playlist_id)
        sess, _ = self._build_session(require_auth=False)

        detail = self._post_weapi(
            "/weapi/v6/playlist/detail",
            {"id": str(pid), "n": 100000, "s": 0},
            require_auth=False,
            session=sess,
        )
        pl = detail.get("playlist")
        if not pl:
            # Fallback to /api/v6/playlist/detail
            resp = sess.post(
                "https://music.163.com/api/v6/playlist/detail",
                data={"id": str(pid), "n": 100000, "s": 0},
                timeout=12,
            )
            detail = resp.json()
            pl = detail.get("playlist")

        if not pl:
            msg = detail.get("message") or detail.get("msg") or "歌单不存在或为私密歌单（私密歌单请先粘贴网易云 Cookie 登录）"
            raise ValueError(f"读取网易云歌单失败: {msg}")

        playlist_name = pl.get("name") or "网易云音乐歌单"
        track_ids_objs = pl.get("trackIds") or []
        all_ids = [str(item["id"]) for item in track_ids_objs if isinstance(item, dict) and item.get("id")]

        tracks: List[Dict[str, Any]] = []
        if all_ids:
            song_map: Dict[str, Dict[str, Any]] = {}
            # Pre-populate with any tracks already returned in `playlist.tracks`
            for t in pl.get("tracks") or []:
                if isinstance(t, dict) and t.get("id"):
                    song_map[str(t["id"])] = t

            missing_ids = [sid for sid in all_ids if sid not in song_map]
            for i in range(0, len(missing_ids), 500):
                batch_ids = missing_ids[i : i + 500]
                c_str = json.dumps([{"id": int(sid)} for sid in batch_ids])
                ids_str = json.dumps([int(sid) for sid in batch_ids])
                s_res = self._post_weapi(
                    "/weapi/v3/song/detail",
                    {"c": c_str, "ids": ids_str},
                    require_auth=False,
                    session=sess,
                )
                for s in s_res.get("songs") or []:
                    if isinstance(s, dict) and s.get("id"):
                        song_map[str(s["id"])] = s
                if i + 500 < len(missing_ids):
                    time.sleep(0.1)

            for sid in all_ids:
                parsed = self._song_obj_to_track(song_map.get(sid) or {})
                if parsed:
                    tracks.append(parsed)
        else:
            for t in pl.get("tracks") or []:
                parsed = self._song_obj_to_track(t)
                if parsed:
                    tracks.append(parsed)

        return {
            "playlist_name": playlist_name,
            "count": len(tracks),
            "tracks": tracks,
        }

    def import_from_url(self, url_or_id: str) -> Dict[str, Any]:
        pid = self._extract_playlist_id(url_or_id)
        return self.get_playlist_tracks(pid)

    def search_candidates(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        sess, _ = self._build_session(require_auth=False)
        songs: List[Dict[str, Any]] = []
        try:
            res = self._post_weapi(
                "/weapi/cloudsearch/get/web",
                {"s": query, "type": 1, "offset": 0, "limit": limit, "total": "true"},
                require_auth=False,
                session=sess,
            )
            songs = ((res.get("result") or {}).get("songs")) or []
        except Exception:
            pass

        if not songs:
            try:
                res2 = self._post_weapi(
                    "/weapi/search/get",
                    {"s": query, "type": 1, "offset": 0, "limit": limit},
                    require_auth=False,
                    session=sess,
                )
                songs = ((res2.get("result") or {}).get("songs")) or []
            except Exception:
                pass

        candidates: List[Dict[str, Any]] = []
        for s in songs[:limit]:
            sid = str(s.get("id") or "")
            if not sid:
                continue
            ar_list = s.get("ar") or s.get("artists") or []
            artists = ", ".join([a.get("name", "") for a in ar_list if isinstance(a, dict) and a.get("name")])
            al_obj = s.get("al") or s.get("album") or {}
            album = al_obj.get("name", "") if isinstance(al_obj, dict) else ""
            dur_ms = int(s.get("dt") or s.get("duration") or 0)
            candidates.append(
                {
                    "platform": "netease",
                    "track_id": sid,
                    "display_id": sid,
                    "title": s.get("name") or "",
                    "artist": artists,
                    "album": album,
                    "duration": format_duration_ms(dur_ms),
                    "duration_seconds": dur_ms // 1000,
                    "resultType": "song",
                    "url": f"https://music.163.com/#/song?id={sid}",
                }
            )
        return candidates

    def create_playlist(
        self,
        title: str,
        description: str = "",
        privacy_status: str = "PRIVATE",
    ) -> str:
        privacy_code = "0" if privacy_status == "PUBLIC" else "10"
        res = self._post_weapi(
            "/weapi/playlist/create",
            {
                "name": (title or "Switch Music 导入歌单").strip(),
                "privacy": privacy_code,
                "type": "NORMAL",
            },
            require_auth=True,
        )
        pid = res.get("id") or ((res.get("playlist") or {}).get("id"))
        if not pid:
            raise RuntimeError(f"创建网易云音乐歌单失败: {res.get('message') or res.get('msg') or res}")
        return str(pid)

    def get_existing_track_ids(
        self,
        playlist_id: Optional[str],
        target_mode: str = "existing_playlist",
    ) -> Set[str]:
        ids: Set[str] = set()
        try:
            pid = self._get_liked_playlist_id() if target_mode == "liked_songs" else playlist_id
            if not pid:
                return ids
            detail = self._post_weapi(
                "/weapi/v6/playlist/detail",
                {"id": str(pid), "n": 100000, "s": 0},
                require_auth=True,
            )
            for item in ((detail.get("playlist") or {}).get("trackIds")) or []:
                if isinstance(item, dict) and item.get("id"):
                    ids.add(str(item["id"]))
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
        sess, _ = self._build_session(require_auth=True)
        pid = self._get_liked_playlist_id() if target_mode == "liked_songs" else playlist_id
        if not pid:
            raise ValueError("未指定目标网易云音乐歌单 ID。")

        song_ids: List[int] = []
        for c in candidates:
            sid_str = str(c.get("track_id") or "").strip()
            if not sid_str.isdigit():
                continue
            if skip_duplicates:
                if sid_str in seen_ids:
                    continue
                seen_ids.add(sid_str)
            song_ids.append(int(sid_str))

        if not song_ids:
            return 0

        # Note: NetEase manipulate/tracks prepends tracks to the top of the playlist;
        # reversing each chunk preserves natural order nicely when viewed or we keep exact order:
        added = 0
        for i in range(0, len(song_ids), 100):
            chunk = song_ids[i : i + 100]
            res = self._post_weapi(
                "/weapi/playlist/manipulate/tracks",
                {
                    "op": "add",
                    "pid": str(pid),
                    "trackIds": json.dumps(chunk),
                    "imme": "true",
                },
                require_auth=True,
                session=sess,
            )
            code = res.get("code")
            if code == 200:
                added += len(chunk)
            elif code == 502:
                # 502 = duplicate songs exist in batch; retry one by one
                for single_id in chunk:
                    r1 = self._post_weapi(
                        "/weapi/playlist/manipulate/tracks",
                        {
                            "op": "add",
                            "pid": str(pid),
                            "trackIds": json.dumps([single_id]),
                            "imme": "true",
                        },
                        require_auth=True,
                        session=sess,
                    )
                    if r1.get("code") == 200:
                        added += 1
            time.sleep(0.15)
        return added

    def get_dedupe_raw_items(self, playlist_id: str) -> Tuple[str, List[Dict[str, Any]]]:
        data = self.get_playlist_tracks(playlist_id)
        items: List[Dict[str, Any]] = []
        for idx, t in enumerate(data.get("tracks") or []):
            sid = str(t.get("source_id") or "")
            dur_ms = int(t.get("duration_ms") or 0)
            artist_str = t.get("artist") or ""
            items.append(
                {
                    "position": idx + 1,
                    "item_id": sid,
                    "videoId": sid,
                    "setVideoId": sid,
                    "can_remove": bool(sid),
                    "title": t.get("title") or "Unknown",
                    "artist": artist_str,
                    "primary_artist": artist_str.split(",")[0].strip() if artist_str else "",
                    "album": t.get("album") or "",
                    "duration": format_duration_ms(dur_ms),
                    "duration_seconds": dur_ms // 1000,
                    "url": f"https://music.163.com/#/song?id={sid}" if sid else "",
                    "extra": {},
                }
            )
        return data.get("playlist_name") or "网易云音乐歌单", items

    def remove_playlist_duplicates(self, playlist_id: str, items: List[Dict[str, Any]]) -> int:
        sess, _ = self._build_session(require_auth=True)
        pid = self._get_liked_playlist_id() if playlist_id == "liked_songs" else playlist_id
        del_ids = [
            int(str(it.get("item_id") or it.get("videoId")))
            for it in items
            if str(it.get("item_id") or it.get("videoId") or "").isdigit()
        ]
        if not del_ids:
            raise ValueError("没有可移除的有效网易云歌曲项。")

        removed = 0
        for i in range(0, len(del_ids), 100):
            chunk = del_ids[i : i + 100]
            res = self._post_weapi(
                "/weapi/playlist/manipulate/tracks",
                {
                    "op": "del",
                    "pid": str(pid),
                    "trackIds": json.dumps(chunk),
                    "imme": "true",
                },
                require_auth=True,
                session=sess,
            )
            if res.get("code") == 200:
                removed += len(chunk)
            time.sleep(0.15)
        return removed

    def build_playlist_url(self, playlist_id: Optional[str], target_mode: str = "new_playlist") -> str:
        if playlist_id and playlist_id != "liked_songs":
            return f"https://music.163.com/#/playlist?id={playlist_id}"
        return "https://music.163.com/#/my/"
