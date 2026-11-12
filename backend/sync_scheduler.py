from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.config import PLATFORM_META, SYNC_TASKS_FILE, read_json_file, write_json_file
from backend.matcher import match_cache, match_track_with_provider
from backend.models import SyncTaskCreateRequest, TrackItem
from backend.notifier import notifier
from backend.providers import get_provider
from backend.text_utils import clean_str


def _track_fingerprint(t: Dict[str, Any]) -> str:
    sid = str(t.get("source_id") or t.get("spotify_uri") or t.get("item_id") or "").strip()
    if sid:
        return f"id:{sid}"
    return f"sig:{clean_str(t.get('title', ''))}|{clean_str(t.get('artist', ''))}"


def _norm_song_sig(title: str, artist: str) -> str:
    t_clean = clean_str(title or "")
    primary_artist = clean_str((artist or "").replace(";", ",").split(",")[0])
    if not t_clean:
        return ""
    return f"{t_clean}|{primary_artist}"


def _resolve_liked_playlist_id(prov: Any) -> str:
    pid_map = {
        "ytm": "LM",
        "spotify": "liked_songs",
        "applemusic": "library_songs",
        "subsonic": "STARRED",
    }
    if prov.platform_id in pid_map:
        return pid_map[prov.platform_id]
    pls = prov.get_user_playlists() or []
    for p in pls:
        if isinstance(p, dict) and p.get("is_liked") and (p.get("id") or p.get("playlistId")):
            return str(p.get("id") or p.get("playlistId"))
    raise ValueError(f"未能定位 {prov.platform_name} 的「我喜欢」歌单 ID。")


def _is_source_liked_playlist(prov: Any, playlist_id: str, playlist_name: str = "") -> bool:
    if playlist_id in ("LM", "liked_songs", "library_songs", "STARRED"):
        return True
    low_name = (playlist_name or "").lower()
    if "我喜欢" in low_name or "liked" in low_name or "starred" in low_name:
        return True
    try:
        pls = prov.get_user_playlists() or []
        for p in pls:
            if isinstance(p, dict) and str(p.get("id") or p.get("playlistId")) == str(playlist_id):
                return bool(p.get("is_liked"))
    except Exception:
        pass
    return False


