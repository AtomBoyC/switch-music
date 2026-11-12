from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from backend.text_utils import format_duration_ms, parse_duration_seconds


def parse_csv_tracks(content_bytes: bytes, filename: str = "") -> Dict[str, Any]:
    """
    Parse tracks from Exportify CSV, Switch Music CSV, Soundiiz/TuneMyMusic CSV, TSV, or JSON.
    """
    try:
        text = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content_bytes.decode("gb18030")
        except UnicodeDecodeError:
            text = content_bytes.decode("latin-1", errors="replace")

    stripped = text.lstrip()
    if filename.lower().endswith((".m3u", ".m3u8")) or stripped.upper().startswith("#EXTM3U") or "#EXTINF:" in stripped[:400]:
        m3u_res = parse_m3u8_tracks(text, filename)
        if m3u_res["tracks"]:
            return m3u_res

    if filename.lower().endswith(".json") or stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            raw_list = data if isinstance(data, list) else (data.get("tracks") or data.get("songs") or [])
            tracks: List[Dict[str, Any]] = []
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or item.get("name") or item.get("songname") or "").strip()
                artist = str(item.get("artist") or item.get("artists") or item.get("singer") or "").strip()
                if title:
                    tracks.append(
                        {
                            "title": title,
                            "artist": artist,
                            "album": str(item.get("album") or item.get("albumname") or "").strip(),
                            "duration_ms": int(item.get("duration_ms") or 0),
                            "isrc": str(item.get("isrc") or "").strip(),
                            "spotify_uri": str(item.get("spotify_uri") or item.get("uri") or "").strip(),
                            "source_platform": str(item.get("source_platform") or "json"),
                            "source_id": str(item.get("source_id") or item.get("id") or ""),
                        }
                    )
            if tracks:
                stem = Path(filename).stem.replace("_", " ").strip() if filename else "Imported JSON Playlist"
                return {"playlist_name": stem, "count": len(tracks), "tracks": tracks}
        except Exception:
            pass

    # Detect delimiter (comma vs tab vs semicolon)
    first_line = text.splitlines()[0] if text.splitlines() else ""
    delimiter = "\t" if "\t" in first_line and "," not in first_line else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    tracks = []
    for row in reader:
        norm = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items() if k}

        title = (
            norm.get("track name")
            or norm.get("title")
            or norm.get("name")
            or norm.get("track")
            or norm.get("song")
            or norm.get("歌曲名")
            or norm.get("歌名")
            or norm.get("标题")
            or norm.get("歌曲标题")
            or ""
        )
        artist = (
            norm.get("artist name(s)")
            or norm.get("artist name")
            or norm.get("artists")
            or norm.get("artist")
            or norm.get("歌手")
            or norm.get("艺术家")
            or norm.get("艺人")
            or ""
        )
        album = (
            norm.get("album name")
            or norm.get("album")
            or norm.get("专辑")
            or norm.get("专辑名")
            or ""
        )
        duration_raw = (
            norm.get("duration (ms)")
            or norm.get("track duration (ms)")
            or norm.get("duration_ms")
            or ""
        )
        duration_str = norm.get("duration") or norm.get("时长") or ""
        isrc = norm.get("isrc") or ""
        uri = (
            norm.get("track uri")
            or norm.get("spotify uri")
            or norm.get("uri")
            or norm.get("source id / uri")
            or ""
        )
        source_platform = norm.get("source platform") or norm.get("platform") or "csv"
        source_id = norm.get("source id") or uri

        artist_clean = artist.replace(";", ", ")
        duration_ms = 0
        if duration_raw:
            try:
                duration_ms = int(float(duration_raw))
            except ValueError:
                duration_ms = 0
        elif duration_str:
            sec = parse_duration_seconds(duration_str)
            duration_ms = sec * 1000 if sec > 0 else 0

        if title:
            tracks.append(
                {
                    "title": title,
                    "artist": artist_clean,
                    "album": album,
                    "duration_ms": duration_ms,
                    "isrc": isrc,
                    "spotify_uri": uri if uri.startswith("spotify:") else "",
                    "source_platform": source_platform,
                    "source_id": source_id,
                }
            )

    # Fallback if CSV had no header row (plain lines)
    if not tracks and text.strip():
        plain = parse_plain_text_tracks(text, filename)
        if plain["tracks"]:
            return plain

    suggested_name = (
        Path(filename).stem.replace("_", " ").strip() if filename else "Imported Playlist"
    )
    if suggested_name.lower() == "liked" or "liked" in suggested_name.lower():
        suggested_name = "Spotify Liked Songs"

    return {
        "playlist_name": suggested_name or "Imported Playlist",
        "count": len(tracks),
        "tracks": tracks,
    }


