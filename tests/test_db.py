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
        self.assertEqual(len(proj1_entries), 1)
        self.assertEqual(proj1_entries[0].description, "Task A")

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

    def test_get_daily_stats(self):
        t1 = datetime(2026, 9, 20, 9, 0, 0)
        t2 = datetime(2026, 9, 21, 10, 0, 0)
        t3 = datetime(2026, 9, 21, 14, 0, 0)

        self.db.add_manual_entry("Coding", 3600, start_dt=t1, project="backend")
        self.db.add_manual_entry("Code Review", 1800, start_dt=t2, project="reviews")
        self.db.add_manual_entry("Coding", 5400, start_dt=t3, project="backend")

        # Call get_daily_stats with include_today=False
        stats = self.db.get_daily_stats(include_today=False)
        self.assertEqual(len(stats), 2)

        # Most recent date first: 2026-09-21
        day_21 = stats[0]
        self.assertEqual(day_21["date"], "2026-09-21")
        self.assertEqual(day_21["day_name"], "Monday")
        self.assertEqual(day_21["total_seconds"], 7200) # 1800 + 5400
        self.assertEqual(day_21["count"], 2)
        self.assertEqual(len(day_21["tasks"]), 2)
        self.assertEqual(day_21["tasks"][0]["description"], "Coding")
        self.assertEqual(day_21["tasks"][0]["total_seconds"], 5400)
        self.assertEqual(day_21["tasks"][0]["percentage"], 75.0)
        self.assertEqual(day_21["tasks"][1]["description"], "Code Review")
        self.assertEqual(day_21["tasks"][1]["total_seconds"], 1800)
        self.assertEqual(day_21["tasks"][1]["percentage"], 25.0)

        # 2026-09-20
        day_20 = stats[1]
        self.assertEqual(day_20["date"], "2026-09-20")
        self.assertEqual(day_20["total_seconds"], 3600)
        self.assertEqual(day_20["count"], 1)

        # Filter by project
        stats_backend = self.db.get_daily_stats(project="backend", include_today=False)
        self.assertEqual(len(stats_backend), 2)
        self.assertEqual(stats_backend[0]["total_seconds"], 5400)
        self.assertEqual(stats_backend[1]["total_seconds"], 3600)

    def test_get_weekly_stats(self):
        # 2026-09-14 is Monday of W38
        # 2026-09-21 is Monday of W39
        t1 = datetime(2026, 9, 15, 9, 0, 0)
        t2 = datetime(2026, 9, 21, 10, 0, 0)
        t3 = datetime(2026, 9, 22, 14, 0, 0)

        self.db.add_manual_entry("Sprint 1 Task", 3600, start_dt=t1, project="backend")
        self.db.add_manual_entry("Sprint 2 Task 1", 1800, start_dt=t2, project="reviews")
        self.db.add_manual_entry("Sprint 2 Task 2", 5400, start_dt=t3, project="backend")

        weeks = self.db.get_weekly_stats(include_current_week=False)
        self.assertEqual(len(weeks), 2)

        # Most recent week: 2026-W39
        w39 = weeks[0]
        self.assertEqual(w39["week"], "2026-W39")
        self.assertEqual(w39["total_seconds"], 7200)
        self.assertEqual(w39["count"], 2)
        self.assertEqual(w39["active_days_count"], 2)
        self.assertEqual(len(w39["days_breakdown"]), 2)

        # 2026-W38
        w38 = weeks[1]
        self.assertEqual(w38["week"], "2026-W38")
        self.assertEqual(w38["total_seconds"], 3600)
        self.assertEqual(w38["count"], 1)

    def test_get_monthly_stats(self):
        t1 = datetime(2026, 8, 20, 9, 0, 0)
        t2 = datetime(2026, 9, 21, 10, 0, 0)

        self.db.add_manual_entry("August Task", 3600, start_dt=t1)
        self.db.add_manual_entry("September Task", 1800, start_dt=t2)

        months = self.db.get_monthly_stats(include_current_month=False)
        self.assertEqual(len(months), 2)

        m_sep = months[0]
        self.assertEqual(m_sep["month"], "2026-09")
        self.assertIn("September", m_sep["month_name"])
        self.assertEqual(m_sep["total_seconds"], 1800)

        m_aug = months[1]
        self.assertEqual(m_aug["month"], "2026-08")
        self.assertIn("August", m_aug["month_name"])
        self.assertEqual(m_aug["total_seconds"], 3600)


if __name__ == "__main__":
    unittest.main()
