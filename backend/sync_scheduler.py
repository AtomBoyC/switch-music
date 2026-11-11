from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Set

from backend.config import SYNC_TASKS_FILE, read_json_file, write_json_file
from backend.matcher import match_cache, match_track_with_provider
from backend.models import SyncTaskCreateRequest, TrackItem
from backend.providers import get_provider
from backend.text_utils import clean_str


def _track_fingerprint(t: Dict[str, Any]) -> str:
    sid = str(t.get("source_id") or t.get("spotify_uri") or "").strip()
    if sid:
        return f"id:{sid}"
    return f"sig:{clean_str(t.get('title', ''))}|{clean_str(t.get('artist', ''))}"


class IncrementalSyncScheduler:
    """
    Lightweight background scheduler that periodically pulls newly added tracks
    from any connected source playlist (e.g. Spotify Liked Songs, NetEase, QQ Music)
    and syncs only the incremental diff to the target playlist/Liked Songs.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._running_task_ids: Set[str] = set()

    def _load_tasks(self) -> List[Dict[str, Any]]:
        data = read_json_file(SYNC_TASKS_FILE, [])
        return data if isinstance(data, list) else []

    def _save_tasks(self, tasks: List[Dict[str, Any]]) -> None:
        write_json_file(SYNC_TASKS_FILE, tasks)

    def start(self) -> None:
        with self._lock:
            if self._worker_thread and self._worker_thread.is_alive():
                return
            self._stop_event.clear()
            self._worker_thread = threading.Thread(target=self._loop, daemon=True, name="SyncScheduler")
            self._worker_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._lock:
            tasks = self._load_tasks()
            out = []
            for t in tasks:
                copy_t = {k: v for k, v in t.items() if k != "synced_fingerprints"}
                copy_t["known_tracks_count"] = len(t.get("synced_fingerprints") or [])
                copy_t["is_running_now"] = t.get("id") in self._running_task_ids
                out.append(copy_t)
            return out

    def create_task(self, req: SyncTaskCreateRequest) -> Dict[str, Any]:
        interval = max(10, min(10080, int(req.interval_minutes or 120)))
        now_ts = int(time.time())
        task_id = "sync_" + str(uuid.uuid4())[:8]
        task: Dict[str, Any] = {
            "id": task_id,
            "name": req.name.strip() or f"{req.source_platform} → {req.target_platform} 自动同步",
            "source_platform": req.source_platform,
            "source_playlist_id": req.source_playlist_id,
            "source_playlist_name": req.source_playlist_name or req.source_playlist_id,
            "target_platform": req.target_platform,
            "target_mode": req.target_mode,
            "target_playlist_id": req.target_playlist_id,
            "target_playlist_name": req.target_playlist_name or (
                "❤️ 我喜欢的音乐" if req.target_mode == "liked_songs" else (req.target_playlist_id or "")
            ),
            "interval_minutes": interval,
            "enabled": req.enabled,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_run_at": None,
            "next_run_ts": now_ts + interval * 60,
            "last_status": "idle",
            "last_added_count": 0,
            "total_synced_count": 0,
            "last_message": "已创建定时同步规则，点击「立即同步」可执行首次增量扫描",
            "synced_fingerprints": [],
        }
        with self._lock:
            tasks = self._load_tasks()
            tasks.insert(0, task)
            self._save_tasks(tasks)
        return {k: v for k, v in task.items() if k != "synced_fingerprints"}

    def toggle_task(self, task_id: str, enabled: bool) -> Dict[str, Any]:
        with self._lock:
            tasks = self._load_tasks()
            for t in tasks:
                if t.get("id") == task_id:
                    t["enabled"] = bool(enabled)
                    if enabled:
                        t["next_run_ts"] = int(time.time()) + int(t.get("interval_minutes", 120)) * 60
                    self._save_tasks(tasks)
                    return {k: v for k, v in t.items() if k != "synced_fingerprints"}
        raise ValueError("找不到该定时同步任务。")

    def delete_task(self, task_id: str) -> bool:
        with self._lock:
            tasks = [t for t in self._load_tasks() if t.get("id") != task_id]
            self._save_tasks(tasks)
            return True

    def trigger_now(self, task_id: str) -> Dict[str, Any]:
        with self._lock:
            tasks = self._load_tasks()
            if not any(t.get("id") == task_id for t in tasks):
                raise ValueError("找不到该定时同步任务。")
            if task_id in self._running_task_ids:
                return {"success": True, "message": "该同步任务正在执行中..."}
            self._running_task_ids.add(task_id)

        th = threading.Thread(target=self._execute_task, args=(task_id,), daemon=True)
        th.start()
        return {"success": True, "message": "已触发后台增量同步任务！"}

    def _loop(self) -> None:
        while not self._stop_event.wait(20.0):
            now_ts = int(time.time())
            due_ids: List[str] = []
            with self._lock:
                tasks = self._load_tasks()
                for t in tasks:
                    tid = t.get("id")
                    if (
                        tid
                        and t.get("enabled")
                        and tid not in self._running_task_ids
                        and now_ts >= int(t.get("next_run_ts") or 0)
                    ):
                        self._running_task_ids.add(tid)
                        due_ids.append(tid)
            for tid in due_ids:
                self._execute_task(tid)

    def _execute_task(self, task_id: str) -> None:
        try:
            with self._lock:
                tasks = self._load_tasks()
                task = next((t for t in tasks if t.get("id") == task_id), None)
                if not task:
                    return
                task["last_status"] = "running"
                task["last_message"] = "正在拉取源歌单并检测新增曲目..."
                self._save_tasks(tasks)

            src_prov = get_provider(task["source_platform"])
            tgt_prov = get_provider(task["target_platform"])

            src_data = src_prov.get_playlist_tracks(task["source_playlist_id"])
            src_tracks = src_data.get("tracks") or []

            known_set: Set[str] = set(task.get("synced_fingerprints") or [])
            new_raw_tracks: List[Dict[str, Any]] = []
            all_current_fps: List[str] = []

            for raw_t in src_tracks:
                fp = _track_fingerprint(raw_t)
                all_current_fps.append(fp)
                if fp not in known_set:
                    new_raw_tracks.append(raw_t)

            added_count = 0
            if new_raw_tracks:
                existing_target_ids = tgt_prov.get_existing_track_ids(
                    task.get("target_playlist_id"), task.get("target_mode", "existing_playlist")
                )
                matched_cands: List[Dict[str, Any]] = []
                for raw_t in new_raw_tracks:
                    tr = TrackItem(**raw_t)
                    m = match_track_with_provider(tgt_prov, tr, use_cache=True)
                    if m and m.get("track_id"):
                        matched_cands.append(m)
                    time.sleep(0.08)

                match_cache.flush()
                if matched_cands:
                    added_count = tgt_prov.add_tracks(
                        playlist_id=task.get("target_playlist_id"),
                        target_mode=task.get("target_mode", "existing_playlist"),
                        candidates=matched_cands,
                        seen_ids=existing_target_ids,
                        skip_duplicates=True,
                    )

            merged_fps = list(dict.fromkeys(list(known_set) + all_current_fps))[-10000:]
            with self._lock:
                tasks = self._load_tasks()
                for t in tasks:
                    if t.get("id") == task_id:
                        t["last_run_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        t["next_run_ts"] = int(time.time()) + int(t.get("interval_minutes", 120)) * 60
                        t["last_status"] = "ok"
                        t["last_added_count"] = added_count
                        t["total_synced_count"] = int(t.get("total_synced_count") or 0) + added_count
                        t["synced_fingerprints"] = merged_fps
                        if len(new_raw_tracks) == 0:
                            t["last_message"] = f"扫描完成（共 {len(src_tracks)} 首），暂无新增曲目"
                        else:
                            t["last_message"] = f"发现 {len(new_raw_tracks)} 首新歌，成功同步写入 {added_count} 首"
                        break
                self._save_tasks(tasks)
        except Exception as e:
            with self._lock:
                tasks = self._load_tasks()
                for t in tasks:
                    if t.get("id") == task_id:
                        t["last_run_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        t["next_run_ts"] = int(time.time()) + int(t.get("interval_minutes", 120)) * 60
                        t["last_status"] = "error"
                        t["last_message"] = f"同步出错: {str(e)}"
                        break
                self._save_tasks(tasks)
        finally:
            with self._lock:
                self._running_task_ids.discard(task_id)


sync_scheduler = IncrementalSyncScheduler()
