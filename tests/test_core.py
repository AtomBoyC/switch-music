from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module
from backend.config import parse_cookie_and_headers
from backend.csv_io import export_tracks_to_csv_string, parse_csv_tracks, parse_plain_text_tracks
from backend.deduplicator import analyze_playlist_duplicate_groups, deduplicate_source_tracks
from backend.matcher import build_search_queries, score_candidate
from backend.models import TrackItem
from backend.providers import detect_platform_from_url
from backend.providers.netease import NetEaseProvider, aes128_cbc_encrypt, weapi_encrypt
from backend.providers.qqmusic import QQMusicProvider, calc_qq_gtk, extract_qq_uin_and_key
from backend.text_utils import clean_str, extract_version_tags, strip_noise_for_query, to_simplified


def _client() -> TestClient:
    # The app only accepts loopback Host headers (DNS-rebinding protection).
    return TestClient(app_module.app, base_url="http://127.0.0.1:8765")


class TestSwitchMusicCore(unittest.TestCase):
    def test_traditional_simplified_and_cleaning(self):
        self.assertEqual(to_simplified("周杰倫 - 髮如雪 (Live 演唱會)"), "周杰伦 - 发如雪 (Live 演唱会)")
        self.assertEqual(clean_str("晴天 (feat. Jay) [2021 Remastered]"), "晴天")
        self.assertEqual(strip_noise_for_query("Mojito (feat. 群星) - Remastered 2022"), "Mojito")

    def test_version_tag_detection_and_scoring(self):
        studio_track = TrackItem(title="晴天", artist="周杰伦", album="叶惠美", duration_ms=269000)

        studio_cand = {
            "track_id": "1",
            "title": "晴天",
            "artist": "周杰伦",
            "album": "叶惠美",
            "duration_seconds": 269,
            "resultType": "song",
        }
        karaoke_cand = {
            "track_id": "2",
            "title": "晴天 (伴奏版 Karaoke)",
            "artist": "伴奏大师",
            "album": "热门伴奏",
            "duration_seconds": 269,
            "resultType": "song",
        }
        unrelated_cand = {
            "track_id": "3",
            "title": "Despacito",
            "artist": "Luis Fonsi",
            "album": "Vida",
            "duration_seconds": 228,
            "resultType": "song",
        }

        s_studio, conf_studio, _ = score_candidate(studio_track, studio_cand, rank_idx=0)
        s_karaoke, conf_karaoke, _ = score_candidate(studio_track, karaoke_cand, rank_idx=0)
        s_unrel, conf_unrel, _ = score_candidate(studio_track, unrelated_cand, rank_idx=0)

        self.assertGreaterEqual(s_studio, 80)
        self.assertEqual(conf_studio, "high")
        self.assertLess(s_karaoke, 20)
        self.assertEqual(conf_karaoke, "unmatched")
        self.assertLess(s_unrel, 20)
        self.assertEqual(conf_unrel, "unmatched")
        self.assertIn("instrumental", extract_version_tags(karaoke_cand["title"]))

    def test_search_query_builder(self):
        tr = TrackItem(title="Love Story (Taylor's Version) [From The Vault]", artist="Taylor Swift, Colbie")
        queries = build_search_queries(tr)
        self.assertTrue(len(queries) >= 2)
        self.assertIn("Love Story Taylor Swift", queries)

    def test_aes128_cbc_matches_openssl(self):
        msg = '{"s":"周杰伦 七里香","type":1,"limit":6}'.encode("utf-8")
        key = b"0CoJUm6Qyw8W8jud"
        iv = b"0102030405060708"
        py_cipher = aes128_cbc_encrypt(msg, key, iv)
        proc = subprocess.run(
            ["/usr/bin/openssl", "enc", "-aes-128-cbc", "-K", key.hex(), "-iv", iv.hex()],
            input=msg,
            capture_output=True,
            check=True,
        )
        self.assertEqual(py_cipher, proc.stdout)
        enc = weapi_encrypt({"id": "123456", "n": 1000})
        self.assertEqual(len(enc["encSecKey"]), 256)
        self.assertTrue(len(enc["params"]) > 16)

    def test_cookie_and_platform_parsers(self):
        curl_str = (
            "curl 'https://music.163.com/weapi/user/playlist' "
            "-H 'Cookie: MUSIC_U=abcdef123456; __csrf=987654;' "
            "-H 'User-Agent: Mozilla/5.0'"
        )
        c_str, c_dict, _ = parse_cookie_and_headers(curl_str)
        self.assertEqual(c_dict["MUSIC_U"], "abcdef123456")
        self.assertEqual(c_dict["__csrf"], "987654")
        self.assertIn("MUSIC_U=", c_str)

        uin, key, ltype = extract_qq_uin_and_key({"uin": "o00889911", "qm_keyst": "Q_H_L_2xyz"})
        self.assertEqual(uin, "889911")
        self.assertEqual(key, "Q_H_L_2xyz")
        self.assertEqual(ltype, 2)
        self.assertGreater(calc_qq_gtk("Q_H_L_2xyz"), 0)

        self.assertEqual(detect_platform_from_url("分享歌单 https://music.163.com/#/playlist?id=998877"), "netease")
        self.assertEqual(detect_platform_from_url("https://y.qq.com/n/ryqq/playlist/8014914608"), "qqmusic")
        self.assertEqual(detect_platform_from_url("https://music.youtube.com/playlist?list=PL123"), "ytm")
        self.assertEqual(NetEaseProvider._extract_playlist_id("https://music.163.com/#/playlist?id=556677&userid=1"), "556677")
        self.assertEqual(QQMusicProvider._extract_disstid("https://y.qq.com/n/ryqq/playlist/8014914608"), "8014914608")

    def test_csv_and_plain_text_io(self):
        txt = "1. 晴天 - 周杰伦 (04:29)\n2、夜曲 - 周杰伦\n《稻香》 周杰伦"
        parsed = parse_plain_text_tracks(txt, "周董精选")
        self.assertEqual(parsed["count"], 3)
        self.assertEqual(parsed["tracks"][0]["title"], "晴天")
        self.assertEqual(parsed["tracks"][0]["artist"], "周杰伦")
        self.assertEqual(parsed["tracks"][0]["duration_ms"], 269000)

        csv_out = export_tracks_to_csv_string(parsed["tracks"])
        reparsed = parse_csv_tracks(csv_out.encode("utf-8"), "reimport.csv")
        self.assertEqual(reparsed["count"], 3)
        self.assertEqual(reparsed["tracks"][2]["title"], "稻香")

    def test_deduplicators(self):
        tracks = [
            TrackItem(title="髮如雪", artist="周杰倫", duration_ms=299000),
            TrackItem(title="发如雪 (Remastered)", artist="周杰伦", duration_ms=300000),
            TrackItem(title="夜曲", artist="周杰伦", duration_ms=226000),
        ]
        res = deduplicate_source_tracks(tracks, mode="standard")
        self.assertEqual(res["unique_count"], 2)
        self.assertEqual(res["removed_count"], 1)
        self.assertEqual(len(res["groups"]), 1)

        pl_items = [
            {"position": 1, "item_id": "v1", "can_remove": True, "title": "十年", "artist": "陈奕迅", "duration_seconds": 205},
            {"position": 2, "item_id": "v2", "can_remove": True, "title": "十年", "artist": "陳奕迅", "duration_seconds": 206},
        ]
        pl_res = analyze_playlist_duplicate_groups(pl_items, "pl1", "测试歌单", mode="standard", platform="netease")
        self.assertEqual(pl_res["groups_count"], 1)
        self.assertEqual(pl_res["duplicates_count"], 1)

    def test_fastapi_endpoints(self):
        with _client() as client:
            r_home = client.get("/")
            self.assertEqual(r_home.status_code, 200)
            self.assertIn("Switch Music", r_home.text)

            with patch.object(app_module.ytm_provider, "get_status", return_value={"connected": False}), \
                 patch.object(app_module.spotify_provider, "get_status", return_value={"connected": False}), \
                 patch.object(app_module.netease_provider, "get_status", return_value={"connected": False}), \
                 patch.object(app_module.qqmusic_provider, "get_status", return_value={"connected": False}), \
                 patch.object(app_module.kugou_provider, "get_status", return_value={"connected": False}), \
                 patch.object(app_module.applemusic_provider, "get_status", return_value={"connected": False}), \
                 patch.object(app_module.subsonic_provider, "get_status", return_value={"connected": False}), \
                 patch.object(app_module.qishui_provider, "get_status", return_value={"connected": False}):
                r_st = client.get("/api/platforms/status")
                self.assertEqual(r_st.status_code, 200)
                plats = r_st.json()["platforms"]
                self.assertEqual(
                    set(plats.keys()),
                    {"ytm", "spotify", "netease", "qqmusic", "kugou", "applemusic", "subsonic", "qishui"},
                )

            r_txt = client.post("/api/import/text", json={"text": "晴天 - 周杰伦\n七里香 - 周杰伦", "playlist_name": "测试"})
            self.assertEqual(r_txt.status_code, 200)
            self.assertEqual(r_txt.json()["count"], 2)

            r_exp = client.post("/api/export/csv", json={"playlist_name": "周杰伦歌单", "tracks": r_txt.json()["tracks"]})
            self.assertEqual(r_exp.status_code, 200)
            self.assertIn("Track Name", r_exp.text)

    def test_concurrent_migration_preserves_order_and_manual_backfill(self):
        import tempfile
        import time as _time
        from pathlib import Path
        from backend.providers.base import PlatformProvider

        added_batches = []

        class FakeTargetProvider(PlatformProvider):
            platform_id = "netease"
            platform_name = "网易云音乐"

            def get_status(self):
                return {"platform": "netease", "connected": True}

            def create_playlist(self, title, description="", privacy_status="PRIVATE"):
                return "pl_999"

            def build_playlist_url(self, playlist_id, target_mode="new_playlist"):
                return f"https://music.163.com/#/playlist?id={playlist_id}"

            def search_candidates(self, query, limit=6):
                # Deliberately make earlier tracks slower to verify sliding-window order preservation!
                if "Song 1" in query:
                    _time.sleep(0.08)
                elif "Unmatched" in query:
                    return []
                num = query.split()[1]
                return [
                    {
                        "platform": "netease",
                        "track_id": f"id_{num}",
                        "title": f"Song {num}",
                        "artist": "Artist",
                        "album": "Album",
                        "duration": "3:20",
                        "duration_seconds": 200,
                        "resultType": "song",
                        "url": f"https://music.163.com/#/song?id=id_{num}",
                    }
                ]

            def add_tracks(self, playlist_id, target_mode, candidates, seen_ids, skip_duplicates=True):
                ids = [c["track_id"] for c in candidates]
                added_batches.extend(ids)
                return len(ids)

        fake_prov = FakeTargetProvider()
        tracks_payload = [
            {"title": "Song 1", "artist": "Artist", "duration_ms": 200000},
            {"title": "Song 2", "artist": "Artist", "duration_ms": 200000},
            {"title": "UnmatchedXYZ", "artist": "Nobody", "duration_ms": 200000},
            {"title": "Song 4", "artist": "Artist", "duration_ms": 200000},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with patch("backend.migration_engine.get_provider", return_value=fake_prov), \
                 patch("backend.migration_engine.HISTORY_FILE", tmp_path / "history.json"), \
                 patch("backend.migration_engine.JOBS_DIR", tmp_path / "jobs"), \
                 patch("backend.matcher.MATCH_CACHE_FILE", tmp_path / "cache.json"):
                with _client() as client:
                    r_start = client.post(
                        "/api/migrate/start",
                        json={
                            "source_platform": "qqmusic",
                            "target_platform": "netease",
                            "target_mode": "new_playlist",
                            "playlist_title": "并发保序测试",
                            "concurrency": 4,
                            "use_cache": False,
                            "tracks": tracks_payload,
                        },
                    )
                    self.assertEqual(r_start.status_code, 200)
                    jid = r_start.json()["job_id"]

                    for _ in range(40):
                        st = client.get(f"/api/migrate/status/{jid}").json()
                        if st["status"] != "running":
                            break
                        _time.sleep(0.05)

                    self.assertEqual(st["status"], "completed")
                    self.assertEqual(st["matched_count"], 3)
                    self.assertEqual(st["unmatched_count"], 1)
                    # Verify exact order preserved despite Song 1 sleeping longer!
                    self.assertEqual(added_batches, ["id_1", "id_2", "id_4"])

                    # Now test manual backfill on unmatched track index 2
                    r_manual = client.post(
                        "/api/migrate/manual-apply",
                        json={
                            "target_platform": "netease",
                            "target_mode": "existing_playlist",
                            "playlist_id": "pl_999",
                            "candidate": {
                                "platform": "netease",
                                "track_id": "id_manual_3",
                                "title": "Manual Song 3",
                                "artist": "Artist",
                                "duration": "3:20",
                            },
                            "job_id": jid,
                            "result_index": 2,
                        },
                    )
                    self.assertEqual(r_manual.status_code, 200)
                    st_after = client.get(f"/api/migrate/status/{jid}").json()
                    self.assertEqual(st_after["matched_count"], 4)
                    self.assertEqual(st_after["unmatched_count"], 0)

    def test_sync_scheduler_crud(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("backend.sync_scheduler.SYNC_TASKS_FILE", Path(tmpdir) / "sync_tasks.json"):
                with _client() as client:
                    r_create = client.post(
                        "/api/sync/tasks",
                        json={
                            "name": "测试同步规则",
                            "source_platform": "netease",
                            "source_playlist_id": "12345",
                            "target_platform": "qqmusic",
                            "target_mode": "liked_songs",
                            "interval_minutes": 60,
                        },
                    )
                    self.assertEqual(r_create.status_code, 200)
                    tid = r_create.json()["task"]["id"]

                    r_toggle = client.patch(f"/api/sync/tasks/{tid}", json={"enabled": False})
                    self.assertEqual(r_toggle.status_code, 200)
                    self.assertFalse(r_toggle.json()["task"]["enabled"])

                    r_del = client.delete(f"/api/sync/tasks/{tid}")
                    self.assertEqual(r_del.status_code, 200)

    def test_frontend_syntax_and_dom_wiring(self):
        import os
        import re
        from backend.config import STATIC_DIR

        html_path = STATIC_DIR / "index.html"
        i18n_path = STATIC_DIR / "js" / "i18n.js"
        js_path = STATIC_DIR / "js" / "app.js"
        css_path = STATIC_DIR / "css" / "styles.css"

        self.assertTrue(html_path.exists())
        self.assertTrue(i18n_path.exists())
        self.assertTrue(js_path.exists())
        self.assertTrue(css_path.exists())

        jsc_bin = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
        if os.path.exists(jsc_bin):
            for script_file in (i18n_path, js_path):
                proc = subprocess.run(
                    [
                        jsc_bin,
                        "-e",
                        f"new Function(readFile('{script_file.as_posix()}')); print('JS_SYNTAX_OK');",
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(proc.returncode, 0, f"JS syntax error in {script_file}: {proc.stdout} {proc.stderr}")
                self.assertIn("JS_SYNTAX_OK", proc.stdout)

        html_text = html_path.read_text(encoding="utf-8")
        i18n_text = i18n_path.read_text(encoding="utf-8")
        js_text = js_path.read_text(encoding="utf-8")
        combined_js = i18n_text + "\n" + js_text

        # 1. Every literal getElementById('xyz') in JS must exist in index.html or dynamic JS templates
        html_ids = set(re.findall(r'\bid=["\']([^"\']+)["\']', html_text))
        dynamic_js_ids = set(re.findall(r'\bid=["\']([^"\']+)["\']', combined_js))
        all_known_ids = html_ids | dynamic_js_ids
        referenced_ids = set(re.findall(r"getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)", combined_js))
        missing_ids = referenced_ids - all_known_ids
        self.assertEqual(missing_ids, set(), f"Missing DOM IDs referenced in JS: {missing_ids}")

        # 2. Every inline handler function in index.html must exist in JS
        js_funcs = set(re.findall(r"(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(", combined_js))
        inline_calls = set(
            re.findall(r'\bon(?:click|change|input|keydown|submit)=["\']([A-Za-z0-9_]+)\s*\(', html_text)
        )
        builtin_globals = {"if", "event", "window", "document", "alert", "confirm"}
        missing_funcs = (inline_calls - js_funcs) - builtin_globals
        self.assertEqual(missing_funcs, set(), f"Missing JS functions referenced in index.html: {missing_funcs}")


class TestReliabilityAndSecurity(unittest.TestCase):
    """v2.1: pipeline resilience, ordered writer, crash recovery and local-server hardening."""

    def _isolated_paths(self, tmp_path):
        return [
            patch("backend.migration_engine.HISTORY_FILE", tmp_path / "history.json"),
            patch("backend.migration_engine.JOBS_DIR", tmp_path / "jobs"),
            patch("backend.matcher.MATCH_CACHE_FILE", tmp_path / "cache.json"),
        ]

    def test_host_and_origin_guard(self):
        from backend.config import is_allowed_host, is_allowed_origin

        self.assertTrue(is_allowed_host("127.0.0.1:8765"))
        self.assertTrue(is_allowed_host("localhost:8765"))
        self.assertTrue(is_allowed_host("[::1]:8765"))
        self.assertFalse(is_allowed_host("evil.example.com"))
        self.assertFalse(is_allowed_host("127.0.0.1.evil.com:8765"))
        self.assertTrue(is_allowed_origin(""))
        self.assertTrue(is_allowed_origin("http://127.0.0.1:8765"))
        self.assertFalse(is_allowed_origin("https://evil.example.com"))
        self.assertFalse(is_allowed_origin("null"))

        with _client() as client:
            self.assertEqual(client.get("/api/health").status_code, 200)
            # DNS rebinding: foreign Host header must be rejected
            r_host = client.get("/api/health", headers={"host": "attacker.example.com"})
            self.assertEqual(r_host.status_code, 403)
            # CSRF: cross-site POST must be rejected, same-origin POST allowed
            payload = {"text": "晴天 - 周杰伦", "playlist_name": "x"}
            r_evil = client.post("/api/import/text", json=payload, headers={"origin": "https://evil.example.com"})
            self.assertEqual(r_evil.status_code, 403)
            r_ok = client.post("/api/import/text", json=payload, headers={"origin": "http://127.0.0.1:8765"})
            self.assertEqual(r_ok.status_code, 200)
            self.assertEqual(r_ok.headers.get("x-frame-options"), "DENY")

    def test_deployment_options_password_and_hosts(self):
        """Docker/server mode: optional password, extra allowed hosts, wildcard never opens CSRF."""
        import base64
        from backend import config as cfg

        with patch.object(app_module, "ACCESS_PASSWORD", "s3cret"), _client() as client:
            self.assertEqual(client.get("/api/health").status_code, 200)  # healthcheck stays open
            r = client.get("/")
            self.assertEqual(r.status_code, 401)
            self.assertIn("Basic", r.headers.get("www-authenticate", ""))
            bad = base64.b64encode(b"any:wrong").decode()
            self.assertEqual(client.get("/", headers={"authorization": f"Basic {bad}"}).status_code, 401)
            good = base64.b64encode(b"whoever:s3cret").decode()
            self.assertEqual(client.get("/", headers={"authorization": f"Basic {good}"}).status_code, 200)

        with patch.object(cfg, "ALLOW_ANY_HOST", True):
            self.assertTrue(cfg.is_allowed_host("music.example.com"))
            # Wildcard host must not make foreign origins acceptable...
            self.assertFalse(cfg.is_allowed_origin("https://evil.example.com", "music.example.com"))
            # ...while same-origin requests on the deployment host are fine.
            self.assertTrue(cfg.is_allowed_origin("https://music.example.com", "music.example.com"))

        with patch.object(cfg, "ALLOWED_HOSTS", cfg.ALLOWED_HOSTS | {"192.168.1.10"}):
            self.assertTrue(cfg.is_allowed_host("192.168.1.10:8765"))
            self.assertTrue(cfg.is_allowed_origin("http://192.168.1.10:8765"))

    def test_private_file_permissions(self):
        import os
        import stat
        import tempfile
        from pathlib import Path
        from backend.config import write_json_file

        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "secret.json"
            write_json_file(p, {"MUSIC_U": "x"})
            mode = stat.S_IMODE(os.stat(p).st_mode)
            self.assertEqual(mode, 0o600)

    def test_search_errors_do_not_stall_pipeline_and_write_failures_are_recorded(self):
        import tempfile
        import time as _time
        from contextlib import ExitStack
        from pathlib import Path
        from backend import migration_engine
        from backend.models import MigrationRequest
        from backend.providers.base import PlatformProvider

        written = []

        class FlakyProvider(PlatformProvider):
            platform_id = "netease"
            platform_name = "网易云音乐"

            def get_status(self):
                return {"platform": "netease", "connected": True}

            def create_playlist(self, title, description="", privacy_status="PRIVATE"):
                return "pl_1"

            def search_candidates(self, query, limit=6):
                if "Broken" in query:
                    raise ConnectionError("HTTP 429 Too Many Requests")
                num = query.split()[1]
                return [{
                    "platform": "netease", "track_id": f"id_{num}", "title": f"Song {num}",
                    "artist": "Artist", "duration_seconds": 200, "resultType": "song",
                }]

            def add_tracks(self, playlist_id, target_mode, candidates, seen_ids, skip_duplicates=True):
                ids = [c["track_id"] for c in candidates]
                if "id_13" in ids:
                    raise RuntimeError("playlist write rejected")
                written.extend(ids)
                return len(ids)

        tracks = []
        for i in range(1, 31):
            title = "Broken Song" if i == 2 else f"Song {i}"
            tracks.append({"title": title, "artist": "Artist", "duration_ms": 200000})

        with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
            tmp_path = Path(tmpdir)
            (tmp_path / "jobs").mkdir()
            for p in self._isolated_paths(tmp_path):
                stack.enter_context(p)
            stack.enter_context(patch("backend.migration_engine.get_provider", return_value=FlakyProvider()))
            stack.enter_context(patch("backend.migration_engine.WRITE_RETRY_BACKOFF_SECONDS", 0.01))
            stack.enter_context(patch("backend.migration_engine.WRITE_BATCH_SIZE", 10))

            req = MigrationRequest(
                source_platform="csv", target_platform="netease", target_mode="new_playlist",
                playlist_title="t", concurrency=4, use_cache=False, tracks=tracks,
            )
            jid = migration_engine.start_migration_job(req)
            for _ in range(200):
                job = migration_engine.get_job(jid)
                if job["status"] != "running":
                    break
                _time.sleep(0.05)

            self.assertEqual(job["status"], "completed")
            # Every track committed despite the exception on track #2 (no stalled window)
            self.assertEqual(len(job["results"]), 30)
            self.assertEqual(job["results"][1]["status"], "error")
            self.assertEqual(job["error_count"], 1)
            self.assertEqual(job["matched_count"], 29)
            # Batch containing id_13 failed after retries -> recorded, other batches still written in order
            self.assertEqual(job["write_failed_count"], 10)
            self.assertTrue(job["results"][12]["write_failed"])
            expected_order = [f"id_{i}" for i in range(1, 31) if i != 2]
            failed_batch = expected_order[10:20]
            self.assertIn("id_13", failed_batch)
            self.assertEqual(written, [x for x in expected_order if x not in failed_batch])
            # Failed rows are retryable
            self.assertEqual(len(job["unmatched_tracks"]), 11)

    def test_interrupted_job_recovery(self):
        import tempfile
        from contextlib import ExitStack
        from pathlib import Path
        from backend import migration_engine
        from backend.config import read_json_file, write_json_file

        with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
            tmp_path = Path(tmpdir)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()
            for p in self._isolated_paths(tmp_path):
                stack.enter_context(p)

            src = [{"title": f"S{i}", "artist": "A"} for i in range(5)]
            write_json_file(jobs_dir / "job_dead1.json", {
                "job_id": "dead1", "job_type": "migrate", "status": "running",
                "results": [{"index": 1, "track_index": 0}, {"index": 2, "track_index": 1}],
            })
            write_json_file(jobs_dir / "job_dead1_tracks.json", src)

            self.assertEqual(migration_engine.recover_interrupted_jobs(), 1)
            job = read_json_file(jobs_dir / "job_dead1.json", {})
            self.assertEqual(job["status"], "interrupted")
            self.assertEqual(job["pending_count"], 3)
            self.assertEqual([t["title"] for t in job["pending_tracks"]], ["S2", "S3", "S4"])
            history = read_json_file(tmp_path / "history.json", [])
            self.assertEqual(history[0]["status"], "interrupted")

    def test_existing_ids_failure_aborts_instead_of_hanging(self):
        """Reading the target playlist for duplicate protection fails -> job fails cleanly, nothing written."""
        import tempfile
        import time as _time
        from contextlib import ExitStack
        from pathlib import Path
        from backend import migration_engine
        from backend.models import MigrationRequest
        from backend.providers.base import PlatformProvider

        written = []

        class ExpiredLoginProvider(PlatformProvider):
            platform_id = "netease"
            platform_name = "网易云音乐"

            def get_status(self):
                return {"platform": "netease", "connected": True}

            def get_existing_track_ids(self, playlist_id, target_mode="existing_playlist"):
                raise PermissionError("cookie expired")

            def add_tracks(self, playlist_id, target_mode, candidates, seen_ids, skip_duplicates=True):
                written.extend(candidates)
                return len(candidates)

        with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
            tmp_path = Path(tmpdir)
            (tmp_path / "jobs").mkdir()
            for p in self._isolated_paths(tmp_path):
                stack.enter_context(p)
            stack.enter_context(patch("backend.migration_engine.get_provider", return_value=ExpiredLoginProvider()))
            req = MigrationRequest(
                source_platform="csv", target_platform="netease", target_mode="existing_playlist",
                existing_playlist_id="pl_9", use_cache=False,
                tracks=[{"title": f"S{i}", "artist": "A"} for i in range(3)],
            )
            jid = migration_engine.start_migration_job(req)
            for _ in range(100):
                job = migration_engine.get_job(jid)
                if job["status"] != "running":
                    break
                _time.sleep(0.05)
            self.assertEqual(job["status"], "failed")
            self.assertIn("cookie expired", job["error"])
            self.assertEqual(job["pending_count"], 3)
            self.assertEqual(written, [])
            _time.sleep(0.3)  # let the worker finish its final checkpoint before the temp dir is removed


class TestKugouAndAppleMusic(unittest.TestCase):
    def test_platform_detection(self):
        self.assertEqual(detect_platform_from_url("https://www.kugou.com/songlist/gcid_3z15kqlufz87z048/"), "kugou")
        self.assertEqual(detect_platform_from_url("collection_3_2132029040_287_0"), "kugou")
        self.assertEqual(detect_platform_from_url("https://music.apple.com/cn/playlist/x/pl.abc123"), "applemusic")
        self.assertEqual(detect_platform_from_url("https://apple.co/3xyz"), "applemusic")

    def test_kugou_gcid_decoding(self):
        from backend.providers.kugou import decode_kugou_gcid

        # Verified against kugou.com pages (share code -> global_collection_id)
        self.assertEqual(decode_kugou_gcid("gcid_3z15kqlufz87z048"), "collection_3_2132029040_287_0")
        self.assertEqual(decode_kugou_gcid("gcid_3z15kqv21zi8z0a3"), "collection_3_2132040296_638_0")
        self.assertEqual(decode_kugou_gcid("gcid_3zmhxisrz4tz089"), "collection_3_1182429807_169_0")
        self.assertIsNone(decode_kugou_gcid("gcid_bogus"))

    def test_kugou_signature_and_parsing(self):
        import hashlib
        from backend.providers.kugou import KugouProvider, _split_kugou_name, kugou_android_signature

        params = {"b": 2, "a": "x", "clienttime": 100}
        expected = hashlib.md5(
            b"OIlwieks28dk2k092lksi2UIkpa=xb=2clienttime=100{\"k\":1}OIlwieks28dk2k092lksi2UIkp"
        ).hexdigest()
        self.assertEqual(kugou_android_signature(params, '{"k":1}'), expected)

        self.assertEqual(_split_kugou_name("周杰伦 - 晴天", "周杰伦"), ("晴天", "周杰伦"))
        self.assertEqual(_split_kugou_name("A - B - C", ""), ("B - C", "A"))

        self.assertEqual(KugouProvider._extract_token_userid('{"token": "abc123", "userid": 42}'), ("abc123", "42"))
        tok, uid = KugouProvider._extract_token_userid("KuGoo=KugooID=778899&t=deadbeef&a_id=1014")
        self.assertEqual((tok, uid), ("deadbeef", "778899"))
        self.assertEqual(KugouProvider._parse_compound_id("lid_5|gid_collection_3_1_5_0"), (5, "collection_3_1_5_0"))

    def test_apple_music_url_parsing(self):
        from backend.providers.applemusic import AppleMusicProvider

        p = AppleMusicProvider._parse_url
        self.assertEqual(
            p("https://music.apple.com/cn/playlist/%E7%B2%BE%E9%80%89/pl.f4d106fed2bd41149aaacabb233eb5eb"),
            ("playlist", "pl.f4d106fed2bd41149aaacabb233eb5eb", "cn"),
        )
        # Album named with digits must not be mistaken for the album id
        self.assertEqual(
            p("https://music.apple.com/us/album/1989/1440935467?i=1440935471"), ("album", "1440935467", "us")
        )
        self.assertEqual(p("https://music.apple.com/library/playlist/p.AbCdEf123"), ("library_playlist", "p.AbCdEf123", ""))
        self.assertEqual(p("pl.u-AbCd123"), ("playlist", "pl.u-AbCd123", ""))
        with self.assertRaises(ValueError):
            p("https://example.com/nothing")


class TestV23EcosystemUpgrade(unittest.TestCase):
    """v2.3: Subsonic/Navidrome, Qishui Music, M3U8/JSON IO, Mirror/2-Way Sync, Push Notifier & Cache Inspector."""

    def test_subsonic_provider_auth_playlists_search_and_dedupe(self):
        import hashlib
        import tempfile
        from pathlib import Path
        from backend.providers.subsonic import SubsonicProvider, make_subsonic_auth_params, normalize_subsonic_url

        self.assertEqual(normalize_subsonic_url("http://192.168.1.10:4533/rest/"), "http://192.168.1.10:4533")
        with self.assertRaises(ValueError):
            normalize_subsonic_url("ftp://bad-host")

        params = make_subsonic_auth_params("alice", "s3cr3t", salt="abc123")
        self.assertEqual(params["u"], "alice")
        self.assertEqual(params["s"], "abc123")
        self.assertEqual(params["t"], hashlib.md5(b"s3cr3tabc123").hexdigest())

        prov = SubsonicProvider()
        recorded_calls = []

        def fake_request(endpoint, params=None, creds=None, method="GET"):
            recorded_calls.append((endpoint, params, method))
            if endpoint == "ping":
                return {"status": "ok", "type": "navidrome", "serverVersion": "0.53.3"}
            if endpoint == "getPlaylists":
                return {
                    "status": "ok",
                    "playlists": {
                        "playlist": [
                            {"id": "pl_sub_1", "name": "Hi-Res Jazz", "songCount": 2, "owner": "alice"},
                            {"id": "pl_other", "name": "Readonly Shared", "songCount": 5, "owner": "bob"},
                        ]
                    },
                }
            if endpoint == "getPlaylist":
                return {
                    "status": "ok",
                    "playlist": {
                        "id": "pl_sub_1",
                        "name": "Hi-Res Jazz",
                        "entry": [
                            {
                                "id": "tr_1",
                                "title": "Blue in Green",
                                "artists": [{"name": "Miles Davis"}, {"name": "Bill Evans"}],
                                "album": "Kind of Blue",
                                "duration": 337,
                                "isrc": ["USSM15900113"],
                                "path": "Jazz/Miles Davis/03 - Blue in Green.flac",
                            },
                            {
                                "id": "tr_1",
                                "title": "Blue in Green",
                                "artist": "Miles Davis",
                                "album": "Kind of Blue",
                                "duration": 337,
                                "path": "Jazz/Miles Davis/03 - Blue in Green.flac",
                            },
                        ],
                    },
                }
            if endpoint == "search3":
                return {
                    "status": "ok",
                    "searchResult3": {
                        "song": [
                            {
                                "id": "tr_99",
                                "title": "晴天",
                                "artist": "周杰伦",
                                "album": "叶惠美",
                                "duration": 269,
                            }
                        ]
                    },
                }
            if endpoint == "createPlaylist":
                return {"status": "ok", "playlist": {"id": "pl_new_7"}}
            if endpoint in ("updatePlaylist", "star"):
                return {"status": "ok"}
            raise AssertionError(f"Unexpected endpoint {endpoint}")

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "subsonic_auth.json"
            with patch("backend.providers.subsonic.SUBSONIC_AUTH_FILE", auth_file), \
                 patch.object(prov, "_request", side_effect=fake_request):
                saved = prov.save_config("http://10.0.0.5:4533/", "alice", "my_pass")
                self.assertTrue(saved["connected"])
                self.assertIn("navidrome", saved["user_name"])

                st = prov.get_status()
                self.assertTrue(st["connected"])
                self.assertTrue(st["has_password"])
                self.assertNotIn("my_pass", str(st))

                pls = prov.get_user_playlists()
                self.assertEqual(pls[0]["id"], "STARRED")
                self.assertEqual(pls[1]["id"], "pl_sub_1")
                self.assertTrue(pls[1]["editable"])
                self.assertFalse(pls[2]["editable"])

                pl_data = prov.get_playlist_tracks("pl_sub_1")
                self.assertEqual(pl_data["count"], 2)
                self.assertEqual(pl_data["tracks"][0]["isrc"], "USSM15900113")
                self.assertEqual(pl_data["tracks"][0]["artist"], "Miles Davis, Bill Evans")
                self.assertEqual(pl_data["tracks"][0]["extra"]["path"], "Jazz/Miles Davis/03 - Blue in Green.flac")

                cands = prov.search_candidates("晴天 周杰伦")
                self.assertEqual(cands[0]["track_id"], "tr_99")

                new_pid = prov.create_playlist("New NAS List", "desc", "PRIVATE")
                self.assertEqual(new_pid, "pl_new_7")

                added = prov.add_tracks("pl_new_7", "new_playlist", cands, set())
                self.assertEqual(added, 1)

                removed = prov.remove_playlist_duplicates(
                    "pl_sub_1",
                    [{"item_id": "tr_1", "extra": {"index": 1, "song_id": "tr_1"}}],
                )
                self.assertEqual(removed, 1)
                update_calls = [c for c in recorded_calls if c[0] == "updatePlaylist"]
                self.assertTrue(any(("songIndexToRemove", "1") in list(c[1]) for c in update_calls))

    def test_qishui_url_detection_and_html_parsers(self):
        from backend.providers.qishui import parse_qishui_html

        self.assertEqual(detect_platform_from_url("来看看歌单 https://qishui.douyin.com/s/iRNB7xYz/ 吧"), "qishui")
        self.assertEqual(
            detect_platform_from_url("https://music.douyin.com/qishui/share/playlist?playlist_id=7291827364512345678"),
            "qishui",
        )

        # Case 1: SSR _ROUTER_DATA JSON
        ssr_html = """
        <html><head><title>汽水音乐</title></head><body>
        <script>window._ROUTER_DATA = {"loaderData":{"playlist_page":{"playlistInfo":{"name":"深夜电台精选"},"trackList":[{"id":"qs_1","name":"兰亭序","artists":[{"name":"周杰伦"}],"album":{"name":"魔杰座"},"duration":253000},{"id":"qs_2","name":"稻香","artistName":"周杰伦","albumName":"魔杰座","duration":223}]}}};</script>
        </body></html>
        """
        res_ssr = parse_qishui_html(ssr_html)
        self.assertEqual(res_ssr["playlist_name"], "深夜电台精选")
        self.assertEqual(res_ssr["count"], 2)
        self.assertEqual(res_ssr["tracks"][0]["title"], "兰亭序")
        self.assertEqual(res_ssr["tracks"][0]["artist"], "周杰伦")
        self.assertEqual(res_ssr["tracks"][0]["duration_ms"], 253000)
        self.assertEqual(res_ssr["tracks"][1]["duration_ms"], 223000)

        # Case 2: Fallback HTML <p> pair structure ("Title" + "Artist • Album")
        fallback_html = """
        <html><head><title>开车兜风歌单 - 汽水音乐</title></head><body>
        <h1><p>开车兜风歌单</p></h1>
        <div><p>晴天</p><p>周杰伦 • 叶惠美</p></div>
        <div><p>Blinding Lights</p><p>The Weeknd • After Hours</p></div>
        </body></html>
        """
        res_fb = parse_qishui_html(fallback_html)
        self.assertEqual(res_fb["playlist_name"], "开车兜风歌单")
        self.assertEqual(res_fb["count"], 2)
        self.assertEqual(res_fb["tracks"][0]["album"], "叶惠美")
        self.assertEqual(res_fb["tracks"][1]["artist"], "The Weeknd")

    def test_m3u8_and_json_import_export_endpoints(self):
        m3u_content = (
            "#EXTM3U\n"
            "#PLAYLIST:NAS 无损精选\n"
            "#EXTINF:269,周杰伦 - 晴天\n"
            "Pop/JayChou/晴天.flac\n"
            "#EXTINF:200,Taylor Swift - Lover\n"
            "Pop/Taylor/Lover.flac\n"
        )
        with _client() as client:
            r_up = client.post(
                "/api/import/csv",
                files=[("files", ("nas_favs.m3u8", m3u_content.encode("utf-8"), "audio/x-mpegurl"))],
            )
            self.assertEqual(r_up.status_code, 200)
            up_data = r_up.json()
            self.assertEqual(up_data["playlist_name"], "NAS 无损精选")
            self.assertEqual(up_data["count"], 2)
            self.assertEqual(up_data["tracks"][0]["title"], "晴天")
            self.assertEqual(up_data["tracks"][0]["artist"], "周杰伦")
            self.assertEqual(up_data["tracks"][0]["duration_ms"], 269000)
            self.assertEqual(up_data["tracks"][0]["extra"]["path"], "Pop/JayChou/晴天.flac")

            # Export back to M3U8 preserving relative NAS path
            r_m3u = client.post(
                "/api/export/m3u8",
                json={"playlist_name": "NAS 无损精选", "tracks": up_data["tracks"]},
            )
            self.assertEqual(r_m3u.status_code, 200)
            self.assertIn("#EXTM3U", r_m3u.text)
            self.assertIn("#PLAYLIST:NAS 无损精选", r_m3u.text)
            self.assertIn("Pop/JayChou/晴天.flac", r_m3u.text)

            # Export portable JSON and re-import via /api/import/csv
            r_json = client.post(
                "/api/export/json",
                json={"playlist_name": "JSON 备份测试", "tracks": up_data["tracks"]},
            )
            self.assertEqual(r_json.status_code, 200)
            r_reimport = client.post(
                "/api/import/csv",
                files=[("files", ("backup.json", r_json.content, "application/json"))],
            )
            self.assertEqual(r_reimport.status_code, 200)
            self.assertEqual(r_reimport.json()["count"], 2)

    def test_sync_mirror_safety_breakers_and_two_way_echo_free_merge(self):
        import tempfile
        from pathlib import Path
        from backend.models import SyncTaskCreateRequest
        from backend.providers.base import PlatformProvider
        from backend.sync_scheduler import IncrementalSyncScheduler

        class InMemoryPlatform(PlatformProvider):
            def __init__(self, pid: str, name: str, initial_tracks: list):
                self.platform_id = pid
                self.platform_name = name
                # Each entry: (id, title, artist)
                self.store = list(initial_tracks)

            def get_status(self):
                return {"platform": self.platform_id, "connected": True}

            def get_user_playlists(self):
                return [{"id": "pl_1", "name": "Test Playlist", "count": len(self.store), "editable": True}]

            def get_playlist_tracks(self, playlist_id: str):
                return {
                    "playlist_name": "Test Playlist",
                    "count": len(self.store),
                    "tracks": [
                        {
                            "title": title,
                            "artist": artist,
                            "album": "",
                            "duration_ms": 200000,
                            "source_platform": self.platform_id,
                            "source_id": tid,
                        }
                        for tid, title, artist in self.store
                    ],
                }

            def get_existing_track_ids(self, playlist_id: str, target_mode: str = "existing_playlist"):
                return {tid for tid, _, _ in self.store}

            def search_candidates(self, query: str, limit: int = 6):
                q_low = query.lower()
                # Deterministic catalog mapping across platforms
                catalog = [
                    ("cat_1", "Song One", "Artist A"),
                    ("cat_2", "Song Two", "Artist B"),
                    ("cat_3", "Song Three", "Artist C"),
                    ("cat_4", "Song Four", "Artist D"),
                    ("cat_5", "Song Five", "Artist E"),
                ]
                out = []
                for cid, title, artist in catalog:
                    if title.lower() in q_low:
                        out.append(
                            {
                                "platform": self.platform_id,
                                "track_id": f"{self.platform_id}_{cid}",
                                "title": title,
                                "artist": artist,
                                "album": "",
                                "duration_seconds": 200,
                                "resultType": "song",
                            }
                        )
                return out

            def add_tracks(self, playlist_id, target_mode, candidates, seen_ids, skip_duplicates=True):
                added = 0
                for c in candidates:
                    tid = c["track_id"]
                    if skip_duplicates and tid in seen_ids:
                        continue
                    seen_ids.add(tid)
                    self.store.append((tid, c["title"], c["artist"]))
                    added += 1
                return added

            def get_dedupe_raw_items(self, playlist_id: str):
                items = [
                    {
                        "position": idx + 1,
                        "item_id": tid,
                        "videoId": tid,
                        "setVideoId": f"sv_{idx}",
                        "can_remove": True,
                        "title": title,
                        "artist": artist,
                        "extra": {"idx": idx},
                    }
                    for idx, (tid, title, artist) in enumerate(self.store)
                ]
                return "Test Playlist", items

            def remove_playlist_duplicates(self, playlist_id: str, items: list):
                remove_ids = {it["item_id"] for it in items}
                before = len(self.store)
                self.store = [row for row in self.store if row[0] not in remove_ids]
                return before - len(self.store)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            src_p = InMemoryPlatform(
                "spotify",
                "Spotify",
                [
                    ("sp_1", "Song One", "Artist A"),
                    ("sp_2", "Song Two", "Artist B"),
                    ("sp_3", "Song Three", "Artist C"),
                    ("sp_4", "Song Four", "Artist D"),
                ],
            )
            tgt_p = InMemoryPlatform("ytm", "YouTube Music", [])
            prov_map = {"spotify": src_p, "ytm": tgt_p}

            with patch("backend.sync_scheduler.SYNC_TASKS_FILE", tmp_path / "sync.json"), \
                 patch("backend.matcher.MATCH_CACHE_FILE", tmp_path / "cache.json"), \
                 patch("backend.sync_scheduler.get_provider", side_effect=lambda pid: prov_map[pid]), \
                 patch("backend.sync_scheduler.notifier.send") as mock_notify:
                sched = IncrementalSyncScheduler()

                # --- Part A: Mirror Sync + Safety Breakers ---
                t_mirror = sched.create_task(
                    SyncTaskCreateRequest(
                        name="Mirror Test",
                        source_platform="spotify",
                        source_playlist_id="pl_1",
                        target_platform="ytm",
                        target_mode="existing_playlist",
                        target_playlist_id="pl_1",
                        sync_mode="mirror",
                        max_remove_ratio=0.35,
                    )
                )
                mid = t_mirror["id"]

                # Run 1: Syncs all 4 tracks into target
                sched._execute_task(mid)
                self.assertEqual(len(tgt_p.store), 4)

                # Remove 1 of 4 tracks (25% <= 35% max_remove_ratio) -> allowed!
                src_p.store.pop(0)  # removes Song One
                sched._execute_task(mid)
                self.assertEqual(len(tgt_p.store), 3)
                self.assertNotIn("ytm_cat_1", {x[0] for x in tgt_p.store})

                # Remove 2 of remaining 3 tracks (66.7% > 35% max_remove_ratio) -> CIRCUIT BREAKER TRIPS!
                saved_store = list(src_p.store)
                src_p.store = [saved_store[0]]
                sched._execute_task(mid)
                self.assertEqual(len(tgt_p.store), 3)  # Nothing deleted!
                st_after_trip = [x for x in sched.list_tasks() if x["id"] == mid][0]
                self.assertEqual(st_after_trip["last_status"], "error")
                self.assertIn("防误删熔断", st_after_trip["last_message"])

                # Empty snapshot (0 tracks) -> EMPTY-SNAPSHOT GUARD TRIPS!
                src_p.store = []
                sched._execute_task(mid)
                self.assertEqual(len(tgt_p.store), 3)  # Still untouched!
                self.assertTrue(mock_notify.called)

                # --- Part B: Two-Way Merge (Echo-Free) ---
                plat_a = InMemoryPlatform("spotify", "Spotify", [("sp_1", "Song One", "Artist A")])
                plat_b = InMemoryPlatform("ytm", "YouTube Music", [("ytm_2", "Song Two", "Artist B")])
                prov_map["spotify"] = plat_a
                prov_map["ytm"] = plat_b

                t_2way = sched.create_task(
                    SyncTaskCreateRequest(
                        name="2-Way Merge",
                        source_platform="spotify",
                        source_playlist_id="pl_1",
                        target_platform="ytm",
                        target_mode="existing_playlist",
                        target_playlist_id="pl_1",
                        sync_mode="two_way",
                    )
                )
                wid = t_2way["id"]

                # Tick 1: Song One goes to YTM, Song Two goes to Spotify
                sched._execute_task(wid)
                self.assertEqual({x[1] for x in plat_a.store}, {"Song One", "Song Two"})
                self.assertEqual({x[1] for x in plat_b.store}, {"Song One", "Song Two"})

                # Tick 2: Echo-free! Neither side should duplicate or re-add anything
                sched._execute_task(wid)
                self.assertEqual(len(plat_a.store), 2)
                self.assertEqual(len(plat_b.store), 2)
                st_2way = [x for x in sched.list_tasks() if x["id"] == wid][0]
                self.assertEqual(st_2way["last_added_count"], 0)

    def test_notifier_secret_masking_and_cache_inspector_endpoints(self):
        import tempfile
        from pathlib import Path
        from backend.matcher import MatchCache

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            notif_file = tmp_path / "notif.json"
            cache_file = tmp_path / "cache.json"
            temp_cache = MatchCache()
            temp_cache._data = {}

            with patch("backend.notifier.NOTIFICATION_CONFIG_FILE", notif_file), \
                 patch("backend.matcher.MATCH_CACHE_FILE", cache_file), \
                 patch.object(app_module, "match_cache", temp_cache):
                with _client() as client:
                    # 1. Save notification config & verify secret masking
                    r_save = client.post(
                        "/api/notifications/config",
                        json={
                            "enabled": True,
                            "notify_on_sync_error": True,
                            "notify_on_sync_success": True,
                            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/secret123",
                            "bark_url": "my_bark_device_key",
                            "telegram_bot_token": "123456:ABCDEF",
                            "telegram_chat_id": "998877",
                        },
                    )
                    self.assertEqual(r_save.status_code, 200)
                    pub = client.get("/api/notifications/config").json()
                    self.assertEqual(pub["webhook_url"], "********")
                    self.assertEqual(pub["bark_url"], "********")
                    self.assertEqual(pub["telegram_bot_token"], "********")
                    self.assertTrue(pub["has_webhook"])

                    # Re-saving with masked "********" must preserve underlying real secrets!
                    client.post(
                        "/api/notifications/config",
                        json={
                            "enabled": True,
                            "webhook_url": "********",
                            "bark_url": "********",
                            "telegram_bot_token": "********",
                            "telegram_chat_id": "998877",
                        },
                    )
                    raw_loaded = app_module.notifier.load_config()
                    self.assertIn("secret123", raw_loaded["webhook_url"])
                    self.assertEqual(raw_loaded["bark_url"], "https://api.day.app/my_bark_device_key")

                    # Test push dispatch across all 3 channels
                    posted_urls = []

                    class DummyResp:
                        status_code = 200

                        def raise_for_status(self):
                            return None

                    class DummySession:
                        def post(self, url, json=None, timeout=10):
                            posted_urls.append((url, json))
                            return DummyResp()

                    with patch("backend.notifier.make_retry_session", return_value=DummySession()):
                        r_test = client.post("/api/notifications/test")
                        self.assertEqual(r_test.status_code, 200)
                        self.assertEqual(set(r_test.json()["channels"]), {"webhook", "bark", "telegram"})
                        self.assertEqual(len(posted_urls), 3)

                    # 2. MatchCache Inspector list / filter / single-item delete
                    tr1 = TrackItem(title="晴天", artist="周杰伦", album="叶惠美", isrc="TWK970300403", duration_ms=269000)
                    tr2 = TrackItem(title="Lover", artist="Taylor Swift", duration_ms=221000)
                    temp_cache.put(
                        "ytm",
                        tr1,
                        {"track_id": "vid_1", "title": "晴天", "artist": "周杰伦", "score": 98, "confidence": "high"},
                        flush_now=True,
                    )
                    temp_cache.put(
                        "subsonic",
                        tr2,
                        {"track_id": "sub_2", "title": "Lover", "artist": "Taylor Swift", "score": 95, "confidence": "manual"},
                        flush_now=True,
                    )

                    r_all = client.get("/api/cache/matches").json()
                    self.assertEqual(r_all["total_cached"], 2)
                    self.assertEqual(r_all["by_platform"], {"ytm": 1, "subsonic": 1})

                    r_filtered = client.get("/api/cache/matches?platform=ytm&q=TWK970300403").json()
                    self.assertEqual(r_filtered["filtered_count"], 1)
                    key_to_del = r_filtered["entries"][0]["key"]

                    r_del = client.delete("/api/cache/matches/item", params={"key": key_to_del})
                    self.assertEqual(r_del.status_code, 200)
                    self.assertTrue(r_del.json()["deleted"])
                    self.assertEqual(client.get("/api/cache/matches").json()["total_cached"], 1)


if __name__ == "__main__":
    unittest.main()
