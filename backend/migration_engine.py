from __future__ import annotations

import concurrent.futures
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Set

from backend.config import HISTORY_FILE, JOBS_DIR, read_json_file, write_json_file
from backend.matcher import match_cache, match_track_with_provider
from backend.models import (
    ManualApplyMatchRequest,
    MigrationRequest,
    PreviewMatchRequest,
    TrackItem,
    model_to_dict,
)
from backend.providers import get_provider

_jobs_lock = threading.RLock()
migration_jobs: Dict[str, Dict[str, Any]] = {}


def _save_job_to_disk(job: Dict[str, Any]) -> None:
    job_id = job["job_id"]
    write_json_file(JOBS_DIR / f"job_{job_id}.json", job)
    if job.get("job_type") == "migrate":
        _upsert_history_summary(job)


def _upsert_history_summary(job: Dict[str, Any]) -> None:
    with _jobs_lock:
        history: List[Dict[str, Any]] = read_json_file(HISTORY_FILE, [])
        if not isinstance(history, list):
            history = []
        summary = {
            "job_id": job["job_id"],
            "status": job["status"],
            "source_platform": job.get("source_platform", ""),
            "target_platform": job.get("target_platform", "ytm"),
            "target_mode": job.get("target_mode", "new_playlist"),
            "playlist_title": job.get("playlist_title", ""),
            "target_playlist_id": job.get("target_playlist_id"),
            "target_playlist_url": job.get("target_playlist_url", ""),
            "total": job.get("total", 0),
            "matched_count": job.get("matched_count", 0),
            "low_confidence_count": job.get("low_confidence_count", 0),
            "already_existed_count": job.get("already_existed_count", 0),
            "unmatched_count": job.get("unmatched_count", 0),
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "error": job.get("error"),
        }
        history = [h for h in history if h.get("job_id") != job["job_id"]]
        history.insert(0, summary)
        write_json_file(HISTORY_FILE, history[:60])


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _jobs_lock:
        if job_id in migration_jobs:
            return migration_jobs[job_id]
    disk_job = read_json_file(JOBS_DIR / f"job_{job_id}.json", None)
    if isinstance(disk_job, dict):
        with _jobs_lock:
            migration_jobs[job_id] = disk_job
        return disk_job
    return None


def get_history_list() -> List[Dict[str, Any]]:
    data = read_json_file(HISTORY_FILE, [])
    return data if isinstance(data, list) else []


def delete_history_item(job_id: str) -> bool:
    with _jobs_lock:
        migration_jobs.pop(job_id, None)
        job_file = JOBS_DIR / f"job_{job_id}.json"
        if job_file.exists():
            job_file.unlink()
        history = [h for h in get_history_list() if h.get("job_id") != job_id]
        write_json_file(HISTORY_FILE, history)
        return True


def clear_all_history() -> int:
    with _jobs_lock:
        history = get_history_list()
        count = len(history)
        for h in history:
            jid = h.get("job_id")
            if jid:
                migration_jobs.pop(jid, None)
                jf = JOBS_DIR / f"job_{jid}.json"
                if jf.exists():
                    jf.unlink()
        write_json_file(HISTORY_FILE, [])
        return count


def cancel_job(job_id: str) -> bool:
    job = get_job(job_id)
    if not job:
        return False
    job["cancel_requested"] = True
    return True


def _format_result_row(
    idx: int,
    track: TrackItem,
    match: Optional[Dict[str, Any]],
    skipped_by_user: bool = False,
    already_existed: bool = False,
) -> Dict[str, Any]:
    base = {
        "index": idx + 1,
        "track_index": idx,
        "source_title": track.title,
        "source_artist": track.artist,
        "source_album": track.album or "",
        "source_duration_ms": track.duration_ms or 0,
        "source_track": model_to_dict(track),
    }
    if skipped_by_user:
        return {
            **base,
            "status": "skipped",
            "confidence": "skipped",
            "score": 0,
            "match_reason": "用户手动跳过",
        }
    if not match or not match.get("track_id"):
        return {
            **base,
            "status": "unmatched",
            "confidence": "unmatched",
            "score": 0,
            "match_reason": "未找到高于阈值的匹配结果",
        }

    vid = match.get("videoId") or match.get("track_id") or ""
    return {
        **base,
        "status": "matched",
        "already_existed": already_existed,
        "confidence": match.get("confidence", "high"),
        "score": match.get("score", 80),
        "match_reason": match.get("match_reason", ""),
        "matched_platform": match.get("platform", ""),
        "matched_track_id": match.get("track_id", ""),
        "matched_title": match.get("title", ""),
        "matched_artist": match.get("artist", ""),
        "matched_album": match.get("album", ""),
        "matched_duration": match.get("duration", ""),
        "matched_url": match.get("url", ""),
        "candidate": match,
        # Backward-compatible fields for YTM UI links
        "ytm_video_id": vid,
        "ytm_title": match.get("title", ""),
        "ytm_artist": match.get("artist", ""),
        "ytm_duration": match.get("duration", ""),
        "result_type": match.get("resultType", "song"),
    }


