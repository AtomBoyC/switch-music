from __future__ import annotations

from typing import Any, Dict, List

from backend.models import TrackItem, model_to_dict
from backend.text_utils import clean_str, parse_duration_seconds


def deduplicate_source_tracks(tracks: List[TrackItem], mode: str = "standard") -> Dict[str, Any]:
    seen_ids: Dict[str, Dict[str, Any]] = {}
    seen_isrcs: Dict[str, Dict[str, Any]] = {}
    seen_sigs: Dict[tuple, Dict[str, Any]] = {}
    seen_title_dur: Dict[str, List[Dict[str, Any]]] = {}

    unique_tracks: List[Dict[str, Any]] = []
    removed_items: List[Dict[str, Any]] = []
    groups_map: Dict[int, Dict[str, Any]] = {}
    idx_to_gid: Dict[int, int] = {}
    next_gid = 1

    for idx, t in enumerate(tracks):
        uri = (t.spotify_uri or t.source_id or "").strip()
        isrc = (t.isrc or "").strip().upper()
        primary_artist = t.artist.split(",")[0].strip() if t.artist else ""
        dur_sec = (t.duration_ms or 0) // 1000

        if mode == "strict":
            sig = (t.title.strip().lower(), primary_artist.lower())
        else:
            sig = (clean_str(t.title), clean_str(primary_artist))

        info = {
            "track_index": idx,
            "position": idx + 1,
            "title": t.title,
            "artist": t.artist,
            "album": t.album or "",
            "duration_ms": t.duration_ms or 0,
            "duration_seconds": dur_sec,
        }

        kept = None
        reason = ""
        reason_code = ""

        if uri and uri in seen_ids:
            kept = seen_ids[uri]
            reason = "完全相同曲目 (同平台 ID/URI)"
            reason_code = "exact_id"
        elif mode != "strict" and isrc and isrc in seen_isrcs:
            kept = seen_isrcs[isrc]
            reason = "相同录音编码 (同 ISRC)"
            reason_code = "same_isrc"
        elif sig[0] and sig in seen_sigs:
            kept = seen_sigs[sig]
            reason = "同名同歌手 (含简繁/不同专辑版)"
            reason_code = "same_song"
        elif mode == "deep" and len(sig[0]) >= 2 and dur_sec > 0 and sig[0] in seen_title_dur:
            for prev in seen_title_dur[sig[0]]:
                if prev["duration_seconds"] > 0 and abs(prev["duration_seconds"] - dur_sec) <= 3:
                    kept = prev
                    reason = "同名且时长一致 (疑似译名/多版本)"
                    reason_code = "title_duration"
                    break

        if kept is not None:
            removed_items.append(info)
            k_idx = kept["track_index"]
            if k_idx not in idx_to_gid:
                gid = next_gid
                next_gid += 1
                idx_to_gid[k_idx] = gid
                groups_map[gid] = {
                    "group_id": gid,
                    "reason": reason,
                    "reason_code": reason_code,
                    "items": [{**kept, "reason": "最早出现", "reason_code": reason_code, "default_remove": False}],
                }
            else:
                gid = idx_to_gid[k_idx]

            idx_to_gid[idx] = gid
            groups_map[gid]["items"].append(
                {**info, "reason": reason, "reason_code": reason_code, "default_remove": True}
            )
        else:
            if uri:
                seen_ids[uri] = info
            if isrc:
                seen_isrcs[isrc] = info
            if sig[0]:
                seen_sigs[sig] = info
            if len(sig[0]) >= 2 and dur_sec > 0:
                seen_title_dur.setdefault(sig[0], []).append(info)
            unique_tracks.append(model_to_dict(t))

    return {
        "unique_tracks": unique_tracks,
        "unique_count": len(unique_tracks),
        "removed_count": len(removed_items),
        "removed_items": removed_items,
        "groups": list(groups_map.values()),
    }


