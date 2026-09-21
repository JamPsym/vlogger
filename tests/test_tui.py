"""Unit tests for TUI state machine and key handling."""

import unittest
import tempfile
from pathlib import Path

from vlogger.db import Database
from vlogger.tui import VLoggerTUI


class TestTUI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_tui.db"
        self.db = Database(self.db_path)
        self.tui = VLoggerTUI(self.db)
        self.tui.refresh_data()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initial_state(self):
        self.assertEqual(self.tui.mode, "NORMAL")
        self.assertEqual(self.tui.desc_buffer, "Work")
        self.assertIsNone(self.tui.active_entry)

    def test_start_and_stop_via_key(self):
        # Press 's' to start
        self.tui._handle_normal_key(ord('s'))
        self.tui.refresh_data()
        self.assertIsNotNone(self.tui.active_entry)
        self.assertEqual(self.tui.active_entry.description, "Work")

        # Press 's' again to stop
        self.tui._handle_normal_key(ord('s'))
        self.tui.refresh_data()
        self.assertIsNone(self.tui.active_entry)
        self.assertEqual(len(self.tui.entries), 1)

    def test_insert_mode_and_edit_description(self):
        # Enter insert mode via 'i'
        self.tui._handle_normal_key(ord('i'))
        self.assertEqual(self.tui.mode, "INSERT")

        # Clear description with Ctrl-U (ASCII 21)
        self.tui._handle_insert_key(21)
        self.assertEqual(self.tui.desc_buffer, "")

        # Type "Coding"
        for ch in "Coding":
            self.tui._handle_insert_key(ord(ch))
        self.assertEqual(self.tui.desc_buffer, "Coding")

        # Press Enter (ASCII 10) to return to NORMAL mode
        self.tui._handle_insert_key(10)
        self.assertEqual(self.tui.mode, "NORMAL")
        self.assertEqual(self.tui.desc_buffer, "Coding")

        # Start timer with the edited description
        self.tui._handle_normal_key(ord('s'))
        self.tui.refresh_data()
        self.assertEqual(self.tui.active_entry.description, "Coding")

    def test_default_description_keys(self):
        # Change buffer
        self.tui.desc_buffer = "Temporary Task"
        
        # Press 'd' to reset to default
        self.tui._handle_normal_key(ord('d'))
        self.assertEqual(self.tui.desc_buffer, "Work")

        # Change buffer and press 'D' to save as new default
        self.tui.desc_buffer = "Design Work"
        self.tui._handle_normal_key(ord('D'))
        self.assertEqual(self.tui.default_desc, "Design Work")
        self.assertEqual(self.db.get_setting("default_description"), "Design Work")

    def test_history_navigation_and_deletion(self):
        # Create two entries
        e1 = self.db.add_manual_entry("Task 1", 300)
        e2 = self.db.add_manual_entry("Task 2", 600)
        self.tui.refresh_data()
        self.assertEqual(len(self.tui.entries), 2)

        # Move down with 'j'
        self.assertEqual(self.tui.selected_idx, 0)
        self.tui._handle_normal_key(ord('j'))
        self.assertEqual(self.tui.selected_idx, 1)

        # Move up with 'k'
        self.tui._handle_normal_key(ord('k'))
        self.assertEqual(self.tui.selected_idx, 0)

        # Press 'x' to trigger delete modal
        self.tui._handle_normal_key(ord('x'))
        self.assertEqual(self.tui.mode, "CONFIRM_DELETE")
        self.assertIsNotNone(self.tui.pending_delete_id)

    def test_quit_key(self):
        keep_running = self.tui._handle_normal_key(ord('q'))
        self.assertFalse(keep_running)


if __name__ == "__main__":
    unittest.main()
