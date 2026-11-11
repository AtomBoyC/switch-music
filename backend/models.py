from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.config import DEFAULT_SPOTIFY_REDIRECT_URI


def model_to_dict(obj: BaseModel) -> Dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()  # type: ignore[attr-defined]
    return obj.dict()  # type: ignore[attr-defined]


class RawAuthPayload(BaseModel):
    headers_raw: str


class SpotifyConfigPayload(BaseModel):
    client_id: str
    client_secret: str
    redirect_uri: str = DEFAULT_SPOTIFY_REDIRECT_URI


class UrlImportPayload(BaseModel):
    platform: str = "auto"  # "auto" | "netease" | "qqmusic" | "kugou" | "applemusic" | "ytm" | "spotify"
    url_or_id: str


class TextImportPayload(BaseModel):
    text: str
    playlist_name: str = "文本导入歌单"


class TrackItem(BaseModel):
    title: str
    artist: str = ""
    album: Optional[str] = ""
    duration_ms: Optional[int] = 0
    isrc: Optional[str] = ""
    spotify_uri: Optional[str] = ""
    source_platform: Optional[str] = ""
    source_id: Optional[str] = ""
    extra: Dict[str, Any] = Field(default_factory=dict)


class PreviewMatchRequest(BaseModel):
    target_platform: str = "ytm"
    concurrency: int = 4
    use_cache: bool = True
    min_score: int = 38
    tracks: List[TrackItem]


class MigrationRequest(BaseModel):
    source_platform: str = "spotify"
    target_platform: str = "ytm"  # "ytm" | "spotify" | "netease" | "qqmusic" | "kugou" | "applemusic"
    target_mode: str = "new_playlist"  # "new_playlist" | "existing_playlist" | "liked_songs"
    playlist_title: Optional[str] = "My Imported Playlist"
    playlist_description: Optional[str] = "Imported via Switch Music"
    privacy_status: str = "PRIVATE"  # "PRIVATE" | "PUBLIC" | "UNLISTED"
    existing_playlist_id: Optional[str] = None
    skip_duplicates: bool = True
    concurrency: int = 4
    use_cache: bool = True
    min_score: int = 38
    tracks: List[TrackItem]
    # Optional index -> overridden candidate dict (or {"skip": True})
    prematched: Optional[Dict[str, Dict[str, Any]]] = None


class ManualSearchRequest(BaseModel):
    platform: str = "ytm"
    query: str
    limit: int = 8
    source_track: Optional[TrackItem] = None


class ManualApplyMatchRequest(BaseModel):
    target_platform: str
    target_mode: str = "existing_playlist"  # "existing_playlist" | "liked_songs"
    playlist_id: Optional[str] = None
    candidate: Dict[str, Any]
    job_id: Optional[str] = None
    result_index: Optional[int] = None


class DeduplicateTracksRequest(BaseModel):
    mode: str = "standard"  # "standard" | "strict" | "deep"
    tracks: List[TrackItem]


class RemovePlaylistItem(BaseModel):
    item_id: Optional[str] = ""
    videoId: Optional[str] = ""
    setVideoId: Optional[str] = ""
    extra: Dict[str, Any] = Field(default_factory=dict)


class RemoveDuplicatesRequest(BaseModel):
    items: List[RemovePlaylistItem]


class ExportCsvRequest(BaseModel):
    playlist_name: str = "Switch_Music_Export"
    tracks: List[Dict[str, Any]]


class SyncTaskCreateRequest(BaseModel):
    name: str
    source_platform: str
    source_playlist_id: str
    source_playlist_name: str = ""
    target_platform: str
    target_mode: str = "existing_playlist"  # "existing_playlist" | "liked_songs"
    target_playlist_id: Optional[str] = None
    target_playlist_name: str = ""
    interval_minutes: int = 120
    enabled: bool = True


class SyncTaskTogglePayload(BaseModel):
    enabled: bool
