"""Unit tests for static HTML progress report generation."""

import unittest
import tempfile
from pathlib import Path
from datetime import datetime

from vlogger.db import Database
from vlogger.core import VLoggerCore
from vlogger.export import export_entries, export_to_file
from vlogger.html_report import generate_html_report, write_html_report


class TestHtmlReport(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_report.db"
        self.db = Database(self.db_path)
        self.core = VLoggerCore(self.db)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_generate_html_empty_db(self):
        html_str = generate_html_report(self.db)
        self.assertIn("<!DOCTYPE html>", html_str)
        self.assertIn("vlogger", html_str)
        self.assertIn("Daily Stats", html_str)
        self.assertIn("Weekly Stats", html_str)
        self.assertIn("Monthly Stats", html_str)
        self.assertIn("Logs", html_str)

    def test_generate_html_with_entries(self):
        t1 = datetime(2026, 9, 21, 9, 0, 0)
        t2 = datetime(2026, 9, 21, 14, 0, 0)
        t3 = datetime(2026, 9, 22, 10, 0, 0)

        self.db.add_manual_entry("Backend API <auth>", 3600, start_dt=t1, project="api")
        self.db.add_manual_entry("Code Review", 1800, start_dt=t2, project="reviews")
        self.db.add_manual_entry("Feature Testing", 5400, start_dt=t3, project="qa")

        html_str = generate_html_report(self.db)

        # Basic structure & 4 tabs
        self.assertIn("<!DOCTYPE html>", html_str)
        self.assertIn("terminal-window", html_str)
        self.assertIn("tab-btn-logs", html_str)
        self.assertIn("tab-btn-stats", html_str)
        self.assertIn("tab-btn-weekly", html_str)
        self.assertIn("tab-btn-monthly", html_str)

        # Views and breakdowns
        self.assertIn("tui-view-logs", html_str)
        self.assertIn("tui-view-stats", html_str)
        self.assertIn("tui-view-weekly", html_str)
        self.assertIn("tui-view-monthly", html_str)
        self.assertIn("tui-stats-breakdown", html_str)
        self.assertIn("tui-weekly-breakdown", html_str)
        self.assertIn("tui-monthly-breakdown", html_str)
        self.assertIn("tui-cell-bar", html_str)

        # Escaped task names
        self.assertIn("Backend API &lt;auth&gt;", html_str)
        self.assertIn("Code Review", html_str)
        self.assertIn("Feature Testing", html_str)

        # Projects
        self.assertIn("api", html_str)
        self.assertIn("reviews", html_str)
        self.assertIn("qa", html_str)

        # Dates, weeks, months
        self.assertIn("2026-09-21", html_str)
        self.assertIn("2026-09-22", html_str)
        self.assertIn("2026-W39", html_str)
        self.assertIn("September 2026", html_str)

    def test_write_html_report_to_file(self):
        out_file = Path(self.temp_dir.name) / "dashboard.html"
        res_path = write_html_report(self.db, file_path=out_file)

        self.assertEqual(res_path, out_file)
        self.assertTrue(out_file.exists())
        content = out_file.read_text(encoding="utf-8")
        self.assertIn("<!DOCTYPE html>", content)
        self.assertGreater(len(content), 1000)

    def test_auto_generate_on_task_stop_and_manual_add(self):
        # Configure custom report path in core
        report_file = Path(self.temp_dir.name) / "auto_progress.html"
        self.db.set_setting("html_report_path", str(report_file))

        self.assertFalse(report_file.exists())

        # Start and stop a timer
        self.core.start("Task Automatically Finished")
        self.core.stop()

        self.assertTrue(report_file.exists(), "Report should be generated after timer stop")
        content1 = report_file.read_text(encoding="utf-8")
        self.assertIn("Task Automatically Finished", content1)

        # Add manual entry
        self.core.add_manual("45m", "Manual Sprint Planning")
        content2 = report_file.read_text(encoding="utf-8")
        self.assertIn("Manual Sprint Planning", content2)

    def test_auto_generate_when_previous_task_auto_stopped(self):
        report_file = Path(self.temp_dir.name) / "auto_switch.html"
        self.db.set_setting("html_report_path", str(report_file))

        # Start task 1
        self.core.start("Task 1")
        # Starting task 2 auto-stops task 1 and triggers report generation
        self.core.start("Task 2")

        self.assertTrue(report_file.exists())
        content = report_file.read_text(encoding="utf-8")
        self.assertIn("Task 1", content)

    def test_export_format_html(self):
        self.db.add_manual_entry("Exported Task", 1200)

        # Export entries
        html_str = export_entries(self.db, fmt="html")
        self.assertIn("<!DOCTYPE html>", html_str)
        self.assertIn("Exported Task", html_str)

        # Export to file
        out_file = Path(self.temp_dir.name) / "exported_report.html"
        count = export_to_file(self.db, file_path=out_file, fmt="html")
        self.assertEqual(count, 1)
        self.assertTrue(out_file.exists())


    def test_auto_generate_on_start_shows_active_running_task(self):
        report_file = Path(self.temp_dir.name) / "active_progress.html"
        self.db.set_setting("html_report_path", str(report_file))

        self.assertFalse(report_file.exists())
        self.core.start("Green Active Running Task")

        self.assertTrue(report_file.exists(), "Report should be generated immediately when a timer starts")
        content = report_file.read_text(encoding="utf-8")
        self.assertIn("RUNNING", content)
        self.assertIn("Green Active Running Task", content)
        self.assertIn("[Active]", content)

    def test_auto_generate_on_update_and_delete(self):
        report_file = Path(self.temp_dir.name) / "actions_progress.html"
        self.db.set_setting("html_report_path", str(report_file))

        entry = self.core.add_manual("30m", "Original Name")
        self.assertIn("Original Name", report_file.read_text(encoding="utf-8"))

        # Update
        self.core.update_entry(entry.id, description="Renamed Task")
        self.assertIn("Renamed Task", report_file.read_text(encoding="utf-8"))

        # Delete
        self.core.delete_entry(entry.id)
        self.assertNotIn("Renamed Task", report_file.read_text(encoding="utf-8"))

    def test_sync_cmd_hook(self):
        import time
        report_file = Path(self.temp_dir.name) / "sync_progress.html"
        marker_file = Path(self.temp_dir.name) / "synced_marker.txt"
        self.db.set_setting("html_report_path", str(report_file))
        self.db.set_setting("html_sync_cmd", f"touch {marker_file}")

        self.core.start("Hook Triggered Task")
        time.sleep(0.1)  # Brief wait for subprocess
        self.assertTrue(marker_file.exists(), "Sync command hook should be executed")

    def test_html_report_readonly_permissions_and_ekselek_branding(self):
        import stat
        report_file = Path(self.temp_dir.name) / "ekselek.html"
        self.db.set_setting("html_report_path", str(report_file))

        self.core.start("Task For Ekselek")

        self.assertTrue(report_file.exists())
        # Check permissions are read-only (0o444)
        file_mode = report_file.stat().st_mode
        self.assertEqual(stat.S_IMODE(file_mode), 0o444, "File should have read-only 0444 permissions")

        # Check content includes ekselek and read-only indicator
        content = report_file.read_text(encoding="utf-8")
        self.assertIn("ekselek", content.lower())
        self.assertIn("READ-ONLY", content)

        # Overwrite test: should cleanly overwrite despite 0o444
        self.core.stop()
        self.assertTrue(report_file.exists())
        self.assertEqual(stat.S_IMODE(report_file.stat().st_mode), 0o444)


if __name__ == "__main__":
    unittest.main()


