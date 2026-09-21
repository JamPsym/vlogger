"""Tests for SQLite database operations."""

import os
import tempfile
from pathlib import Path
import unittest
from datetime import datetime, timedelta

from vlogger.db import Database
from vlogger.models import TimeEntry


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_vlogger.db"
        self.db = Database(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_and_default_settings(self):
        self.assertTrue(self.db_path.exists())
        self.assertEqual(self.db.get_setting("default_description"), "Work")
        self.assertEqual(self.db.get_setting("default_project"), "default")

    def test_settings_set_and_get(self):
        self.db.set_setting("default_description", "Coding")
        self.assertEqual(self.db.get_setting("default_description"), "Coding")

    def test_start_and_stop_timer(self):
        # No active timer initially
        self.assertIsNone(self.db.get_active_entry())

        # Start timer
        start_t = datetime(2026, 9, 21, 10, 0, 0)
        entry = self.db.start_timer(description="Unit test task", start_dt=start_t)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.description, "Unit test task")
        self.assertTrue(entry.is_active)

        # Active entry should be returned
        active = self.db.get_active_entry()
        self.assertIsNotNone(active)
        self.assertEqual(active.id, entry.id)

        # Stop timer 1 hour later
        stop_t = datetime(2026, 9, 21, 11, 0, 0)
        stopped = self.db.stop_timer(end_dt=stop_t)
        self.assertIsNotNone(stopped)
        self.assertFalse(stopped.is_active)
        self.assertEqual(stopped.duration_seconds, 3600)
        self.assertIsNone(self.db.get_active_entry())

    def test_start_timer_auto_stops_previous(self):
        t1 = datetime(2026, 9, 21, 10, 0, 0)
        t2 = datetime(2026, 9, 21, 10, 30, 0)

        e1 = self.db.start_timer(description="Task 1", start_dt=t1)
        e2 = self.db.start_timer(description="Task 2", start_dt=t2)

        # e1 should now be stopped with 1800s
        e1_refreshed = self.db.get_entry(e1.id)
        self.assertFalse(e1_refreshed.is_active)
        self.assertEqual(e1_refreshed.duration_seconds, 1800)

        # e2 should be active
        self.assertTrue(e2.is_active)
        self.assertEqual(self.db.get_active_entry().id, e2.id)

    def test_add_manual_entry(self):
        entry = self.db.add_manual_entry(
            description="Manual past task",
            duration_seconds=2700,
            project="client-x",
            tags=["refactor", "api"],
        )
        self.assertIsNotNone(entry.id)
        self.assertEqual(entry.duration_seconds, 2700)
        self.assertEqual(entry.project, "client-x")
        self.assertIn("refactor", entry.tags)
        self.assertFalse(entry.is_active)

    def test_update_and_delete_entry(self):
        entry = self.db.add_manual_entry("Initial", 1000)
        updated = self.db.update_entry(entry.id, description="Updated desc", project="infra")
        self.assertEqual(updated.description, "Updated desc")
        self.assertEqual(updated.project, "infra")

        deleted = self.db.delete_entry(entry.id)
        self.assertTrue(deleted)
        self.assertIsNone(self.db.get_entry(entry.id))

    def test_list_entries_and_filtering(self):
        t1 = datetime(2026, 9, 21, 8, 0, 0)
        t2 = datetime(2026, 9, 21, 12, 0, 0)
        self.db.add_manual_entry("Task A", 1800, start_dt=t1, project="proj1")
        self.db.add_manual_entry("Task B", 3600, start_dt=t2, project="proj2")

        all_entries = self.db.list_entries()
        self.assertEqual(len(all_entries), 2)

        proj1_entries = self.db.list_entries(project="proj1")
    def test_get_last_description_and_recent(self):
        self.assertIsNone(self.db.get_last_description())
        self.assertEqual(len(self.db.get_recent_descriptions()), 0)

        t1 = datetime(2026, 9, 21, 8, 0, 0)
        t2 = datetime(2026, 9, 21, 9, 0, 0)
        t3 = datetime(2026, 9, 21, 10, 0, 0)
        self.db.add_manual_entry("Task X", 100, start_dt=t1)
        self.db.add_manual_entry("Task Y", 100, start_dt=t2)
        self.db.add_manual_entry("Task X", 100, start_dt=t3)

        self.assertEqual(self.db.get_last_description(), "Task X")
        recent = self.db.get_recent_descriptions()
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["description"], "Task X")
        self.assertEqual(recent[0]["count"], 2)
        self.assertEqual(recent[1]["description"], "Task Y")
        self.assertEqual(recent[1]["count"], 1)


if __name__ == "__main__":
    unittest.main()
