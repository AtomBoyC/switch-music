from __future__ import annotations

import concurrent.futures
import re
import urllib.parse
import warnings
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")
try:
    from urllib3.exceptions import NotOpenSSLWarning  # type: ignore

    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
except Exception:
    pass

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.config import (
    PLATFORM_META,
    STATIC_DIR,
    harden_data_dir_permissions,
    is_allowed_host,
    is_allowed_origin,
)
from backend.csv_io import export_tracks_to_csv_string, parse_csv_tracks, parse_plain_text_tracks
from backend.deduplicator import analyze_playlist_duplicate_groups, deduplicate_source_tracks
from backend.matcher import match_cache, score_candidate
from backend.migration_engine import (
    apply_manual_match,
    cancel_job,
    clear_all_history,
    delete_history_item,
    get_history_list,
    get_job,
    recover_interrupted_jobs,
    start_migration_job,
    start_preview_job,
)
from backend.models import (
    DeduplicateTracksRequest,
    ExportCsvRequest,
    ManualApplyMatchRequest,
    ManualSearchRequest,
    MigrationRequest,
    PreviewMatchRequest,
    RawAuthPayload,
    RemoveDuplicatesRequest,
    SpotifyConfigPayload,
    SyncTaskCreateRequest,
    SyncTaskTogglePayload,
    TextImportPayload,
    UrlImportPayload,
    model_to_dict,
)
from backend.providers import (
    PROVIDERS,
    applemusic_provider,
    detect_platform_from_url,
    get_provider,
    kugou_provider,
    netease_provider,
    qqmusic_provider,
    spotify_provider,
    ytm_provider,
)
from backend.sync_scheduler import sync_scheduler

APP_VERSION = "2.1.0"


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    harden_data_dir_permissions()
    recover_interrupted_jobs()
    sync_scheduler.start()
    try:
        yield
    finally:
        sync_scheduler.stop()
        match_cache.flush()


app = FastAPI(
    title="Switch Music · 全平台歌单互转与去重中心",
    version=APP_VERSION,
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def local_security_guard(request: Request, call_next):
    """
    The server stores music-account cookies / OAuth tokens locally, so it must only be
    reachable from this machine's own UI:
      * Host header allow-list blocks DNS-rebinding attacks from malicious websites.
      * Origin check on state-changing requests blocks cross-site form/fetch CSRF.
    """
    if not is_allowed_host(request.headers.get("host", "")):
        return JSONResponse({"detail": "Forbidden host"}, status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not is_allowed_origin(request.headers.get("origin", "")):
            return JSONResponse({"detail": "Cross-origin request blocked"}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.get("/api/health")
def health():
    return {"status": "ok", "version": APP_VERSION}


# ---------------------------------------------------------------------------
# Web Entry
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Switch Music UI is being prepared...</h1>")
    return FileResponse(str(index_file))


# ---------------------------------------------------------------------------
# Unified Multi-Platform Connections & Playlists
# ---------------------------------------------------------------------------

@app.get("/api/platforms/status")
def all_platforms_status():
    results: Dict[str, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        fmap = {pid: pool.submit(prov.get_status) for pid, prov in PROVIDERS.items()}
        for pid, fut in fmap.items():
            try:
                results[pid] = {**PLATFORM_META[pid], **fut.result()}
            except Exception as e:
                results[pid] = {
                    **PLATFORM_META[pid],
                    "platform": pid,
                    "connected": False,
                    "message": str(e),
                }
    return {"platforms": results}


@app.post("/api/platforms/{platform_id}/auth")
def platform_save_cookie_auth(platform_id: str, payload: RawAuthPayload):
    raw = payload.headers_raw.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="请粘贴有效的 Copy as cURL 命令、请求头或 Cookie。")
    try:
        if platform_id == "ytm":
            return ytm_provider.save_auth(raw)
        if platform_id == "netease":
            return netease_provider.save_auth(raw)
        if platform_id == "qqmusic":
            return qqmusic_provider.save_auth(raw)
        if platform_id == "kugou":
            return kugou_provider.save_auth(raw)
        if platform_id == "applemusic":
            return applemusic_provider.save_auth(raw)
        raise HTTPException(status_code=400, detail=f"平台 {platform_id} 不使用 Cookie 方式认证。")
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"验证连接失败: {str(e)}")


@app.post("/api/platforms/kugou/qrcode")
def kugou_create_qrcode():
    try:
        return kugou_provider.create_login_qrcode()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"生成酷狗登录二维码失败: {str(e)}")


@app.get("/api/platforms/kugou/qrcode/{key}")
def kugou_check_qrcode(key: str):
    if not re.fullmatch(r"[0-9a-zA-Z]{8,128}", key or ""):
        raise HTTPException(status_code=400, detail="无效的二维码 key")
    try:
        return kugou_provider.check_login_qrcode(key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"检查扫码状态失败: {str(e)}")


@app.post("/api/platforms/{platform_id}/disconnect")
def platform_disconnect(platform_id: str):
    try:
        prov = get_provider(platform_id)
        return prov.disconnect()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/platforms/{platform_id}/playlists")
def platform_get_playlists(platform_id: str, include_liked: bool = True):
    try:
        prov = get_provider(platform_id)
        if platform_id == "ytm":
            playlists = ytm_provider.get_user_playlists(include_liked=include_liked)
        else:
            playlists = prov.get_user_playlists()
            if not include_liked:
                playlists = [p for p in playlists if not p.get("is_liked")]
        return {"platform": platform_id, "playlists": playlists}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"获取歌单列表失败: {str(e)}")


