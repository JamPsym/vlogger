"""Screen-size and text rendering checks for the curses interface."""

import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest.mock import patch

from vlogger.db import Database
from vlogger.tui import VLoggerTUI


class Screen:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.cells = [[" " for _ in range(width)] for _ in range(height)]

    def addstr(self, y, x, value, *args):
        self._write(y, x, value)

    def addch(self, y, x, value, *args):
        self._write(y, x, chr(value) if isinstance(value, int) else value)

    def _write(self, y, x, value):
        if y < 0 or y >= self.height or x < 0:
            raise AssertionError(f"off-screen write at ({x}, {y})")
        cursor = x
        for char in value:
            width = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in "WF" else 1)
            if cursor + width > self.width:
                raise AssertionError(f"off-screen text at ({x}, {y}): {value!r}")
            if width:
                self.cells[y][cursor] = char
                cursor += width


class TestTuiLayout(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        db = Database(Path(self.temp.name) / "layout.db")
        db.add_manual_entry("Review 项目 and café " * 5, 120)
        db.start_timer("A running description that is much longer than the field")
        self.tui = VLoggerTUI(db)
        self.tui.refresh_data()

    def render(self, view, width, height):
        screen = Screen(width, height)
        self.tui.mode = "NORMAL"
        self.tui.view = view
        with patch("vlogger.tui.curses.color_pair", return_value=0):
            self.tui._render_header(screen, height, width)
            self.tui._render_timer_and_controls(screen, height, width)
            if view == "LOGS":
                self.tui._render_history_table(screen, height, width)
            elif view == "STATS":
                self.tui._render_daily_stats(screen, height, width)
            elif view == "WEEKLY":
                self.tui._render_weekly_stats(screen, height, width)
            else:
                self.tui._render_monthly_stats(screen, height, width)
            self.tui._render_footer(screen, height, width)
        self.assertEqual(screen.cells[height - 3][2], "╰")
        self.assertEqual(screen.cells[height - 3][width - 3], "╯")

    def test_all_views_fit_supported_screen_sizes(self):
        for width, height in ((55, 16), (55, 24), (80, 24), (120, 40)):
            for view in ("LOGS", "STATS", "WEEKLY", "MONTHLY"):
                with self.subTest(width=width, height=height, view=view):
                    self.render(view, width, height)

    def test_modals_fit_minimum_screen(self):
        self.tui.pending_delete_id = self.tui.entries[0].id
        self.tui.editing_entry_id = self.tui.entries[0].id
        self.tui.edit_buffer = "Description long enough to scroll in the edit dialog"
        self.tui.edit_cursor_pos = len(self.tui.edit_buffer)
        self.tui.desc_options = self.tui.core.get_unique_descriptions()
        self.tui.selected_day_detail = self.tui.daily_stats[0]
        for mode, method in (
            ("HELP", self.tui._render_help_modal),
            ("CONFIRM_DELETE", self.tui._render_confirm_delete_modal),
            ("EDIT_HISTORY", self.tui._render_edit_history_modal),
            ("PICK_DESC", self.tui._render_pick_desc_modal),
            ("DAY_DETAIL", self.tui._render_day_detail_modal),
        ):
            with self.subTest(mode=mode):
                self.tui.mode = mode
                screen = Screen(55, 16)
                with patch("vlogger.tui.curses.color_pair", return_value=0):
                    method(screen, 16, 55)

    def test_long_field_keeps_cursor_in_view(self):
        value = "abcdefghijklmnopqrstuvwxyz"
        self.assertEqual(self.tui._field_view(value, 4, 10), ("abcdefghij", 4))
        visible, cursor = self.tui._field_view(value, len(value), 10)
        self.assertEqual(visible, "rstuvwxyz")
        self.assertEqual(cursor, 9)
        wide, column = self.tui._field_view("界" * 10, 10, 10)
        self.assertLess(column, 10)
        self.assertLessEqual(len(wide) * 2, 10)

    def test_unchanged_timer_uses_cached_statistics(self):
        with patch.object(self.tui.db, "_stats_entries", side_effect=AssertionError("unexpected aggregate refresh")):
            self.tui.refresh_data(full=False)

    def test_insert_accepts_non_ascii_text(self):
        self.tui.mode = "INSERT"
        self.tui.desc_buffer = ""
        self.tui.cursor_pos = 0
        for char in "Zażółć":
            self.tui._handle_insert_key(ord(char) if ord(char) < 256 else char)
        self.assertEqual(self.tui.desc_buffer, "Zażółć")


if __name__ == "__main__":
    unittest.main()
