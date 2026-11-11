from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple


class PlatformProvider:
    """Unified interface for music streaming platforms (YTM, Spotify, NetEase, QQ Music)."""

    platform_id: str = ""
    platform_name: str = ""

    def get_status(self) -> Dict[str, Any]:
        raise NotImplementedError

    def disconnect(self) -> Dict[str, Any]:
        raise NotImplementedError

    def get_user_playlists(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def get_playlist_tracks(self, playlist_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def import_from_url(self, url_or_id: str) -> Dict[str, Any]:
        raise NotImplementedError(f"{self.platform_name} 暂不支持通过该链接直接导入。")

    def search_candidates(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def create_playlist(
        self,
        title: str,
        description: str = "",
        privacy_status: str = "PRIVATE",
    ) -> str:
        raise NotImplementedError

    def get_existing_track_ids(
        self,
        playlist_id: Optional[str],
        target_mode: str = "existing_playlist",
    ) -> Set[str]:
        return set()

    def add_tracks(
        self,
        playlist_id: Optional[str],
        target_mode: str,
        candidates: List[Dict[str, Any]],
        seen_ids: Set[str],
        skip_duplicates: bool = True,
    ) -> int:
        raise NotImplementedError

    def get_dedupe_raw_items(self, playlist_id: str) -> Tuple[str, List[Dict[str, Any]]]:
        raise NotImplementedError

    def remove_playlist_duplicates(self, playlist_id: str, items: List[Dict[str, Any]]) -> int:
        raise NotImplementedError

    def build_playlist_url(self, playlist_id: Optional[str], target_mode: str = "new_playlist") -> str:
        return ""