@app.get("/api/platforms/{platform_id}/playlist/{playlist_id:path}/tracks")
def platform_get_playlist_tracks(platform_id: str, playlist_id: str):
    try:
        prov = get_provider(platform_id)
        return prov.get_playlist_tracks(playlist_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"读取歌单曲目失败: {str(e)}")


# ---------------------------------------------------------------------------
# Universal Import (URL / CSV / Plain Text) & CSV Export
# ---------------------------------------------------------------------------

@app.post("/api/import/url")
def import_playlist_from_url(payload: UrlImportPayload):
    url_or_id = payload.url_or_id.strip()
    if not url_or_id:
        raise HTTPException(status_code=400, detail="请输入歌单分享链接或歌单 ID。")
    try:
        plat = payload.platform.strip().lower()
        if not plat or plat == "auto":
            plat = detect_platform_from_url(url_or_id)
        prov = get_provider(plat)
        data = prov.import_from_url(url_or_id)
        return {"platform": plat, **data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/import/text")
def import_playlist_from_text(payload: TextImportPayload):
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="请粘贴至少一行歌曲列表文本（如：晴天 - 周杰伦）。")
    parsed = parse_plain_text_tracks(payload.text, payload.playlist_name)
    if not parsed["tracks"]:
        raise HTTPException(status_code=400, detail="未能从文本中解析出任何有效歌曲。")
    return parsed


@app.post("/api/import/csv")
@app.post("/api/spotify/parse-csv")
async def parse_uploaded_csv(files: List[UploadFile] = File(...)):
    all_tracks: List[Dict[str, Any]] = []
    names: List[str] = []
    for f in files:
        content = await f.read()
        parsed = parse_csv_tracks(content, f.filename or "")
        if parsed["playlist_name"] and parsed["playlist_name"] not in names:
            names.append(parsed["playlist_name"])
        all_tracks.extend(parsed["tracks"])

    if not all_tracks:
        raise HTTPException(
            status_code=400,
            detail="未能从文件中解析出任何有效歌曲，请确认是否为有效的 CSV / TSV / JSON / 歌单文本文件。",
        )

    combined_name = " + ".join(names[:2]) if names else "Imported Playlist"
    return {
        "playlist_name": combined_name,
        "count": len(all_tracks),
        "tracks": all_tracks,
    }


