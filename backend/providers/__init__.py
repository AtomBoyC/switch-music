from __future__ import annotations

from typing import Dict

from backend.providers.applemusic import AppleMusicProvider
from backend.providers.base import PlatformProvider
from backend.providers.kugou import KugouProvider
from backend.providers.netease import NetEaseProvider
from backend.providers.qishui import QishuiProvider
from backend.providers.qqmusic import QQMusicProvider
from backend.providers.spotify import SpotifyProvider
from backend.providers.subsonic import SubsonicProvider
from backend.providers.ytm import YTMProvider

ytm_provider = YTMProvider()
spotify_provider = SpotifyProvider()
netease_provider = NetEaseProvider()
qqmusic_provider = QQMusicProvider()
kugou_provider = KugouProvider()
applemusic_provider = AppleMusicProvider()
subsonic_provider = SubsonicProvider()
qishui_provider = QishuiProvider()

PROVIDERS: Dict[str, PlatformProvider] = {
    "ytm": ytm_provider,
    "spotify": spotify_provider,
    "netease": netease_provider,
    "qqmusic": qqmusic_provider,
    "kugou": kugou_provider,
    "applemusic": applemusic_provider,
    "subsonic": subsonic_provider,
    "qishui": qishui_provider,
}


def get_provider(platform_id: str) -> PlatformProvider:
    pid = (platform_id or "").strip().lower()
    if pid not in PROVIDERS:
        raise ValueError(f"不支持的音乐平台标识: {platform_id}")
    return PROVIDERS[pid]


def detect_platform_from_url(url_or_text: str) -> str:
    s = (url_or_text or "").lower()
    if "qishui.douyin.com" in s or "music.douyin.com/qishui" in s or ("汽水音乐" in s and "http" in s):
        return "qishui"
    if "kugou.com" in s or "gcid_" in s or s.strip().startswith("collection_"):
        return "kugou"
    if "music.apple.com" in s or "apple.co/" in s:
        return "applemusic"
    if "163.com" in s or "163cn.tv" in s:
        return "netease"
    if "y.qq.com" in s or "qq.com" in s or "url.cn" in s:
        return "qqmusic"
    if "music.youtube.com" in s or "youtube.com/playlist" in s:
        return "ytm"
    if "spotify.com" in s or s.startswith("spotify:"):
        return "spotify"
    raise ValueError(
        "未能自动识别链接所属平台，请手动指定平台（网易云音乐 / QQ音乐 / 酷狗音乐 / 汽水音乐 / Apple Music / YouTube Music / Spotify）。"
    )