def parse_plain_text_tracks(text: str, playlist_name: str = "文本导入歌单") -> Dict[str, Any]:
    """
    Parse plain text song lists such as:
      1. 晴天 - 周杰伦
      七里香 - 周杰伦 (04:59)
      《夜曲》 周杰伦
      Shape of You\tEd Sheeran\tDivide
    """
    tracks: List[Dict[str, Any]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        # Remove leading numbering like "1.", "01、", "(1)", "1)"
        line = re.sub(r"^\s*(?:\(\d+\)|\d+\s*[.、)\]:：-])\s*", "", line).strip()
        if not line:
            continue

        # Extract trailing duration like (04:29) or [3:45] or 04:29
        duration_ms = 0
        dur_match = re.search(r"[\(\[（【]?(\d{1,2}:\d{2}(?::\d{2})?)[\)\]）】]?\s*$", line)
        if dur_match:
            sec = parse_duration_seconds(dur_match.group(1))
            if sec > 0:
                duration_ms = sec * 1000
                line = line[: dur_match.start()].strip(" -·\t")

        title = ""
        artist = ""
        album = ""

        if "\t" in line:
            cols = [c.strip() for c in line.split("\t") if c.strip()]
            if len(cols) >= 2:
                title, artist = cols[0], cols[1]
                album = cols[2] if len(cols) >= 3 else ""
            elif cols:
                title = cols[0]
        elif " - " in line:
            left, right = line.split(" - ", 1)
            title, artist = left.strip(), right.strip()
        elif " — " in line or " – " in line:
            parts = re.split(r"\s+[—–]\s+", line, maxsplit=1)
            title = parts[0].strip()
            artist = parts[1].strip() if len(parts) > 1 else ""
        elif "-" in line:
            left, right = line.split("-", 1)
            title, artist = left.strip(), right.strip()
        else:
            book_match = re.match(r"^《([^》]+)》\s*(.*)$", line)
            if book_match:
                title = book_match.group(1).strip()
                artist = book_match.group(2).strip(" -/·")
            else:
                title = line

        title = title.strip("《》\"' ")
        artist = artist.strip()
        if title:
            tracks.append(
                {
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "duration_ms": duration_ms,
                    "isrc": "",
                    "spotify_uri": "",
                    "source_platform": "text",
                    "source_id": "",
                }
            )

    clean_name = Path(playlist_name).stem if playlist_name.endswith(".txt") else playlist_name
    return {
        "playlist_name": clean_name or "文本导入歌单",
        "count": len(tracks),
        "tracks": tracks,
    }


def export_tracks_to_csv_string(tracks: List[Dict[str, Any]]) -> str:
    """
    Generate UTF-8 CSV content compatible with both Excel and Exportify re-import.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Track Name",
            "Artist Name(s)",
            "Album Name",
            "Duration (ms)",
            "Duration",
            "ISRC",
            "Track URI",
            "Source Platform",
            "Matched Status",
            "Matched Title",
            "Matched Artist",
            "Matched URL",
        ]
    )
    for t in tracks:
        title = t.get("title") or t.get("source_title") or ""
        artist = t.get("artist") or t.get("source_artist") or ""
        album = t.get("album") or t.get("source_album") or ""
        dur_ms = int(t.get("duration_ms") or 0)
        dur_str = t.get("duration") or format_duration_ms(dur_ms)
        isrc = t.get("isrc") or ""
        uri = t.get("spotify_uri") or t.get("source_id") or ""
        src_plat = t.get("source_platform") or ""
        status = t.get("status") or ""
        m_title = t.get("matched_title") or t.get("ytm_title") or ""
        m_artist = t.get("matched_artist") or t.get("ytm_artist") or ""
        m_url = t.get("matched_url") or (
            f"https://music.youtube.com/watch?v={t['ytm_video_id']}"
            if t.get("ytm_video_id")
            else ""
        )
        writer.writerow(
            [
                title,
                artist,
                album,
                dur_ms if dur_ms > 0 else "",
                dur_str,
                isrc,
                uri,
                src_plat,
                status,
                m_title,
                m_artist,
                m_url,
            ]
        )
    return "\ufeff" + buf.getvalue()


def parse_m3u8_tracks(text: str, filename: str = "") -> Dict[str, Any]:
    """
    Parse #EXTM3U / .m3u / .m3u8 playlists (Jellyfin / Navidrome / foobar2000 / Apple Music).
    Supports #PLAYLIST: header, #EXTINF:seconds,Artist - Title metadata, and bare path lines.
    """
    playlist_name = Path(filename).stem.replace("_", " ").strip() if filename else "Imported M3U8 Playlist"
    tracks: List[Dict[str, Any]] = []
    pending_inf: Dict[str, Any] = {}

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTM3U"):
            continue
        if line.upper().startswith("#PLAYLIST:"):
            pname = line.split(":", 1)[1].strip()
            if pname:
                playlist_name = pname
            continue
        if line.upper().startswith("#EXTINF:"):
            rest = line.split(":", 1)[1].strip()
            dur_ms = 0
            display = rest
            if "," in rest:
                dur_part, display = rest.split(",", 1)
                dur_m = re.match(r"^\s*(-?\d+(?:\.\d+)?)", dur_part)
                if dur_m:
                    sec = float(dur_m.group(1))
                    if sec > 0:
                        dur_ms = int(sec * 1000)
            display = display.strip()
            artist = ""
            title = display
            if " - " in display:
                left, right = display.split(" - ", 1)
                artist, title = left.strip(), right.strip()
            elif " — " in display or " – " in display:
                parts = re.split(r"\s+[—–]\s+", display, maxsplit=1)
                artist = parts[0].strip()
                title = parts[1].strip() if len(parts) > 1 else ""
            pending_inf = {"title": title, "artist": artist, "duration_ms": dur_ms}
            continue
        if line.startswith("#"):
            continue

        # Media path or URL line
        path_val = line
        if pending_inf.get("title"):
            tracks.append(
                {
                    "title": pending_inf["title"],
                    "artist": pending_inf.get("artist", ""),
                    "album": "",
                    "duration_ms": pending_inf.get("duration_ms", 0),
                    "isrc": "",
                    "spotify_uri": "",
                    "source_platform": "m3u8",
                    "source_id": "",
                    "extra": {"path": path_val},
                }
            )
            pending_inf = {}
        else:
            # Infer Artist - Title from file basename
            stem = Path(path_val.replace("\\", "/")).stem.strip()
            stem = re.sub(r"^\d{1,3}[\s._-]+", "", stem)
            artist, title = "", stem
            if " - " in stem:
                artist, title = [x.strip() for x in stem.split(" - ", 1)]
            if title:
                tracks.append(
                    {
                        "title": title,
                        "artist": artist,
                        "album": "",
                        "duration_ms": 0,
                        "isrc": "",
                        "spotify_uri": "",
                        "source_platform": "m3u8",
                        "source_id": "",
                        "extra": {"path": path_val},
                    }
                )

    if pending_inf.get("title"):
        tracks.append(
            {
                "title": pending_inf["title"],
                "artist": pending_inf.get("artist", ""),
                "album": "",
                "duration_ms": pending_inf.get("duration_ms", 0),
                "isrc": "",
                "spotify_uri": "",
                "source_platform": "m3u8",
                "source_id": "",
            }
        )

    return {
        "playlist_name": playlist_name or "Imported M3U8 Playlist",
        "count": len(tracks),
        "tracks": tracks,
    }


def export_tracks_to_m3u8_string(tracks: List[Dict[str, Any]], playlist_name: str = "Switch Music Playlist") -> str:
    """
    Generate standard UTF-8 #EXTM3U (.m3u8) playlist compatible with Jellyfin, Navidrome, Plex & foobar2000.
    Preserves local/Subsonic relative file paths when present, falling back to URL or Artist - Title.mp3 hint.
    """
    lines = ["#EXTM3U", f"#PLAYLIST:{playlist_name}"]
    for t in tracks:
        title = str(t.get("title") or t.get("source_title") or "").strip()
        artist = str(t.get("artist") or t.get("source_artist") or "").strip()
        if not title:
            continue
        dur_ms = int(t.get("duration_ms") or 0)
        dur_sec = (dur_ms // 1000) if dur_ms > 0 else -1
        display = f"{artist} - {title}" if artist else title
        lines.append(f"#EXTINF:{dur_sec},{display}")

        extra = t.get("extra") if isinstance(t.get("extra"), dict) else {}
        location = (
            str(extra.get("path") or t.get("path") or "").strip()
            or str(t.get("matched_url") or t.get("url") or t.get("spotify_uri") or "").strip()
            or f"{display}.flac"
        )
        lines.append(location)
    return "\n".join(lines) + "\n"


def export_tracks_to_json_string(tracks: List[Dict[str, Any]], playlist_name: str = "Switch Music Playlist") -> str:
    """Export portable UTF-8 JSON backup with full metadata (ISRC, duration_ms, source IDs)."""
    cleaned = []
    for t in tracks:
        title = str(t.get("title") or t.get("source_title") or "").strip()
        if not title:
            continue
        cleaned.append(
            {
                "title": title,
                "artist": str(t.get("artist") or t.get("source_artist") or "").strip(),
                "album": str(t.get("album") or t.get("source_album") or "").strip(),
                "duration_ms": int(t.get("duration_ms") or 0),
                "isrc": str(t.get("isrc") or "").strip(),
                "source_platform": str(t.get("source_platform") or "").strip(),
                "source_id": str(t.get("source_id") or t.get("spotify_uri") or "").strip(),
                "extra": t.get("extra") if isinstance(t.get("extra"), dict) else {},
            }
        )
    return json.dumps(
        {
            "playlist_name": playlist_name,
            "count": len(cleaned),
            "tracks": cleaned,
        },
        ensure_ascii=False,
        indent=2,
    )
