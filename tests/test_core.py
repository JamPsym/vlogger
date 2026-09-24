"""Tests for core business logic and duration parsing."""

import unittest
import tempfile
from pathlib import Path

from vlogger.db import Database
from vlogger.core import VLoggerCore, parse_duration


class TestCore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_core.db"
        self.db = Database(self.db_path)
        self.core = VLoggerCore(self.db)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_duration(self):
        # Minutes
        self.assertEqual(parse_duration("45m"), 2700)
        self.assertEqual(parse_duration("30"), 1800)  # bare number = minutes

        # Hours
        self.assertEqual(parse_duration("1h"), 3600)
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration("1.5h"), 5400)
        self.assertEqual(parse_duration("2.25h"), 8100)

        # Seconds
        self.assertEqual(parse_duration("45s"), 45)

        # Compound
        self.assertEqual(parse_duration("1h30m"), 5400)
        self.assertEqual(parse_duration("1h 15m 30s"), 4530)

        # Invalid
        with self.assertRaises(ValueError):
            parse_duration("invalid_str")

    def test_default_description_setting(self):
        self.assertEqual(self.core.default_description, "Work")
        
        # When an entry is added, default_description becomes that entry's description
        self.db.add_manual_entry("Sprint Review", 1800)
        self.assertEqual(self.core.default_description, "Sprint Review")

        # Explicit start uses that default
        entry = self.core.start()
        self.assertEqual(entry.description, "Sprint Review")

    def test_toggle_logic(self):
        # 1. First toggle should start
        res1 = self.core.toggle(description="Toggle Task")
        self.assertEqual(res1["action"], "started")
        self.assertTrue(self.db.get_active_entry().is_active)

        # 2. Second toggle should stop
        res2 = self.core.toggle()
        self.assertEqual(res2["action"], "stopped")
        self.assertIsNone(self.db.get_active_entry())

    def test_waybar_payload(self):
        # When idle
        payload_idle = self.core.get_waybar_payload()
        self.assertEqual(payload_idle["class"], "stopped")
        self.assertIn("Idle", payload_idle["text"])

        # When running
        self.core.start("Waybar Test")
        payload_run = self.core.get_waybar_payload()
        self.assertEqual(payload_run["class"], "running")
        self.assertIn("Waybar Test", payload_run["text"])

    def test_daily_stats_and_summary(self):
        from datetime import datetime
        t1 = datetime(2026, 9, 21, 9, 0, 0)
        t2 = datetime(2026, 9, 22, 10, 0, 0)
        self.db.add_manual_entry("Task 1", 3600, start_dt=t1)
        self.db.add_manual_entry("Task 2", 7200, start_dt=t2)

        days, summary = self.core.get_daily_stats()
        self.assertGreaterEqual(len(days), 2)
        self.assertEqual(summary["total_seconds"], 10800)
        self.assertEqual(summary["total_entries"], 2)
        self.assertEqual(summary["active_days"], 2)
        self.assertEqual(summary["average_daily_seconds"], 5400)
        self.assertEqual(summary["max_day_seconds"], 7200)
        self.assertEqual(summary["peak_day"], "2026-09-22")


if __name__ == "__main__":
    unittest.main()
