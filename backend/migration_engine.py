from __future__ import annotations

import concurrent.futures
import queue
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

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

WRITE_BATCH_SIZE = 25
WRITE_RETRY_ATTEMPTS = 3
WRITE_RETRY_BACKOFF_SECONDS = 1.5
CHECKPOINT_EVERY = 100


def _job_file(job_id: str):
    return JOBS_DIR / f"job_{job_id}.json"


def _job_tracks_file(job_id: str):
    return JOBS_DIR / f"job_{job_id}_tracks.json"


def _remove_job_files(job_id: str) -> None:
    for f in (_job_file(job_id), _job_tracks_file(job_id)):
        try:
            if f.exists():
                f.unlink()
        except OSError:
            pass


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
        _remove_job_files(job_id)
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
                _remove_job_files(jid)
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
    error: Optional[str] = None,
) -> Dict[str, Any]:
    base = {
        "index": idx + 1,
        "track_index": idx,
        "source_title": track.title,
        "source_artist": track.artist,
        "source_album": track.album or "",
        "source_duration_ms": track.duration_ms or 0,
        "source_track": model_to_dict(track),
        "write_failed": False,
    }
    if skipped_by_user:
        return {
            **base,
            "status": "skipped",
            "confidence": "skipped",
            "score": 0,
            "match_reason": "用户手动跳过",
        }
    if error:
        return {
            **base,
            "status": "error",
            "confidence": "unmatched",
            "score": 0,
            "match_reason": f"搜索出错（可稍后重试）: {error[:160]}",
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
        "error_count": 0,
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
            err: Optional[str] = None
            try:
                m = match_track_with_provider(
                    provider,
                    tr,
                    use_cache=req.use_cache,
                    min_score=req.min_score,
                )
            except Exception as exc:  # never leave a hole in the ordered commit window
                m = None
                err = str(exc) or exc.__class__.__name__
            with commit_lock:
                nonlocal next_commit
                completed_map[idx] = {"match": m, "error": err}
                while next_commit in completed_map:
                    res = completed_map.pop(next_commit)
                    src_tr = req.tracks[next_commit]
                    row = _format_result_row(next_commit, src_tr, res["match"], error=res["error"])
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
                        if row["status"] == "error":
                            job["error_count"] = job.get("error_count", 0) + 1
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
        "error_count": 0,
        "write_failed_count": 0,
        "last_write_error": None,
        "pending_count": 0,
        "pending_tracks": [],
        "results": [],
        "unmatched_tracks": [],
        "error": None,
        "cancel_requested": False,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "completed_at": None,
    }
    with _jobs_lock:
        migration_jobs[job_id] = job
    # Snapshot source tracks so an interrupted job (crash / restart) can resume its remainder.
    write_json_file(_job_tracks_file(job_id), [model_to_dict(t) for t in req.tracks])
    _save_job_to_disk(job)

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
    batch_buffer: List[Tuple[int, Dict[str, Any]]] = []
    prematched = req.prematched or {}

    completed_map: Dict[int, Dict[str, Any]] = {}
    next_commit = 0
    commit_lock = threading.Lock()

    # Single ordered writer: chunks are enqueued under commit_lock (in playlist order)
    # and written strictly one at a time, so concurrent searches can never reorder
    # or race playlist writes, and write failures are recorded instead of swallowed.
    write_queue: "queue.Queue[Optional[List[Tuple[int, Dict[str, Any]]]]]" = queue.Queue()

    def _mark_write_failed(chunk: List[Tuple[int, Dict[str, Any]]], err: str) -> None:
        with commit_lock:
            for t_idx, _cand in chunk:
                if t_idx < len(job["results"]):
                    row = job["results"][t_idx]
                    row["write_failed"] = True
                    row["match_reason"] = f"写入目标平台失败: {err[:120]}"
                job["unmatched_tracks"].append(model_to_dict(req.tracks[t_idx]))
            job["write_failed_count"] = job.get("write_failed_count", 0) + len(chunk)
            job["last_write_error"] = err[:300]

    def _writer_loop() -> None:
        while True:
            chunk = write_queue.get()
            if chunk is None:
                return
            if job.get("cancel_requested"):
                continue
            last_err = ""
            for attempt in range(WRITE_RETRY_ATTEMPTS):
                try:
                    provider.add_tracks(
                        playlist_id=target_playlist_id,
                        target_mode=req.target_mode,
                        candidates=[c for _i, c in chunk],
                        seen_ids=seen_write_ids,
                        skip_duplicates=req.skip_duplicates,
                    )
                    last_err = ""
                    break
                except Exception as exc:
                    last_err = str(exc) or exc.__class__.__name__
                    time.sleep(WRITE_RETRY_BACKOFF_SECONDS * (attempt + 1))
            if last_err:
                _mark_write_failed(chunk, last_err)

    writer_thread = threading.Thread(target=_writer_loop, daemon=True)
    writer_thread.start()

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
        try:
            m = match_track_with_provider(
                provider,
                tr,
                use_cache=req.use_cache,
                min_score=req.min_score,
            )
        except Exception as exc:  # never leave a hole in the ordered commit window
            return {"skipped": False, "match": None, "error": str(exc) or exc.__class__.__name__}
        # Gentle pacing per worker when hitting live search APIs
        if not prematched:
            time.sleep(0.08)
        return {"skipped": False, "match": m}

    def _worker_task(idx: int, tr: TrackItem) -> None:
        if job.get("cancel_requested"):
            return
        try:
            outcome = _resolve_track(idx, tr)
        except Exception as exc:
            outcome = {"skipped": False, "match": None, "error": str(exc) or exc.__class__.__name__}

        with commit_lock:
            nonlocal next_commit
            completed_map[idx] = outcome
            while next_commit in completed_map:
                cur_out = completed_map.pop(next_commit)
                cur_tr = req.tracks[next_commit]
                skipped = bool(cur_out.get("skipped"))
                match_cand = cur_out.get("match")
                err = cur_out.get("error")

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
                        batch_buffer.append((next_commit, match_cand))
                        if len(batch_buffer) >= WRITE_BATCH_SIZE:
                            write_queue.put(list(batch_buffer))
                            batch_buffer.clear()

                row = _format_result_row(
                    next_commit,
                    cur_tr,
                    match_cand,
                    skipped_by_user=skipped,
                    already_existed=already_existed,
                    error=err,
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
                    if row["status"] == "error":
                        job["error_count"] = job.get("error_count", 0) + 1
                    job["unmatched_tracks"].append(model_to_dict(cur_tr))

                next_commit += 1
                if next_commit % CHECKPOINT_EVERY == 0:
                    _save_job_to_disk(job)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = []
            for i, track in enumerate(req.tracks):
                if job.get("cancel_requested"):
                    break
                futures.append(pool.submit(_worker_task, i, track))
            for f in concurrent.futures.as_completed(futures):
                try:
                    f.result()
                except Exception:
                    pass

        with commit_lock:
            if batch_buffer and not job.get("cancel_requested"):
                write_queue.put(list(batch_buffer))
            batch_buffer.clear()
        write_queue.put(None)
        writer_thread.join()

        match_cache.flush()
        if job["status"] == "running":
            job["status"] = "cancelled" if job.get("cancel_requested") else "completed"
    except Exception as e:
        write_queue.put(None)
        job["status"] = "failed"
        job["error"] = str(e)

    _attach_pending_tracks(job, req.tracks)
    job["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_job_to_disk(job)


def _attach_pending_tracks(job: Dict[str, Any], tracks: List[Any]) -> None:
    """Tracks never processed (cancel / crash / restart) are kept so they can be retried in one click."""
    done = len(job.get("results") or [])
    pending = []
    for t in tracks[done:]:
        pending.append(t if isinstance(t, dict) else model_to_dict(t))
    job["pending_tracks"] = pending
    job["pending_count"] = len(pending)


def recover_interrupted_jobs() -> int:
    """
    Called at server startup: any migration job checkpointed as "running" was interrupted
    by a crash / restart. Mark it as interrupted and expose its unprocessed tracks.
    """
    recovered = 0
    for jf in JOBS_DIR.glob("job_*.json"):
        if jf.name.endswith("_tracks.json"):
            continue
        job = read_json_file(jf, None)
        if not isinstance(job, dict) or job.get("status") != "running":
            continue
        job_id = job.get("job_id") or jf.stem[len("job_"):]
        src_tracks = read_json_file(JOBS_DIR / f"job_{job_id}_tracks.json", [])
        job["status"] = "interrupted"
        job["error"] = "服务在任务执行过程中被关闭或重启，可点击「重试未完成曲目」继续。"
        job["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _attach_pending_tracks(job, src_tracks if isinstance(src_tracks, list) else [])
        with _jobs_lock:
            migration_jobs.pop(job_id, None)
        _save_job_to_disk(job)
        recovered += 1
    return recovered


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
                        if r.get("write_failed"):
                            job["write_failed_count"] = max(0, job.get("write_failed_count", 1) - 1)
                            job["unmatched_tracks"] = [
                                ut
                                for ut in (job.get("unmatched_tracks") or [])
                                if not (ut.get("title") == src_track.title and ut.get("artist") == src_track.artist)
                            ]
                        if prev_status in ("unmatched", "error"):
                            if prev_status == "error":
                                job["error_count"] = max(0, job.get("error_count", 1) - 1)
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
