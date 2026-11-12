from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.config import MATCH_CACHE_FILE, read_json_file, write_json_file
from backend.models import TrackItem
from backend.text_utils import (
    clean_str,
    extract_version_tags,
    parse_duration_seconds,
    split_artists,
    strip_noise_for_query,
    to_simplified,
)

HIGH_CONFIDENCE_THRESHOLD = 65
DEFAULT_MIN_SCORE = 38
CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days


class MatchCache:
    """Thread-safe local match cache to accelerate repeated track searches across playlists."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: Dict[str, Dict[str, Any]] = read_json_file(MATCH_CACHE_FILE, {})
        if not isinstance(self._data, dict):
            self._data = {}
        self._dirty_count = 0

    @staticmethod
    def make_key(target_platform: str, track: TrackItem) -> str:
        t_clean = clean_str(track.title)
        a_clean = clean_str(track.artist.split(",")[0] if track.artist else "")
        dur_bucket = ((track.duration_ms or 0) // 5000) if track.duration_ms else 0
        isrc = (track.isrc or "").strip().upper()
        return f"{target_platform}|{isrc}|{t_clean}|{a_clean}|{dur_bucket}"

    def get(self, target_platform: str, track: TrackItem) -> Optional[Dict[str, Any]]:
        key = self.make_key(target_platform, track)
        with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            ts = entry.get("ts", 0)
            if time.time() - ts > CACHE_TTL_SECONDS:
                self._data.pop(key, None)
                return None
            cand = entry.get("candidate")
            return dict(cand) if isinstance(cand, dict) else None

    def put(self, target_platform: str, track: TrackItem, candidate: Dict[str, Any], flush_now: bool = False) -> None:
        key = self.make_key(target_platform, track)
        with self._lock:
            self._data[key] = {
                "ts": int(time.time()),
                "source": {
                    "title": track.title or "",
                    "artist": track.artist or "",
                    "album": track.album or "",
                    "isrc": track.isrc or "",
                },
                "candidate": candidate,
            }
            self._dirty_count += 1
            # Cap cache size to 15,000 entries
            if len(self._data) > 15000:
                oldest_keys = sorted(self._data.keys(), key=lambda k: self._data[k].get("ts", 0))[:2000]
                for k in oldest_keys:
                    self._data.pop(k, None)
            if flush_now or self._dirty_count >= 25:
                self.flush()

    def flush(self) -> None:
        with self._lock:
            if self._dirty_count > 0:
                write_json_file(MATCH_CACHE_FILE, self._data)
                self._dirty_count = 0

    def delete_key(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                self._data.pop(key, None)
                write_json_file(MATCH_CACHE_FILE, self._data)
                self._dirty_count = 0
                return True
            return False

    def list_entries(self, platform: str = "", query: str = "", limit: int = 200) -> Dict[str, Any]:
        plat_filter = (platform or "").strip().lower()
        q_filter = (query or "").strip().lower()
        cap = max(1, min(1000, int(limit or 200)))
        now = time.time()

        with self._lock:
            total_all = len(self._data)
            by_platform: Dict[str, int] = {}
            matched_rows: List[Dict[str, Any]] = []

            for key, entry in self._data.items():
                if not isinstance(entry, dict):
                    continue
                ts = int(entry.get("ts") or 0)
                if ts and (now - ts > CACHE_TTL_SECONDS):
                    continue
                parts = key.split("|")
                tgt_plat = parts[0] if parts else ""
                by_platform[tgt_plat] = by_platform.get(tgt_plat, 0) + 1

                if plat_filter and tgt_plat != plat_filter:
                    continue

                src = entry.get("source") if isinstance(entry.get("source"), dict) else {}
                cand = entry.get("candidate") if isinstance(entry.get("candidate"), dict) else {}
                src_title = str(src.get("title") or (parts[2] if len(parts) > 2 else "")).strip()
                src_artist = str(src.get("artist") or (parts[3] if len(parts) > 3 else "")).strip()
                src_isrc = str(src.get("isrc") or (parts[1] if len(parts) > 1 else "")).strip()

                cand_title = str(cand.get("title") or "").strip()
                cand_artist = str(cand.get("artist") or "").strip()

                if q_filter:
                    haystack = f"{src_title} {src_artist} {src_isrc} {cand_title} {cand_artist}".lower()
                    if q_filter not in haystack:
                        continue

                matched_rows.append(
                    {
                        "key": key,
                        "target_platform": tgt_plat,
                        "source_title": src_title,
                        "source_artist": src_artist,
                        "source_isrc": src_isrc,
                        "matched_id": str(cand.get("track_id") or ""),
                        "matched_title": cand_title,
                        "matched_artist": cand_artist,
                        "matched_album": str(cand.get("album") or ""),
                        "matched_duration": str(cand.get("duration") or ""),
                        "matched_url": str(cand.get("url") or ""),
                        "score": cand.get("score"),
                        "confidence": str(cand.get("confidence") or ""),
                        "match_reason": str(cand.get("match_reason") or ""),
                        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "",
                        "_ts": ts,
                    }
                )

            matched_rows.sort(key=lambda r: r.get("_ts", 0), reverse=True)
            total_filtered = len(matched_rows)
            sliced = [{k: v for k, v in r.items() if k != "_ts"} for r in matched_rows[:cap]]
            return {
                "total_cached": total_all,
                "filtered_count": total_filtered,
                "by_platform": by_platform,
                "entries": sliced,
            }

    def clear(self) -> int:
        with self._lock:
            count = len(self._data)
            self._data.clear()
            self._dirty_count = 0
            write_json_file(MATCH_CACHE_FILE, {})
            return count


match_cache = MatchCache()


def build_search_queries(track: TrackItem) -> List[str]:
    """
    Build progressive search queries from most specific to broader fallback:
      1. Raw title + primary artist
      2. Cleaned title (without feat./remaster/OST brackets) + primary artist
      3. Cleaned title + all artists (if multiple)
      4. Cleaned title alone (catches bilingual artist aliases like Jay Chou <-> 周杰伦)
    """
    queries: List[str] = []
    raw_title = (track.title or "").strip()
    clean_title = strip_noise_for_query(raw_title)
    artists = [a.strip() for a in (track.artist or "").replace(";", ",").split(",") if a.strip()]
    primary_artist = artists[0] if artists else ""

    def _add(q: str) -> None:
        q = q.strip()
        if q and q not in queries:
            queries.append(q)

    if raw_title and primary_artist:
        _add(f"{raw_title} {primary_artist}")
    if clean_title and primary_artist and clean_title != raw_title:
        _add(f"{clean_title} {primary_artist}")
    if clean_title and len(artists) > 1:
        _add(f"{clean_title} {' '.join(artists[:2])}")
    if clean_title and len(clean_str(clean_title)) >= 2:
        _add(clean_title)
    elif raw_title:
        _add(raw_title)

    return queries[:3]


def score_candidate(
    track: TrackItem,
    cand: Dict[str, Any],
    rank_idx: int = 0,
    min_score: int = DEFAULT_MIN_SCORE,
) -> Tuple[int, str, str]:
    """
    Evaluate how closely a platform search candidate matches `track`.
    Returns (score, confidence_tier, reason_summary).
    """
    score = 0
    reasons: List[str] = []

    # 1. ISRC exact match
    src_isrc = (track.isrc or "").strip().upper()
    cand_isrc = str(cand.get("isrc") or "").strip().upper()
    isrc_matched = bool(src_isrc and cand_isrc and src_isrc == cand_isrc)
    if isrc_matched:
        score += 45
        reasons.append("ISRC精准命中")

    # 2. Search rank & result type bonus
    score += max(0, 12 - rank_idx * 3)
    if cand.get("resultType") == "song":
        score += 8

    # 3. Title similarity
    src_title_raw_simp = to_simplified(track.title or "").strip().lower()
    cand_title_raw_simp = to_simplified(cand.get("title") or "").strip().lower()
    src_title_clean = clean_str(track.title or "")
    cand_title_clean = clean_str(cand.get("title") or "")

    title_matched = False
    if src_title_clean and cand_title_clean:
        if src_title_clean == cand_title_clean:
            score += 34
            if src_title_raw_simp == cand_title_raw_simp:
                score += 4
            title_matched = True
            reasons.append("歌名完全匹配")
        elif src_title_clean in cand_title_clean or cand_title_clean in src_title_clean:
            shorter = min(len(src_title_clean), len(cand_title_clean))
            longer = max(len(src_title_clean), len(cand_title_clean))
            if shorter >= 2 and (shorter / max(1, longer)) >= 0.6:
                score += 24
                title_matched = True
                reasons.append("歌名高度相似")
            elif shorter >= 2:
                score += 15
                title_matched = True
                reasons.append("歌名部分包含")
        else:
            src_tokens = set(src_title_clean.split())
            cand_tokens = set(cand_title_clean.split())
            if src_tokens and cand_tokens:
                overlap = len(src_tokens & cand_tokens) / max(1, len(src_tokens | cand_tokens))
                if overlap >= 0.5:
                    score += 18
                    title_matched = True
                    reasons.append("歌名词汇重合")
            if not title_matched and not isrc_matched:
                # Check character overlap for CJK titles without spaces
                src_chars = {c for c in src_title_clean if not c.isspace()}
                cand_chars = {c for c in cand_title_clean if not c.isspace()}
                char_overlap = len(src_chars & cand_chars) / max(1, min(len(src_chars), len(cand_chars)))
                if char_overlap >= 0.65 and len(src_chars) >= 2:
                    score += 14
                    title_matched = True
                    reasons.append("歌名字形相近")
                else:
                    score -= 20

    # 4. Artist similarity (handles multi-artist & reversed collaborations)
    src_artists = split_artists(track.artist or "")
    cand_artists = split_artists(cand.get("artist") or "")
    artist_matched = False
    if src_artists and cand_artists:
        if src_artists[0] == cand_artists[0]:
            score += 28
            artist_matched = True
            reasons.append("主歌手一致")
        elif set(src_artists) & set(cand_artists):
            score += 24
            artist_matched = True
            reasons.append("合作歌手匹配")
        else:
            for sa in src_artists:
                for ca in cand_artists:
                    if (len(sa) >= 2 and sa in ca) or (len(ca) >= 2 and ca in sa):
                        score += 20
                        artist_matched = True
                        reasons.append("歌手名包含匹配")
                        break
                if artist_matched:
                    break
        if not artist_matched:
            score -= 8
    elif not src_artists and title_matched:
        # Plain text import with title only
        score += 10

    # 5. Album similarity
    src_album_clean = clean_str(track.album or "")
    cand_album_clean = clean_str(cand.get("album") or "")
    if src_album_clean and cand_album_clean and len(src_album_clean) >= 2 and len(cand_album_clean) >= 2:
        if src_album_clean == cand_album_clean:
            score += 10
            reasons.append("同专辑")
        elif src_album_clean in cand_album_clean or cand_album_clean in src_album_clean:
            score += 6

    # 6. Duration proximity
    target_sec = (track.duration_ms // 1000) if track.duration_ms else 0
    cand_sec = int(cand.get("duration_seconds") or parse_duration_seconds(cand.get("duration")) or 0)
    if target_sec > 0 and cand_sec > 0:
        diff = abs(target_sec - cand_sec)
        if diff <= 2:
            score += 16
            reasons.append("时长吻合")
        elif diff <= 5:
            score += 12
        elif diff <= 12:
            score += 6
        elif diff > 90:
            score -= 25
            reasons.append(f"时长差异过大({diff}s)")
        elif diff > 45:
            score -= 14
            reasons.append(f"时长偏差({diff}s)")

    # 7. Version tag alignment (penalize unwanted karaoke/cover/live/DJ/sped-up versions)
    src_tags = extract_version_tags(f"{track.title} {track.album or ''}")
    cand_tags = extract_version_tags(f"{cand.get('title', '')} {cand.get('album', '')}")

    if "instrumental" in cand_tags and "instrumental" not in src_tags:
        score -= 45
        reasons.append("疑似伴奏降权")
    if "cover" in cand_tags and "cover" not in src_tags:
        score -= 26
        reasons.append("疑似翻唱降权")
    if "dj" in cand_tags and "dj" not in src_tags:
        score -= 24
        reasons.append("疑似DJ版降权")
    if "sped_slowed" in cand_tags and "sped_slowed" not in src_tags:
        score -= 24
        reasons.append("疑似倍速版降权")
    if "live" in cand_tags and "live" not in src_tags:
        score -= 18
        reasons.append("现场版降权")
    if "remix" in cand_tags and "remix" not in src_tags:
        score -= 14
        reasons.append("混音版降权")

    shared_tags = src_tags & cand_tags
    if shared_tags:
        score += 12
        reasons.append("版本特征一致")

    if score >= HIGH_CONFIDENCE_THRESHOLD:
        confidence = "high"
    elif score >= min_score:
        confidence = "low"
    else:
        confidence = "unmatched"

    return score, confidence, " · ".join(reasons[:3]) if reasons else "综合搜索排名"


def match_track_with_provider(
    provider: Any,
    track: TrackItem,
    use_cache: bool = True,
    min_score: int = DEFAULT_MIN_SCORE,
) -> Optional[Dict[str, Any]]:
    """
    Match a single TrackItem against any PlatformProvider using cache + multi-round search + scoring.
    """
    target_platform = provider.platform_id

    # Direct same-platform shortcut if source_platform == target_platform and source_id is valid
    if track.source_platform == target_platform and track.source_id:
        return {
            "platform": target_platform,
            "track_id": track.source_id,
            "videoId": track.source_id if target_platform == "ytm" else "",
            "title": track.title,
            "artist": track.artist,
            "album": track.album or "",
            "duration": "",
            "duration_seconds": (track.duration_ms or 0) // 1000,
            "resultType": "song",
            "url": (track.extra or {}).get("url", ""),
            "score": 100,
            "confidence": "high",
            "match_reason": "同平台原曲直通",
            "extra": track.extra or {},
        }

    if use_cache:
        cached = match_cache.get(target_platform, track)
        if cached and cached.get("score", 0) >= min_score:
            return cached

    best_candidate: Optional[Dict[str, Any]] = None
    best_score = -999

    # Optional ISRC direct lookup if provider supports it
    isrc = (track.isrc or "").strip()
    if isrc and hasattr(provider, "search_by_isrc"):
        try:
            isrc_cands = provider.search_by_isrc(isrc) or []
            for idx, cand in enumerate(isrc_cands):
                cand_copy = dict(cand)
                cand_copy.setdefault("isrc", isrc)
                sc, conf, reason = score_candidate(track, cand_copy, rank_idx=idx, min_score=min_score)
                if sc > best_score:
                    best_score = sc
                    best_candidate = {**cand_copy, "score": sc, "confidence": conf, "match_reason": reason}
            if best_candidate and best_score >= HIGH_CONFIDENCE_THRESHOLD:
                if use_cache:
                    match_cache.put(target_platform, track, best_candidate)
                return best_candidate
        except Exception:
            pass

    queries = build_search_queries(track)
    seen_cand_ids = set()
    search_errors = 0
    last_error: Optional[BaseException] = None

    for q_idx, q in enumerate(queries):
        try:
            candidates = provider.search_candidates(q, limit=6) or []
        except Exception as exc:
            search_errors += 1
            last_error = exc
            candidates = []

        for idx, cand in enumerate(candidates):
            cid = cand.get("track_id")
            if not cid or cid in seen_cand_ids:
                continue
            seen_cand_ids.add(cid)

            sc, conf, reason = score_candidate(track, cand, rank_idx=idx + q_idx, min_score=min_score)
            if sc > best_score:
                best_score = sc
                best_candidate = {
                    **cand,
                    "score": sc,
                    "confidence": conf,
                    "match_reason": reason,
                }

        # Stop querying fallback variants if we already have a strong high-confidence match
        if best_candidate and best_score >= HIGH_CONFIDENCE_THRESHOLD:
            break

    if best_candidate and best_score >= min_score:
        if use_cache:
            match_cache.put(target_platform, track, best_candidate)
        return best_candidate

    # Every search attempt failed (network / rate limit / expired login): report it as an
    # error instead of a misleading "unmatched", so the user knows a retry may succeed.
    if queries and search_errors == len(queries) and best_candidate is None and last_error is not None:
        raise SearchFailedError(str(last_error) or last_error.__class__.__name__)

    return None


class SearchFailedError(RuntimeError):
    """Raised when all search queries for a track failed with exceptions."""
