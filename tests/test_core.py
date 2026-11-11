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
                 patch.object(app_module.applemusic_provider, "get_status", return_value={"connected": False}):
                r_st = client.get("/api/platforms/status")
                self.assertEqual(r_st.status_code, 200)
                plats = r_st.json()["platforms"]
                self.assertEqual(
                    set(plats.keys()), {"ytm", "spotify", "netease", "qqmusic", "kugou", "applemusic"}
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
        js_path = STATIC_DIR / "js" / "app.js"
        css_path = STATIC_DIR / "css" / "styles.css"

        self.assertTrue(html_path.exists())
        self.assertTrue(js_path.exists())
        self.assertTrue(css_path.exists())

        jsc_bin = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
        if os.path.exists(jsc_bin):
            proc = subprocess.run(
                [
                    jsc_bin,
                    "-e",
                    f"new Function(readFile('{js_path.as_posix()}')); print('JS_SYNTAX_OK');",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, f"JS syntax error: {proc.stdout} {proc.stderr}")
            self.assertIn("JS_SYNTAX_OK", proc.stdout)

        html_text = html_path.read_text(encoding="utf-8")
        js_text = js_path.read_text(encoding="utf-8")

        # 1. Every literal getElementById('xyz') in app.js must exist in index.html or dynamic JS templates
        html_ids = set(re.findall(r'\bid=["\']([^"\']+)["\']', html_text))
        dynamic_js_ids = set(re.findall(r'\bid=["\']([^"\']+)["\']', js_text))
        all_known_ids = html_ids | dynamic_js_ids
        referenced_ids = set(re.findall(r"getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)", js_text))
        missing_ids = referenced_ids - all_known_ids
        self.assertEqual(missing_ids, set(), f"Missing DOM IDs referenced in app.js: {missing_ids}")

        # 2. Every inline handler function in index.html must exist in app.js
        js_funcs = set(re.findall(r"(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(", js_text))
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


if __name__ == "__main__":
    unittest.main()
