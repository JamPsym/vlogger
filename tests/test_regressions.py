"""Regression checks for reporting, timer integrity, and sync behavior."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from vlogger.core import VLoggerCore, parse_duration
from vlogger.db import Database
from vlogger.export import export_entries, export_to_file
from vlogger.html_report import generate_html_report, write_html_report


class ScriptCounter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.count = 0

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.count += 1


class TestRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "vlogger.db"
        self.db = Database(self.db_path)

    def test_simultaneous_starts_leave_one_active_timer(self):
        gate = threading.Barrier(3)
        failures = []

        def start(i):
            try:
                gate.wait(timeout=5)
                Database(self.db_path).start_timer(f"task {i}")
            except Exception as exc:
                failures.append(exc)

        threads = [threading.Thread(target=start, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        gate.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(failures, [])
        with self.db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM entries WHERE end_time IS NULL").fetchone()[0], 1)

    def test_existing_duplicate_active_timers_are_repaired(self):
        first = "2026-09-26T10:00:00+02:00"
        second = "2026-09-26T10:30:00+02:00"
        with self.db.get_connection() as conn:
            conn.execute("DROP INDEX idx_entries_one_active")
            for stamp in (first, second):
                conn.execute(
                    "INSERT INTO entries(description, project, tags, start_time, created_at, updated_at) VALUES ('old', 'default', '', ?, ?, ?)",
                    (stamp, stamp, stamp),
                )
        Database(self.db_path)
        with self.db.get_connection() as conn:
            rows = conn.execute("SELECT start_time, end_time, duration_seconds FROM entries ORDER BY id").fetchall()
        self.assertEqual(rows[0]["end_time"], second)
        self.assertEqual(rows[0]["duration_seconds"], 1800)
        self.assertIsNone(rows[1]["end_time"])

    def test_simultaneous_toggles_cancel_each_other(self):
        gate = threading.Barrier(3)
        failures = []

        def toggle():
            try:
                gate.wait(timeout=5)
                Database(self.db_path).toggle_timer("hotkey")
            except Exception as exc:
                failures.append(exc)

        threads = [threading.Thread(target=toggle) for _ in range(2)]
        for thread in threads:
            thread.start()
        gate.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(failures, [])
        self.assertIsNone(self.db.get_active_entry())

    def test_overnight_time_is_split_across_days_and_months(self):
        start = datetime(2026, 8, 31, 23, 30).astimezone()
        end = datetime.fromtimestamp(start.timestamp() + 3600).astimezone()
        self.db.add_manual_entry("overnight", 3600, start_dt=start, end_dt=end)
        daily = {d["date"]: d for d in self.db.get_daily_stats(include_today=False)}
        monthly = {m["month"]: m for m in self.db.get_monthly_stats(include_current_month=False)}
        self.assertEqual(daily["2026-08-31"]["total_seconds"], 1800)
        self.assertEqual(daily["2026-09-01"]["total_seconds"], 1800)
        self.assertEqual(monthly["2026-08"]["total_seconds"], 1800)
        self.assertEqual(monthly["2026-09"]["total_seconds"], 1800)
        self.assertEqual(VLoggerCore.calculate_daily_summary(list(daily.values()))["total_entries"], 1)
        filtered = self.db.get_daily_stats(since="2026-09-01", until="2026-09-01", include_today=False)
        self.assertEqual([(d["date"], d["total_seconds"]) for d in filtered], [("2026-09-01", 1800)])
        report_path = Path(self.temp.name) / "overnight.html"
        self.assertEqual(export_to_file(self.db, report_path, fmt="html", since="2026-09-01"), 1)

    def test_today_counts_overnight_session(self):
        now = datetime.now().astimezone()
        start = datetime.combine(now.date() - timedelta(days=1), datetime.min.time()).replace(hour=23, minute=30).astimezone()
        end = datetime.fromtimestamp(start.timestamp() + 3600).astimezone()
        self.db.add_manual_entry("overnight", 3600, start_dt=start, end_dt=end)
        self.assertEqual(self.db.get_stats_for_today()["total_seconds"], 1800)

    def test_html_export_applies_project_filter(self):
        self.db.add_manual_entry("share this", 60, project="public")
        self.db.add_manual_entry("SECRET ENTRY", 60, project="private")
        report = export_entries(self.db, fmt="html", project="public")
        self.assertIn("share this", report)
        self.assertNotIn("SECRET ENTRY", report)

    def test_description_cannot_end_inline_script(self):
        payload = "</script><script>window.probe=1</script>"
        self.db.add_manual_entry(payload, 60)
        report = generate_html_report(self.db)
        parser = ScriptCounter()
        parser.feed(report)
        self.assertEqual(parser.count, 1)
        self.assertNotIn(payload, report)

    def test_concurrent_report_writes_keep_latest_snapshot(self):
        first_rendered = threading.Event()
        release_first = threading.Event()
        second_done = threading.Event()
        failures = []
        target = Path(self.temp.name) / "report.html"
        calls = 0

        def render(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                first_rendered.set()
                if not release_first.wait(timeout=5):
                    raise TimeoutError("first report write was not released")
                return "older snapshot"
            return "newer snapshot"

        def write(done=None):
            try:
                write_html_report(self.db, target)
            except Exception as exc:
                failures.append(exc)
            finally:
                if done:
                    done.set()

        with patch("vlogger.html_report.generate_html_report", side_effect=render):
            first = threading.Thread(target=write)
            first.start()
            self.assertTrue(first_rendered.wait(timeout=5))
            second = threading.Thread(target=write, args=(second_done,))
            second.start()
            self.assertFalse(second_done.wait(timeout=0.1))
            release_first.set()
            first.join(timeout=5)
            second.join(timeout=5)

        self.assertEqual(failures, [])
        self.assertEqual(target.read_text(encoding="utf-8"), "newer snapshot")

    def test_static_report_never_shows_nonfunctional_edit_controls(self):
        report = generate_html_report(self.db, read_only=False)
        self.assertIn("READ-ONLY MONITOR", report)
        self.assertNotIn("simulateToggleTimer", report)

    def test_date_only_until_includes_that_day(self):
        self.db.add_manual_entry("same day", 60, start_dt=datetime.fromisoformat("2026-09-26T10:00:00+02:00"))
        self.assertEqual(len(self.db.list_entries(until="2026-09-26")), 1)

    def test_entries_sort_by_instant_across_timezone_offsets(self):
        stamps = (("earlier", "2026-09-26T23:30:00+02:00"),
                  ("later", "2026-09-26T22:45:00+00:00"))
        with self.db.get_connection() as conn:
            for label, stamp in stamps:
                conn.execute(
                    "INSERT INTO entries(description, project, tags, start_time, end_time, duration_seconds, created_at, updated_at) "
                    "VALUES (?, 'default', '', ?, ?, 0, ?, ?)",
                    (label, stamp, stamp, stamp, stamp),
                )
        self.assertEqual([e.description for e in self.db.list_entries(limit=2)], ["later", "earlier"])

    def test_recent_tasks_use_actual_instants_across_offsets(self):
        stamps = (("repeated", "2026-09-26T23:30:00+02:00"),
                  ("repeated", "2026-09-26T22:45:00+00:00"),
                  ("other", "2026-09-26T23:00:00+00:00"))
        with self.db.get_connection() as conn:
            for label, stamp in stamps:
                conn.execute(
                    "INSERT INTO entries(description, project, tags, start_time, end_time, duration_seconds, created_at, updated_at) "
                    "VALUES (?, 'default', '', ?, ?, 0, ?, ?)",
                    (label, stamp, stamp, stamp, stamp),
                )
        recent = self.db.get_recent_descriptions()
        self.assertEqual([row["description"] for row in recent], ["other", "repeated"])
        self.assertEqual(recent[1]["last_used"], "2026-09-26T22:45:00+00:00")

    def test_explicit_default_overrides_last_task(self):
        self.db.add_manual_entry("old task", 60)
        self.db.set_setting("default_description", "Preferred")
        self.assertEqual(VLoggerCore(self.db).default_description, "Preferred")

    def test_invalid_duration_is_rejected(self):
        for value in ("-1h", "1h junk", "1h -30m"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_duration(value)

    def test_export_and_stats_include_more_than_previous_limits(self):
        stamp = "2026-09-26T10:00:00+02:00"
        end_stamp = "2026-09-26T10:00:01+02:00"
        rows = [(f"task {i}", "default", "", stamp, end_stamp, 1, stamp, end_stamp) for i in range(10001)]
        with self.db.get_connection() as conn:
            conn.executemany(
                "INSERT INTO entries(description, project, tags, start_time, end_time, duration_seconds, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        self.assertEqual(len(json.loads(export_entries(self.db))), 10001)
        self.assertEqual(sum(d["count"] for d in self.db.get_daily_stats(include_today=False)), 10001)

    def test_cli_returns_before_automatic_sync_finishes(self):
        marker = Path(self.temp.name) / "synced"
        self.db.set_setting("html_sync_cmd", f"sleep 2; touch {marker}")
        env = os.environ.copy()
        env["VLOGGER_DB"] = str(self.db_path)
        start = time.monotonic()
        result = subprocess.run(
            [sys.executable, "-m", "vlogger", "start", "background sync"],
            env=env, capture_output=True, text=True,
        )
        elapsed = time.monotonic() - start
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(elapsed, 1.5)
        self.assertFalse(marker.exists())
        deadline = time.monotonic() + 4
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(marker.exists())

    def test_sync_quotes_report_path_for_shell_command(self):
        report_path = Path(self.temp.name) / "report's file.html"
        report_path.write_text("report", encoding="utf-8")
        self.db.set_setting("html_sync_cmd", "test -f {file}")
        ok, message = VLoggerCore(self.db).sync_html_report(report_path, wait=True)
        self.assertTrue(ok, message)


if __name__ == "__main__":
    unittest.main()
