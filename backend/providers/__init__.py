from __future__ import annotations

from typing import Dict

from backend.providers.base import PlatformProvider
from backend.providers.netease import NetEaseProvider
from backend.providers.qqmusic import QQMusicProvider
from backend.providers.spotify import SpotifyProvider
from backend.providers.ytm import YTMProvider

ytm_provider = YTMProvider()
spotify_provider = SpotifyProvider()
netease_provider = NetEaseProvider()
qqmusic_provider = QQMusicProvider()

PROVIDERS: Dict[str, PlatformProvider] = {
    "ytm": ytm_provider,
    "spotify": spotify_provider,
    "netease": netease_provider,
    "qqmusic": qqmusic_provider,
}


def get_provider(platform_id: str) -> PlatformProvider:
    pid = (platform_id or "").strip().lower()
    if pid not in PROVIDERS:
        raise ValueError(f"不支持的音乐平台标识: {platform_id}")
    return PROVIDERS[pid]


def detect_platform_from_url(url_or_text: str) -> str:
    s = (url_or_text or "").lower()
    if "163.com" in s or "163cn.tv" in s:
        return "netease"
    if "y.qq.com" in s or "qq.com" in s or "url.cn" in s:
        return "qqmusic"
    if "music.youtube.com" in s or "youtube.com/playlist" in s:
        return "ytm"
    if "spotify.com" in s or s.startswith("spotify:"):
        return "spotify"
    raise ValueError("未能自动识别链接所属平台，请手动指定平台（网易云音乐 / QQ音乐 / YouTube Music / Spotify）。")