def _csv_download_response(csv_text: str, playlist_name: str) -> Response:
    safe_ascii = re.sub(r"[^A-Za-z0-9._-]+", "_", playlist_name).strip("_") or "playlist"
    utf8_quoted = urllib.parse.quote(f"{playlist_name}.csv")
    headers = {
        "Content-Disposition": f"attachment; filename=\"{safe_ascii}.csv\"; filename*=UTF-8''{utf8_quoted}"
    }
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@app.post("/api/export/csv")
def export_tracks_csv(payload: ExportCsvRequest):
    if not payload.tracks:
        raise HTTPException(status_code=400, detail="没有可导出的歌曲数据。")
    csv_str = export_tracks_to_csv_string(payload.tracks)
    return _csv_download_response(csv_str, payload.playlist_name or "Switch_Music_Export")


@app.get("/api/platforms/{platform_id}/playlist/{playlist_id:path}/export-csv")
def export_platform_playlist_csv(platform_id: str, playlist_id: str):
    try:
        prov = get_provider(platform_id)
        data = prov.get_playlist_tracks(playlist_id)
        csv_str = export_tracks_to_csv_string(data.get("tracks") or [])
        return _csv_download_response(csv_str, data.get("playlist_name") or f"{platform_id}_playlist")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"导出歌单 CSV 失败: {str(e)}")


# ---------------------------------------------------------------------------
# Backward-Compatible YouTube Music Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/ytm/status")
def ytm_status():
    return ytm_provider.get_status()


@app.post("/api/ytm/auth")
def ytm_setup_auth(payload: RawAuthPayload):
    return platform_save_cookie_auth("ytm", payload)


@app.get("/api/ytm/playlists")
def ytm_get_playlists():
    try:
        return {"playlists": ytm_provider.get_user_playlists(include_liked=False)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ytm/playlist/{playlist_id}/duplicates")
def ytm_scan_playlist_duplicates(playlist_id: str, mode: str = "standard"):
    return platform_scan_playlist_duplicates("ytm", playlist_id, mode=mode)


@app.post("/api/ytm/playlist/{playlist_id}/remove-duplicates")
def ytm_remove_playlist_duplicates(playlist_id: str, payload: RemoveDuplicatesRequest):
    return platform_remove_playlist_duplicates("ytm", playlist_id, payload)


# ---------------------------------------------------------------------------
# Spotify OAuth Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/spotify/status")
def spotify_status():
    return spotify_provider.get_status()


@app.post("/api/spotify/config")
def spotify_save_config(payload: SpotifyConfigPayload):
    try:
        return spotify_provider.save_config(
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            redirect_uri=payload.redirect_uri,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/spotify/callback")
def spotify_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    if error:
        return HTMLResponse(f"<h3>Spotify 授权失败: {error}</h3><p><a href='/'>返回应用</a></p>")
    if not code:
        return RedirectResponse("/")
    auth_manager = spotify_provider.get_oauth(require_write=True)
    if not auth_manager:
        return HTMLResponse("<h3>未找到 Spotify 配置</h3><p><a href='/'>返回应用</a></p>")
    try:
        auth_manager.get_access_token(code, as_dict=False)
        return RedirectResponse("/?spotify_connected=1")
    except Exception as e:
        return HTMLResponse(f"<h3>获取 Spotify Token 失败: {str(e)}</h3><p><a href='/'>返回应用</a></p>")


@app.get("/api/spotify/playlists")
def spotify_playlists():
    try:
        return {"playlists": spotify_provider.get_user_playlists()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"拉取 Spotify 歌单列表失败: {str(e)}")


@app.get("/api/spotify/playlist/{playlist_id}/tracks")
def spotify_playlist_tracks(playlist_id: str):
    try:
        return spotify_provider.get_playlist_tracks(playlist_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"获取歌单曲目失败: {str(e)}")


# ---------------------------------------------------------------------------
# Deduplication (Source List & Any Platform Playlist)
# ---------------------------------------------------------------------------

@app.post("/api/tracks/deduplicate")
def api_deduplicate_source_tracks(payload: DeduplicateTracksRequest):
    return deduplicate_source_tracks(payload.tracks, mode=payload.mode)


@app.get("/api/platforms/{platform_id}/playlist/{playlist_id:path}/duplicates")
def platform_scan_playlist_duplicates(platform_id: str, playlist_id: str, mode: str = "standard"):
    try:
        prov = get_provider(platform_id)
        pl_title, raw_items = prov.get_dedupe_raw_items(playlist_id)
        return analyze_playlist_duplicate_groups(
            raw_items=raw_items,
            playlist_id=playlist_id,
            playlist_title=pl_title,
            mode=mode,
            platform=platform_id,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"扫描歌单重复曲目失败: {str(e)}")


@app.post("/api/platforms/{platform_id}/playlist/{playlist_id:path}/remove-duplicates")
def platform_remove_playlist_duplicates(
    platform_id: str,
    playlist_id: str,
    payload: RemoveDuplicatesRequest,
):
    try:
        prov = get_provider(platform_id)
        dict_items = [model_to_dict(it) for it in payload.items]
        removed = prov.remove_playlist_duplicates(playlist_id, dict_items)
        return {"success": True, "removed_count": removed}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"移除重复曲目失败: {str(e)}")


# ---------------------------------------------------------------------------
# Search, Preview Match, Migration & Manual Match Override
# ---------------------------------------------------------------------------

@app.post("/api/search/candidates")
def manual_search_candidates(payload: ManualSearchRequest):
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="请输入搜索关键词。")
    try:
        prov = get_provider(payload.platform)
        cands = prov.search_candidates(payload.query.strip(), limit=max(1, min(20, payload.limit)))
        if payload.source_track:
            enriched = []
            for idx, c in enumerate(cands):
                sc, conf, reason = score_candidate(payload.source_track, c, rank_idx=idx)
                enriched.append({**c, "score": sc, "confidence": conf, "match_reason": reason})
            cands = enriched
        return {"platform": payload.platform, "candidates": cands}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"搜索候选歌曲失败: {str(e)}")