class IncrementalSyncScheduler:
    """
    Background playlist sync engine supporting 3 modes:
      - append:   One-way incremental additions (source -> target, never deletes).
      - mirror:   One-way mirror (source -> target, adds & removes with empty-snapshot
                  and max-removal-ratio safety circuit breakers).
      - two_way:  Bidirectional merge (source <-> target, echo-free union on both sides).
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

    @staticmethod
    def _public_task(t: Dict[str, Any], running_ids: Set[str]) -> Dict[str, Any]:
        hidden = {"synced_fingerprints", "reverse_fingerprints", "fp_to_target_id"}
        copy_t = {k: v for k, v in t.items() if k not in hidden}
        copy_t.setdefault("sync_mode", "append")
        copy_t.setdefault("max_remove_ratio", 0.3)
        copy_t["known_tracks_count"] = len(t.get("synced_fingerprints") or [])
        copy_t["is_running_now"] = t.get("id") in running_ids
        return copy_t

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
            return [self._public_task(t, self._running_task_ids) for t in tasks]

    def create_task(self, req: SyncTaskCreateRequest) -> Dict[str, Any]:
        src_meta = PLATFORM_META.get(req.source_platform)
        tgt_meta = PLATFORM_META.get(req.target_platform)
        if not src_meta:
            raise ValueError(f"不支持的源平台: {req.source_platform}")
        if not tgt_meta or not tgt_meta.get("supports_write"):
            raise ValueError(f"目标平台 {req.target_platform} 不支持写入曲目。")

        sync_mode = (req.sync_mode or "append").strip().lower()
        if sync_mode not in ("append", "mirror", "two_way"):
            raise ValueError("不支持的同步模式（可选：append / mirror / two_way）。")

        if sync_mode == "mirror":
            if req.target_mode == "liked_songs" or not req.target_playlist_id:
                raise ValueError("「镜像同步」必须绑定具体的目标自建歌单（不支持对「我喜欢」执行删除镜像）。")
            if not tgt_meta.get("supports_dedupe"):
                raise ValueError(f"{tgt_meta['name']} 接口暂不支持从歌单删除单曲，请改用「增量追加」或「双向合并」模式。")

        if sync_mode == "two_way" and not src_meta.get("supports_write"):
            raise ValueError(f"源平台 {src_meta['name']} 不支持反向写入，无法启用「双向合并同步」。")

        interval = max(10, min(10080, int(req.interval_minutes or 120)))
        max_ratio = max(0.05, min(0.8, float(req.max_remove_ratio or 0.3)))
        now_ts = int(time.time())
        task_id = "sync_" + str(uuid.uuid4())[:8]
        arrow = "⇄" if sync_mode == "two_way" else ("🪞" if sync_mode == "mirror" else "→")
        task: Dict[str, Any] = {
            "id": task_id,
            "name": req.name.strip() or f"{req.source_platform} {arrow} {req.target_platform} 自动同步",
            "source_platform": req.source_platform,
            "source_playlist_id": req.source_playlist_id,
            "source_playlist_name": req.source_playlist_name or req.source_playlist_id,
            "target_platform": req.target_platform,
            "target_mode": req.target_mode,
            "target_playlist_id": req.target_playlist_id,
            "target_playlist_name": req.target_playlist_name
            or ("❤️ 我喜欢的音乐" if req.target_mode == "liked_songs" else (req.target_playlist_id or "")),
            "sync_mode": sync_mode,
            "max_remove_ratio": max_ratio,
            "interval_minutes": interval,
            "enabled": req.enabled,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_run_at": None,
            "next_run_ts": now_ts + interval * 60,
            "last_status": "idle",
            "last_added_count": 0,
            "last_removed_count": 0,
            "total_synced_count": 0,
            "last_message": "已创建定时同步规则，点击「立即同步」可执行首次扫描",
            "synced_fingerprints": [],
            "reverse_fingerprints": [],
            "fp_to_target_id": {},
        }
        with self._lock:
            tasks = self._load_tasks()
            tasks.insert(0, task)
            self._save_tasks(tasks)
        return self._public_task(task, self._running_task_ids)

    def toggle_task(self, task_id: str, enabled: bool) -> Dict[str, Any]:
        with self._lock:
            tasks = self._load_tasks()
            for t in tasks:
                if t.get("id") == task_id:
                    t["enabled"] = bool(enabled)
                    if enabled:
                        t["next_run_ts"] = int(time.time()) + int(t.get("interval_minutes", 120)) * 60
                    self._save_tasks(tasks)
                    return self._public_task(t, self._running_task_ids)
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
        return {"success": True, "message": "已触发后台同步任务！"}

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

    @staticmethod
    def _match_and_write(
        raw_tracks: List[Dict[str, Any]],
        dest_prov: Any,
        dest_playlist_id: Optional[str],
        dest_mode: str,
        existing_dest_ids: Set[str],
    ) -> Tuple[int, int, Set[str], Dict[str, str], Set[str]]:
        """
        Match `raw_tracks` against `dest_prov` and write them.
        Returns (added_count, unmatched_count, retry_fps, fp_to_dest_id, matched_norm_sigs).
        """
        unmatched = 0
        retry_fps: Set[str] = set()
        matched_cands: List[Dict[str, Any]] = []
        fp_to_dest_id: Dict[str, str] = {}
        matched_sigs: Set[str] = set()

        for raw_t in raw_tracks:
            fp = _track_fingerprint(raw_t)
            tr = TrackItem(**raw_t)
            try:
                m = match_track_with_provider(dest_prov, tr, use_cache=True)
            except Exception:
                retry_fps.add(fp)
                continue
            if m and m.get("track_id"):
                matched_cands.append(m)
                fp_to_dest_id[fp] = str(m["track_id"])
                sig = _norm_song_sig(m.get("title", ""), m.get("artist", ""))
                if sig:
                    matched_sigs.add(sig)
            else:
                unmatched += 1
            time.sleep(0.08)

        match_cache.flush()
        added = 0
        if matched_cands:
            added = dest_prov.add_tracks(
                playlist_id=dest_playlist_id,
                target_mode=dest_mode,
                candidates=matched_cands,
                seen_ids=existing_dest_ids,
                skip_duplicates=True,
            )
        return added, unmatched, retry_fps, fp_to_dest_id, matched_sigs

    def _execute_task(self, task_id: str) -> None:
        task_name = task_id
        try:
            with self._lock:
                tasks = self._load_tasks()
                task = next((t for t in tasks if t.get("id") == task_id), None)
                if not task:
                    return
                task_name = str(task.get("name") or task_id)
                task["last_status"] = "running"
                task["last_message"] = "正在拉取歌单并比对差异..."
                self._save_tasks(tasks)

            sync_mode = str(task.get("sync_mode") or "append").lower()
            src_prov = get_provider(task["source_platform"])
            tgt_prov = get_provider(task["target_platform"])

            src_data = src_prov.get_playlist_tracks(task["source_playlist_id"])
            src_tracks = src_data.get("tracks") or []

            known_set: Set[str] = set(task.get("synced_fingerprints") or [])
            rev_known_set: Set[str] = set(task.get("reverse_fingerprints") or [])
            fp_to_target_id: Dict[str, str] = dict(task.get("fp_to_target_id") or {})

            # Safety Rail 1: Empty-Snapshot Guard (if source suddenly returns 0 tracks on an established sync)
            if len(src_tracks) == 0 and len(known_set) > 0:
                raise RuntimeError(
                    f"源歌单返回 0 首曲目（历史已记录 {len(known_set)} 首），触发空快照防误删保护，本次同步已中止。"
                )

            # For two_way mode, pre-read target tracks to prevent echoing songs already on target
            tgt_tracks_initial: List[Dict[str, Any]] = []
            tgt_read_pid = ""
            tgt_norm_sigs: Set[str] = set()
            if sync_mode == "two_way":
                tgt_read_pid = (
                    _resolve_liked_playlist_id(tgt_prov)
                    if task.get("target_mode") == "liked_songs"
                    else str(task.get("target_playlist_id") or "")
                )
                tgt_data = tgt_prov.get_playlist_tracks(tgt_read_pid)
                tgt_tracks_initial = tgt_data.get("tracks") or []
                for tt in tgt_tracks_initial:
                    s = _norm_song_sig(tt.get("title", ""), tt.get("artist", ""))
                    if s:
                        tgt_norm_sigs.add(s)

            # 1. Forward pass: Source -> Target
            new_raw_tracks: List[Dict[str, Any]] = []
            all_current_fps: List[str] = []
            src_norm_sigs: Set[str] = set()
            for raw_t in src_tracks:
                fp = _track_fingerprint(raw_t)
                all_current_fps.append(fp)
                sig = _norm_song_sig(raw_t.get("title", ""), raw_t.get("artist", ""))
                if sig:
                    src_norm_sigs.add(sig)
                if fp not in known_set:
                    if sync_mode == "two_way" and sig and sig in tgt_norm_sigs:
                        continue
                    new_raw_tracks.append(raw_t)

            added_count = 0
            unmatched_count = 0
            retry_later_fps: Set[str] = set()
            newly_pushed_sigs_to_tgt: Set[str] = set()

            if new_raw_tracks:
                existing_target_ids = tgt_prov.get_existing_track_ids(
                    task.get("target_playlist_id"), task.get("target_mode", "existing_playlist")
                )
                added_count, unmatched_count, retry_later_fps, new_map, newly_pushed_sigs_to_tgt = self._match_and_write(
                    new_raw_tracks,
                    tgt_prov,
                    task.get("target_playlist_id"),
                    task.get("target_mode", "existing_playlist"),
                    existing_target_ids,
                )
                fp_to_target_id.update(new_map)

            # 2. Mirror Removal Pass (only when sync_mode == "mirror")
            removed_count = 0
            safety_warning = ""
            if sync_mode == "mirror" and task.get("target_playlist_id"):
                active_mapped_ids = {
                    fp_to_target_id[fp] for fp in all_current_fps if fp in fp_to_target_id and fp_to_target_id[fp]
                }
                _, tgt_raw_items = tgt_prov.get_dedupe_raw_items(str(task["target_playlist_id"]))
                to_remove_items: List[Dict[str, Any]] = []
                for it in tgt_raw_items:
                    if not it.get("can_remove", True):
                        continue
                    it_id = str(it.get("item_id") or it.get("videoId") or "")
                    it_sig = _norm_song_sig(it.get("title", ""), it.get("artist", ""))
                    still_in_source = (it_id and it_id in active_mapped_ids) or (it_sig and it_sig in src_norm_sigs)
                    if not still_in_source:
                        to_remove_items.append(it)

                if to_remove_items:
                    ratio_cap = max(0.05, min(0.8, float(task.get("max_remove_ratio") or 0.3)))
                    max_allowed = max(1, int(len(tgt_raw_items) * ratio_cap))
                    if len(tgt_raw_items) >= 2 and len(to_remove_items) > max_allowed:
                        safety_warning = (
                            f"⚠️ 触发防误删熔断：待移除 {len(to_remove_items)} 首超过安全上限 "
                            f"{max_allowed} 首（{int(ratio_cap * 100)}%），已跳过删除操作"
                        )
                    else:
                        removed_count = tgt_prov.remove_playlist_duplicates(
                            str(task["target_playlist_id"]), to_remove_items
                        )

            # 3. Reverse Pass: Target -> Source (only when sync_mode == "two_way")
            rev_added_count = 0
            rev_unmatched_count = 0
            rev_retry_fps: Set[str] = set()
            all_current_rev_fps: List[str] = []
            if sync_mode == "two_way":
                new_rev_tracks: List[Dict[str, Any]] = []
                active_src_sigs = src_norm_sigs | newly_pushed_sigs_to_tgt
                for tt in tgt_tracks_initial:
                    rfp = _track_fingerprint(tt)
                    all_current_rev_fps.append(rfp)
                    rsig = _norm_song_sig(tt.get("title", ""), tt.get("artist", ""))
                    if rfp not in rev_known_set:
                        if rsig and rsig in active_src_sigs:
                            continue
                        new_rev_tracks.append(tt)

                if new_rev_tracks:
                    src_is_liked = _is_source_liked_playlist(
                        src_prov, task["source_playlist_id"], task.get("source_playlist_name", "")
                    )
                    src_write_mode = "liked_songs" if src_is_liked else "existing_playlist"
                    src_write_pid = None if src_is_liked else task["source_playlist_id"]
                    existing_src_ids = src_prov.get_existing_track_ids(src_write_pid, src_write_mode)
                    rev_added_count, rev_unmatched_count, rev_retry_fps, _, _ = self._match_and_write(
                        new_rev_tracks,
                        src_prov,
                        src_write_pid,
                        src_write_mode,
                        existing_src_ids,
                    )

            # Keep fingerprints bounded & clean
            if sync_mode == "mirror" and not safety_warning:
                # In mirror mode, drop removed songs from known_set so re-adding them later syncs again!
                merged_fps = [fp for fp in all_current_fps if fp not in retry_later_fps][-10000:]
            else:
                merged_fps = [
                    fp for fp in dict.fromkeys(list(known_set) + all_current_fps) if fp not in retry_later_fps
                ][-10000:]

            merged_rev_fps = [
                fp for fp in dict.fromkeys(list(rev_known_set) + all_current_rev_fps) if fp not in rev_retry_fps
            ][-10000:]

            # Prune fp_to_target_id to active keys
            if len(fp_to_target_id) > 10000:
                keep_keys = set(merged_fps[-8000:])
                fp_to_target_id = {k: v for k, v in fp_to_target_id.items() if k in keep_keys}

            total_added_this_run = added_count + rev_added_count
            parts: List[str] = []
            if total_added_this_run == 0 and removed_count == 0 and not safety_warning:
                final_msg = f"扫描完成（源端 {len(src_tracks)} 首），暂无变更"
            else:
                if added_count:
                    parts.append(f"正向新增 {added_count} 首")
                if rev_added_count:
                    parts.append(f"反向合并 {rev_added_count} 首")
                if removed_count:
                    parts.append(f"镜像移除 {removed_count} 首")
                if unmatched_count + rev_unmatched_count:
                    parts.append(f"{unmatched_count + rev_unmatched_count} 首未匹配")
                if len(retry_later_fps) + len(rev_retry_fps):
                    parts.append(f"{len(retry_later_fps) + len(rev_retry_fps)} 首待下次重试")
                if safety_warning:
                    parts.append(safety_warning)
                final_msg = "；".join(parts) if parts else "同步完成"

            with self._lock:
                tasks = self._load_tasks()
                for t in tasks:
                    if t.get("id") == task_id:
                        t["last_run_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        t["next_run_ts"] = int(time.time()) + int(t.get("interval_minutes", 120)) * 60
                        t["last_status"] = "error" if safety_warning else "ok"
                        t["last_added_count"] = total_added_this_run
                        t["last_removed_count"] = removed_count
                        t["total_synced_count"] = int(t.get("total_synced_count") or 0) + total_added_this_run
                        t["total_removed_count"] = int(t.get("total_removed_count") or 0) + removed_count
                        t["synced_fingerprints"] = merged_fps
                        t["reverse_fingerprints"] = merged_rev_fps
                        t["fp_to_target_id"] = fp_to_target_id
                        t["last_message"] = final_msg
                        break
                self._save_tasks(tasks)

            if safety_warning:
                notifier.send(f"同步熔断预警 · {task_name}", final_msg, event="sync_error")
            elif total_added_this_run > 0 or removed_count > 0:
                notifier.send(f"定时同步完成 · {task_name}", final_msg, event="sync_success")

        except Exception as e:
            err_str = str(e) or e.__class__.__name__
            with self._lock:
                tasks = self._load_tasks()
                for t in tasks:
                    if t.get("id") == task_id:
                        t["last_run_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        t["next_run_ts"] = int(time.time()) + int(t.get("interval_minutes", 120)) * 60
                        t["last_status"] = "error"
                        t["last_message"] = f"同步出错: {err_str}"
                        break
                self._save_tasks(tasks)
            notifier.send(f"定时同步失败 · {task_name}", f"原因: {err_str}", event="sync_error")
        finally:
            with self._lock:
                self._running_task_ids.discard(task_id)


sync_scheduler = IncrementalSyncScheduler()