def start_preview_job(req: PreviewMatchRequest) -> str:
    provider = get_provider(req.target_platform)
    # Verify target search works (for Spotify, requires OAuth; YTM/NetEase/QQ work even without login for search!)
    if req.target_platform == "spotify":
        provider.get_status()

    job_id = "pre_" + str(uuid.uuid4())[:8]
    concurrency = max(1, min(6, int(req.concurrency or 4)))
    job: Dict[str, Any] = {
        "job_id": job_id,
        "job_type": "preview",
        "status": "running",
        "target_platform": req.target_platform,
        "total": len(req.tracks),
        "current_index": 0,
        "current_track": "正在并发搜索匹配候选曲目...",
        "matched_count": 0,
        "high_confidence_count": 0,
        "low_confidence_count": 0,
        "unmatched_count": 0,
        "results": [],
        "unmatched_tracks": [],
        "error": None,
        "cancel_requested": False,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "completed_at": None,
    }
    with _jobs_lock:
        migration_jobs[job_id] = job

    t = threading.Thread(target=_run_preview_worker, args=(job_id, req, concurrency), daemon=True)
    t.start()
    return job_id


def _run_preview_worker(job_id: str, req: PreviewMatchRequest, concurrency: int) -> None:
    job = migration_jobs[job_id]
    try:
        provider = get_provider(req.target_platform)
        total = len(req.tracks)
        completed_map: Dict[int, Optional[Dict[str, Any]]] = {}
        next_commit = 0
        commit_lock = threading.Lock()

        def _match_one(idx: int, tr: TrackItem) -> None:
            if job.get("cancel_requested"):
                return
            job["current_track"] = f"{tr.title} - {tr.artist}"
            m = match_track_with_provider(
                provider,
                tr,
                use_cache=req.use_cache,
                min_score=req.min_score,
            )
            with commit_lock:
                nonlocal next_commit
                completed_map[idx] = m
                while next_commit in completed_map:
                    res_match = completed_map.pop(next_commit)
                    src_tr = req.tracks[next_commit]
                    row = _format_result_row(next_commit, src_tr, res_match)
                    job["results"].append(row)
                    job["current_index"] = next_commit + 1
                    if row["status"] == "matched":
                        job["matched_count"] += 1
                        if row["confidence"] == "low":
                            job["low_confidence_count"] += 1
                        else:
                            job["high_confidence_count"] += 1
                    else:
                        job["unmatched_count"] += 1
                        job["unmatched_tracks"].append(model_to_dict(src_tr))
                    next_commit += 1

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = []
            for i, track in enumerate(req.tracks):
                if job.get("cancel_requested"):
                    break
                futures.append(pool.submit(_match_one, i, track))
            for f in concurrent.futures.as_completed(futures):
                if job.get("cancel_requested"):
                    break
                try:
                    f.result()
                except Exception:
                    pass

        match_cache.flush()
        job["status"] = "cancelled" if job.get("cancel_requested") else "completed"
        job["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        job["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")


def start_migration_job(req: MigrationRequest) -> str:
    provider = get_provider(req.target_platform)
    status = provider.get_status()
    if not status.get("connected"):
        raise ValueError(f"目标平台「{provider.platform_name}」尚未登录连接，请先在顶部连接面板完成授权或粘贴 Cookie。")
    if req.target_platform == "spotify" and not status.get("has_write_scope", True):
        raise ValueError("当前 Spotify 登录缺少歌单写入权限，请在连接面板点击「重新授权登录 Spotify」开启写入权限。")

    job_id = str(uuid.uuid4())[:8]
    concurrency = max(1, min(6, int(req.concurrency or 4)))
    job: Dict[str, Any] = {
        "job_id": job_id,
        "job_type": "migrate",
        "status": "running",
        "source_platform": req.source_platform,
        "target_platform": req.target_platform,
        "target_platform_name": provider.platform_name,
        "target_mode": req.target_mode,
        "playlist_title": req.playlist_title,
        "target_playlist_id": req.existing_playlist_id,
        "target_playlist_url": "",
        "total": len(req.tracks),
        "current_index": 0,
        "current_track": "正在初始化目标歌单...",
        "matched_count": 0,
        "high_confidence_count": 0,
        "low_confidence_count": 0,
        "already_existed_count": 0,
        "unmatched_count": 0,
        "skipped_count": 0,
        "results": [],
        "unmatched_tracks": [],
        "error": None,
        "cancel_requested": False,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "completed_at": None,
    }
    with _jobs_lock:
        migration_jobs[job_id] = job

    t = threading.Thread(target=_run_migration_worker, args=(job_id, req, concurrency), daemon=True)
    t.start()
    return job_id


def _run_migration_worker(job_id: str, req: MigrationRequest, concurrency: int) -> None:
    job = migration_jobs[job_id]
    provider = get_provider(req.target_platform)

    target_playlist_id: Optional[str] = None
    try:
        if req.target_mode == "new_playlist":
            title = (req.playlist_title or "Switch Music Playlist").strip()
            desc = (req.playlist_description or "Imported via Switch Music").strip()
            target_playlist_id = provider.create_playlist(
                title=title,
                description=desc,
                privacy_status=req.privacy_status or "PRIVATE",
            )
            job["target_playlist_id"] = target_playlist_id
        elif req.target_mode == "existing_playlist":
            if not req.existing_playlist_id:
                raise ValueError("未选择要追加的现有歌单。")
            target_playlist_id = req.existing_playlist_id
            job["target_playlist_id"] = target_playlist_id

        job["target_playlist_url"] = provider.build_playlist_url(target_playlist_id, req.target_mode)
    except Exception as e:
        job["status"] = "failed"
        job["error"] = f"准备目标歌单失败: {str(e)}"
        job["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_job_to_disk(job)
        return

    existing_ids: Set[str] = set()
    if req.skip_duplicates and req.target_mode in ("existing_playlist", "liked_songs"):
        job["current_track"] = "正在读取目标歌单已有曲目用于防重..."
        existing_ids = provider.get_existing_track_ids(target_playlist_id, req.target_mode)

    seen_write_ids: Set[str] = set(existing_ids)
    batch_buffer: List[Dict[str, Any]] = []
    prematched = req.prematched or {}

    completed_map: Dict[int, Dict[str, Any]] = {}
    next_commit = 0
    commit_lock = threading.Lock()

    def _flush_buffer() -> None:
        if not batch_buffer:
            return
        to_write = list(batch_buffer)
        batch_buffer.clear()
        provider.add_tracks(
            playlist_id=target_playlist_id,
            target_mode=req.target_mode,
            candidates=to_write,
            seen_ids=seen_write_ids,
            skip_duplicates=req.skip_duplicates,
        )

    def _resolve_track(idx: int, tr: TrackItem) -> Dict[str, Any]:
        key_str = str(idx)
        if key_str in prematched:
            pm = prematched[key_str]
            if pm.get("skip"):
                return {"skipped": True, "match": None}
            if pm.get("candidate") and pm["candidate"].get("track_id"):
                return {"skipped": False, "match": pm["candidate"]}
            if pm.get("track_id"):
                return {"skipped": False, "match": pm}

        job["current_track"] = f"{tr.title} - {tr.artist}"
        m = match_track_with_provider(
            provider,
            tr,
            use_cache=req.use_cache,
            min_score=req.min_score,
        )
        # Gentle pacing per worker when hitting live search APIs
        if not prematched:
            time.sleep(0.08)
        return {"skipped": False, "match": m}

    def _worker_task(idx: int, tr: TrackItem) -> None:
        if job.get("cancel_requested"):
            return
        outcome = _resolve_track(idx, tr)
        batches_to_flush: List[List[Dict[str, Any]]] = []

        with commit_lock:
            nonlocal next_commit
            completed_map[idx] = outcome
            while next_commit in completed_map:
                cur_out = completed_map.pop(next_commit)
                cur_tr = req.tracks[next_commit]
                skipped = bool(cur_out.get("skipped"))
                match_cand = cur_out.get("match")

                already_existed = False
                if match_cand and match_cand.get("track_id"):
                    cid_check = str(
                        (match_cand.get("extra") or {}).get("songId")
                        if req.target_platform == "qqmusic" and (match_cand.get("extra") or {}).get("songId")
                        else match_cand["track_id"]
                    )
                    if req.skip_duplicates and cid_check in existing_ids:
                        already_existed = True
                    else:
                        batch_buffer.append(match_cand)
                        if len(batch_buffer) >= 25:
                            batches_to_flush.append(list(batch_buffer))
                            batch_buffer.clear()

                row = _format_result_row(
                    next_commit,
                    cur_tr,
                    match_cand,
                    skipped_by_user=skipped,
                    already_existed=already_existed,
                )
                job["results"].append(row)
                job["current_index"] = next_commit + 1

                if skipped:
                    job["skipped_count"] += 1
                elif row["status"] == "matched":
                    job["matched_count"] += 1
                    if already_existed:
                        job["already_existed_count"] += 1
                    if row["confidence"] == "low":
                        job["low_confidence_count"] += 1
                    else:
                        job["high_confidence_count"] += 1
                else:
                    job["unmatched_count"] += 1
                    job["unmatched_tracks"].append(model_to_dict(cur_tr))

                next_commit += 1

        # Perform batch API writes outside commit_lock while preserving order
        for chunk in batches_to_flush:
            if job.get("cancel_requested"):
                break
            provider.add_tracks(
                playlist_id=target_playlist_id,
                target_mode=req.target_mode,
                candidates=chunk,
                seen_ids=seen_write_ids,
                skip_duplicates=req.skip_duplicates,
            )

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = []
            for i, track in enumerate(req.tracks):
                if job.get("cancel_requested"):
                    break
                futures.append(pool.submit(_worker_task, i, track))
            for f in concurrent.futures.as_completed(futures):
                if job.get("cancel_requested"):
                    break
                try:
                    f.result()
                except Exception:
                    pass

        if batch_buffer and not job.get("cancel_requested"):
            _flush_buffer()

        match_cache.flush()
        if job["status"] == "running":
            job["status"] = "cancelled" if job.get("cancel_requested") else "completed"
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)

    job["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_job_to_disk(job)


def apply_manual_match(req: ManualApplyMatchRequest) -> Dict[str, Any]:
    """
    Immediately add a manually selected candidate track to the target playlist/liked songs
    and update the migration job record & local match cache.
    """
    provider = get_provider(req.target_platform)
    cand = dict(req.candidate)
    cand["confidence"] = "manual"
    cand["score"] = 100
    cand["match_reason"] = "人工指定曲目"

    added = provider.add_tracks(
        playlist_id=req.playlist_id,
        target_mode=req.target_mode,
        candidates=[cand],
        seen_ids=set(),
        skip_duplicates=False,
    )

    if req.job_id:
        job = get_job(req.job_id)
        if job and req.result_index is not None:
            with _jobs_lock:
                for idx, r in enumerate(job.get("results") or []):
                    row_track_idx = r["track_index"] if "track_index" in r else (r.get("index", 1) - 1)
                    if row_track_idx == req.result_index:
                        prev_status = r.get("status")
                        prev_conf = r.get("confidence")
                        src_dict = r.get("source_track") or {
                            "title": r.get("source_title", ""),
                            "artist": r.get("source_artist", ""),
                            "album": r.get("source_album", ""),
                            "duration_ms": r.get("source_duration_ms", 0),
                        }
                        src_track = TrackItem(**src_dict)
                        match_cache.put(req.target_platform, src_track, cand, flush_now=True)

                        updated_row = _format_result_row(
                            r.get("track_index", r.get("index", 1) - 1),
                            src_track,
                            cand,
                        )
                        job["results"][idx] = updated_row
                        if prev_status == "unmatched":
                            job["unmatched_count"] = max(0, job.get("unmatched_count", 1) - 1)
                            job["matched_count"] = job.get("matched_count", 0) + 1
                            job["unmatched_tracks"] = [
                                ut
                                for ut in (job.get("unmatched_tracks") or [])
                                if not (ut.get("title") == src_track.title and ut.get("artist") == src_track.artist)
                            ]
                        elif prev_conf == "low":
                            job["low_confidence_count"] = max(0, job.get("low_confidence_count", 1) - 1)
                        break
                _save_job_to_disk(job)

    return {"success": True, "added_count": added, "candidate": cand}