def analyze_playlist_duplicate_groups(
    raw_items: List[Dict[str, Any]],
    playlist_id: str,
    playlist_title: str,
    mode: str = "standard",
    platform: str = "ytm",
) -> Dict[str, Any]:
    """
    Generic playlist duplicate-group detector supporting YouTube Music, Spotify, NetEase, and QQ Music.
    Each item in raw_items should contain:
      item_id, videoId (optional), setVideoId (optional), can_remove (bool),
      title, artist, primary_artist, album, duration, duration_seconds, url, extra
    """
    seen_id: Dict[str, Dict[str, Any]] = {}
    seen_sig: Dict[tuple, Dict[str, Any]] = {}
    seen_title_dur: Dict[str, List[Dict[str, Any]]] = {}
    groups_map: Dict[int, Dict[str, Any]] = {}
    pos_to_gid: Dict[int, int] = {}
    next_gid = 1
    duplicates_count = 0

    for idx, t in enumerate(raw_items):
        if not t:
            continue
        pos = t.get("position") or (idx + 1)
        item_id = str(t.get("item_id") or t.get("videoId") or "").strip()
        vid = str(t.get("videoId") or item_id).strip()
        set_vid = str(t.get("setVideoId") or "").strip()
        title = t.get("title") or "Unknown"
        artist_str = t.get("artist") or ""
        primary_artist = t.get("primary_artist") or (artist_str.split(",")[0].strip() if artist_str else "")
        album_str = t.get("album") or ""
        duration_str = t.get("duration") or ""
        dur_sec = int(t.get("duration_seconds") or parse_duration_seconds(duration_str) or 0)

        info = {
            "position": pos,
            "item_id": item_id,
            "videoId": vid,
            "setVideoId": set_vid,
            "can_remove": bool(t.get("can_remove", False)),
            "title": title,
            "artist": artist_str,
            "album": album_str,
            "duration": duration_str,
            "duration_seconds": dur_sec,
            "url": t.get("url") or "",
            "extra": t.get("extra") or {},
        }

        norm_t = clean_str(title)
        norm_a = clean_str(primary_artist)

        kept = None
        reason = ""
        reason_code = ""

        if item_id and item_id in seen_id:
            kept = seen_id[item_id]
            reason = "完全相同歌曲 (同 ID)"
            reason_code = "exact_id"
        elif mode in ("standard", "deep") and norm_t and norm_a and (norm_t, norm_a) in seen_sig:
            kept = seen_sig[(norm_t, norm_a)]
            reason = "同名同歌手 (不同版本/简繁体)"
            reason_code = "same_song"
        elif mode == "deep" and len(norm_t) >= 2 and dur_sec > 0 and norm_t in seen_title_dur:
            for prev in seen_title_dur[norm_t]:
                if prev["duration_seconds"] > 0 and abs(prev["duration_seconds"] - dur_sec) <= 3:
                    kept = prev
                    reason = "同名且时长一致 (疑似中英译名/多版本)"
                    reason_code = "title_duration"
                    break

        if kept is not None:
            duplicates_count += 1
            kpos = kept["position"]
            if kpos not in pos_to_gid:
                gid = next_gid
                next_gid += 1
                pos_to_gid[kpos] = gid
                groups_map[gid] = {
                    "group_id": gid,
                    "reason": reason,
                    "reason_code": reason_code,
                    "items": [
                        {
                            **kept,
                            "reason": "最早出现",
                            "reason_code": reason_code,
                            "default_remove": False,
                        }
                    ],
                }
            else:
                gid = pos_to_gid[kpos]

            pos_to_gid[pos] = gid
            groups_map[gid]["items"].append(
                {
                    **info,
                    "reason": reason,
                    "reason_code": reason_code,
                    "default_remove": True,
                }
            )
        else:
            if item_id:
                seen_id[item_id] = info
            if norm_t and norm_a and (norm_t, norm_a) not in seen_sig:
                seen_sig[(norm_t, norm_a)] = info
            if len(norm_t) >= 2 and dur_sec > 0:
                seen_title_dur.setdefault(norm_t, []).append(info)

    groups = list(groups_map.values())
    return {
        "platform": platform,
        "playlist_id": playlist_id,
        "playlist_title": playlist_title,
        "total_tracks": len(raw_items),
        "unique_count": len(raw_items) - duplicates_count,
        "duplicates_count": duplicates_count,
        "groups_count": len(groups),
        "groups": groups,
    }