@app.post("/api/migrate/preview")
def api_start_preview(req: PreviewMatchRequest):
    if not req.tracks:
        raise HTTPException(status_code=400, detail="待匹配的歌曲列表为空。")
    try:
        job_id = start_preview_job(req)
        return {"job_id": job_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/migrate/start")
def api_start_migration(req: MigrationRequest):
    if not req.tracks:
        raise HTTPException(status_code=400, detail="待迁移的歌曲列表为空。")
    try:
        job_id = start_migration_job(req)
        return {"job_id": job_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/migrate/status/{job_id}")
def api_get_migration_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="找不到该任务记录。")
    return job


@app.post("/api/migrate/cancel/{job_id}")
def api_cancel_migration(job_id: str):
    if not cancel_job(job_id):
        raise HTTPException(status_code=404, detail="找不到该任务记录。")
    return {"success": True}


@app.post("/api/migrate/manual-apply")
def api_manual_apply(req: ManualApplyMatchRequest):
    try:
        return apply_manual_match(req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"手动补录曲目失败: {str(e)}")


@app.delete("/api/cache/matches")
def api_clear_match_cache():
    cleared = match_cache.clear()
    return {"success": True, "cleared_count": cleared}


# ---------------------------------------------------------------------------
# History & Incremental Scheduled Sync
# ---------------------------------------------------------------------------

@app.get("/api/history")
def api_get_history():
    return {"history": get_history_list()}


@app.delete("/api/history/{job_id}")
def api_delete_history_item(job_id: str):
    delete_history_item(job_id)
    return {"success": True}


@app.delete("/api/history")
def api_clear_history():
    cleared = clear_all_history()
    return {"success": True, "cleared_count": cleared}


@app.get("/api/sync/tasks")
def api_list_sync_tasks():
    return {"tasks": sync_scheduler.list_tasks()}


@app.post("/api/sync/tasks")
def api_create_sync_task(req: SyncTaskCreateRequest):
    try:
        task = sync_scheduler.create_task(req)
        return {"success": True, "task": task}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.patch("/api/sync/tasks/{task_id}")
def api_toggle_sync_task(task_id: str, payload: SyncTaskTogglePayload):
    try:
        task = sync_scheduler.toggle_task(task_id, payload.enabled)
        return {"success": True, "task": task}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/sync/tasks/{task_id}/run")
def api_run_sync_task_now(task_id: str):
    try:
        return sync_scheduler.trigger_now(task_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/sync/tasks/{task_id}")
def api_delete_sync_task(task_id: str):
    sync_scheduler.delete_task(task_id)
    return {"success": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)
