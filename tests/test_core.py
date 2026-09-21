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
        self.core.default_description = "Writing Code"
        self.assertEqual(self.core.default_description, "Writing Code")

        # Start timer without explicit description uses default
        entry = self.core.start()
        self.assertEqual(entry.description, "Writing Code")

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


if __name__ == "__main__":
    unittest.main()
