"""Terminal User Interface (TUI) for vlogger using curses.

Keyboard-first, Vim-bindings, start/stop buttons, description field with default,
and live timer ticker.
"""

import curses
import os
import sys
import time
import unicodedata
from datetime import datetime
from typing import Optional, List

from vlogger.db import Database
from vlogger.models import TimeEntry
from vlogger.core import VLoggerCore


class VLoggerTUI:
    @staticmethod
    def _cell_width(char: str) -> int:
        return 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in "WF" else 1)

    @staticmethod
    def _fit_text(value: str, width: int, pad: bool = False) -> str:
        """Fit text to terminal cells, including wide and combining characters."""
        used = 0
        result = []
        for char in value:
            if not char.isprintable():
                char = " "
            cells = VLoggerTUI._cell_width(char)
            if used + cells > width:
                break
            result.append(char)
            used += cells
        if pad:
            result.append(" " * max(0, width - used))
        return "".join(result)

    @staticmethod
    def _field_view(value: str, cursor: int, width: int):
        """Keep the cursor visible while editing a description longer than its field."""
        cursor = max(0, min(cursor, len(value)))
        start = cursor
        used = 0
        while start > 0:
            cells = VLoggerTUI._cell_width(value[start - 1])
            if used + cells >= width:
                break
            start -= 1
            used += cells
        return VLoggerTUI._fit_text(value[start:], width), used

    @staticmethod
    def _modal_width(preferred: int, screen_width: int) -> int:
        return screen_width - 2 if screen_width <= preferred + 8 else preferred

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self.core = VLoggerCore(self.db)
        
        # State
        self.mode = "NORMAL"  # "NORMAL", "INSERT", "CONFIRM_DELETE", "HELP", "EDIT_HISTORY", "PICK_DESC", "DAY_DETAIL"
        self.view = "LOGS"  # "LOGS", "STATS", "WEEKLY", "MONTHLY"
        self.default_desc = self.core.default_description
        self.desc_buffer = self.default_desc
        self.cursor_pos = len(self.desc_buffer)
        
        self.selected_idx = 0
        self.history_offset = 0
        self.entries: List[TimeEntry] = []
        self.active_entry: Optional[TimeEntry] = None
        self.today_stats = {"total_seconds": 0, "count": 0}
        self._today_stats_at = time.monotonic()
        self._last_stats_refresh = 0.0
        self._stats_date = None

        self.stats_selected_idx = 0
        self.stats_offset = 0
        self.daily_stats: List[dict] = []
        self.daily_summary: dict = {}

        self.weekly_selected_idx = 0
        self.weekly_offset = 0
        self.weekly_stats: List[dict] = []
        self.weekly_summary: dict = {}

        self.monthly_selected_idx = 0
        self.monthly_offset = 0
        self.monthly_stats: List[dict] = []
        self.monthly_summary: dict = {}

        self.selected_day_detail: Optional[dict] = None
        self.day_detail_offset: int = 0
        
        self.editing_entry_id: Optional[int] = None
        self.edit_buffer: str = ""
        self.edit_cursor_pos: int = 0

        self.desc_options: List[dict] = []
        self.pick_idx: int = 0
        self.pick_offset: int = 0

        self.status_message = "Ready. Press 's' to start/stop, Tab to switch views (1-4), 'i' to edit, '?' for help."
        self.status_message_time = time.time()
        self.pending_delete_id: Optional[int] = None

    def set_status(self, msg: str, duration: float = 3.0):
        self.status_message = msg
        self.status_message_time = time.time() + duration

    def refresh_data(self, full: bool = True):
        """Reload timer state; rebuild aggregates when data or the day changes."""
        previous = [(e.id, e.updated_at, e.end_time) for e in self.entries]
        previous_active = self.active_entry.id if self.active_entry else None
        self.active_entry = self.db.get_active_entry()
        self.entries = self.db.list_entries(limit=50)
        self.selected_idx = min(self.selected_idx, max(0, len(self.entries) - 1))
        current = [(e.id, e.updated_at, e.end_time) for e in self.entries]
        active_id = self.active_entry.id if self.active_entry else None
        full = (full or current != previous or active_id != previous_active or
                self._stats_date != datetime.now().date())
        if full:
            self.default_desc = self.core.default_description
            stats_entries = self.db._stats_entries()
            self.today_stats = self.db.get_stats_for_today(entries_override=stats_entries)
            self._today_stats_at = time.monotonic()
            self.daily_stats = self.db.get_daily_stats(days_limit=30, entries_override=stats_entries)
            self.daily_summary = VLoggerCore.calculate_daily_summary(self.daily_stats)
            self.weekly_stats = self.db.get_weekly_stats(weeks_limit=26, entries_override=stats_entries)
            self.weekly_summary = VLoggerCore.calculate_weekly_summary(self.weekly_stats)
            self.monthly_stats = self.db.get_monthly_stats(months_limit=12, entries_override=stats_entries)
            self.monthly_summary = VLoggerCore.calculate_monthly_summary(self.monthly_stats)
            self._last_stats_refresh = time.monotonic()
            self._stats_date = datetime.now().date()

        if self.stats_selected_idx >= len(self.daily_stats) and self.daily_stats:
            self.stats_selected_idx = len(self.daily_stats) - 1
        if self.weekly_selected_idx >= len(self.weekly_stats) and self.weekly_stats:
            self.weekly_selected_idx = len(self.weekly_stats) - 1
        if self.monthly_selected_idx >= len(self.monthly_stats) and self.monthly_stats:
            self.monthly_selected_idx = len(self.monthly_stats) - 1

        # If active entry exists and we are not currently editing, reflect its description
        if self.active_entry and self.mode not in ("INSERT", "PICK_DESC"):
            self.desc_buffer = self.active_entry.description
            self.cursor_pos = len(self.desc_buffer)
        elif not self.active_entry and self.mode == "NORMAL" and not self.desc_buffer:
            self.desc_buffer = self.default_desc
            self.cursor_pos = len(self.desc_buffer)

    def run(self):
        """Entry point wrapped in curses wrapper."""
        # Set ESCDELAY to 25ms so Esc key registers immediately without lag
        os.environ.setdefault("ESCDELAY", "25")
        curses.wrapper(self._main_loop)

    def _init_colors(self):
        curses.start_color()
        curses.use_default_colors()
        try:
            curses.curs_set(0)  # Hide cursor by default
        except Exception:
            pass

        # Define color pairs: (index, fg, bg)
        # Check available colors
        has_256 = curses.COLORS >= 256
        
        curses.init_pair(1, curses.COLOR_CYAN, -1)     # Header / Borders
        curses.init_pair(2, curses.COLOR_GREEN, -1)    # Running / Success
        curses.init_pair(3, curses.COLOR_RED, -1)      # Stopped / Alert
        curses.init_pair(4, curses.COLOR_YELLOW, -1)   # Timer digits / Highlight
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_GREEN)  # Start Button active
        curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_RED)    # Stop Button active
        curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_CYAN)   # Selected row / input highlight
        curses.init_pair(8, curses.COLOR_MAGENTA, -1)  # Projects / tags
        curses.init_pair(9, curses.COLOR_WHITE, -1)    # Normal text

        # Solid opaque modal pairs (using COLOR_BLACK background so underlying text never shines through)
        curses.init_pair(10, curses.COLOR_WHITE, curses.COLOR_BLACK)  # Modal interior / white on solid black
        curses.init_pair(11, curses.COLOR_YELLOW, curses.COLOR_BLACK) # Modal highlight / title / border
        curses.init_pair(12, curses.COLOR_RED, curses.COLOR_BLACK)    # Modal alert / delete
        curses.init_pair(13, curses.COLOR_CYAN, curses.COLOR_BLACK)   # Modal info / accents

    def _draw_box(
        self,
        stdscr,
        y: int,
        x: int,
        h: int,
        w: int,
        title: str = "",
        color_pair: int = 1,
        fill: bool = False,
        fill_pair: Optional[int] = None,
    ):
        """Draw a box with rounded corners, optional title, and optional solid fill."""
        if h < 2 or w < 2:
            return
        
        attr = curses.color_pair(color_pair)
        fill_attr = curses.color_pair(fill_pair) if fill_pair is not None else attr

        try:
            # If fill requested, erase/fill the entire rectangular area inside the box
            if fill:
                blank_row = " " * (w - 2)
                for i in range(1, h - 1):
                    stdscr.addstr(y + i, x + 1, blank_row, fill_attr)

            # Draw corners
            stdscr.addstr(y, x, "╭", attr)
            stdscr.addstr(y, x + w - 1, "╮", attr)
            stdscr.addstr(y + h - 1, x, "╰", attr)
            stdscr.addstr(y + h - 1, x + w - 1, "╯", attr)

            # Draw top and bottom
            stdscr.addstr(y, x + 1, "─" * (w - 2), attr)
            stdscr.addstr(y + h - 1, x + 1, "─" * (w - 2), attr)

            # Draw sides
            for i in range(1, h - 1):
                stdscr.addstr(y + i, x, "│", attr)
                stdscr.addstr(y + i, x + w - 1, "│", attr)

            # Draw title
            if title:
                t = f" {title} "
                stdscr.addstr(y, x + 2, self._fit_text(t, w - 4), attr | curses.A_BOLD)
        except curses.error:
            pass

    def _main_loop(self, stdscr):
        self._init_colors()
        stdscr.timeout(500)  # 500ms timeout for non-blocking key reads & timer ticking

        while True:
            self.refresh_data(full=time.monotonic() - self._last_stats_refresh >= 5)
            stdscr.erase()
            max_y, max_x = stdscr.getmaxyx()

            if max_y < 16 or max_x < 55:
                # Terminal too small warning
                msg = f"Terminal too small ({max_x}x{max_y}). Min: 55x16."
                try:
                    stdscr.addstr(0, 0, msg[:max_x - 1], curses.color_pair(3) | curses.A_BOLD)
                except curses.error:
                    pass
                try:
                    raw = stdscr.get_wch()
                    ch = ord(raw) if isinstance(raw, str) and ord(raw) < 256 else raw
                except curses.error:
                    continue
                if ch in (ord('q'), ord('Q')):
                    break
                continue

            # Render UI Components
            self._render_header(stdscr, max_y, max_x)
            self._render_timer_and_controls(stdscr, max_y, max_x)
            if self.view == "LOGS":
                self._render_history_table(stdscr, max_y, max_x)
            elif self.view == "STATS":
                self._render_daily_stats(stdscr, max_y, max_x)
            elif self.view == "WEEKLY":
                self._render_weekly_stats(stdscr, max_y, max_x)
            elif self.view == "MONTHLY":
                self._render_monthly_stats(stdscr, max_y, max_x)
            self._render_footer(stdscr, max_y, max_x)

            if self.mode == "HELP":
                self._render_help_modal(stdscr, max_y, max_x)
            elif self.mode == "CONFIRM_DELETE":
                self._render_confirm_delete_modal(stdscr, max_y, max_x)
            elif self.mode == "EDIT_HISTORY":
                self._render_edit_history_modal(stdscr, max_y, max_x)
            elif self.mode == "PICK_DESC":
                self._render_pick_desc_modal(stdscr, max_y, max_x)
            elif self.mode == "DAY_DETAIL":
                self._render_day_detail_modal(stdscr, max_y, max_x)

            stdscr.refresh()

            # Handle Input
            try:
                raw = stdscr.get_wch()
                ch = ord(raw) if isinstance(raw, str) and ord(raw) < 256 else raw
            except curses.error:
                continue

            if self.mode == "HELP":
                if ch in (27, ord('q'), ord('?'), ord(' '), 10, 13):
                    self.mode = "NORMAL"
                continue

            if self.mode == "CONFIRM_DELETE":
                if ch in (ord('y'), ord('Y')):
                    if self.pending_delete_id:
                        self.core.delete_entry(self.pending_delete_id)
                        self.set_status(f"Entry #{self.pending_delete_id} deleted.")
                    self.pending_delete_id = None
                    self.mode = "NORMAL"
                elif ch in (ord('n'), ord('N'), 27, ord('q')):
                    self.pending_delete_id = None
                    self.set_status("Deletion cancelled.")
                    self.mode = "NORMAL"
                continue

            if self.mode == "EDIT_HISTORY":
                self._handle_edit_history_key(ch)
                continue

            if self.mode == "PICK_DESC":
                self._handle_pick_desc_key(ch)
                continue

            if self.mode == "DAY_DETAIL":
                self._handle_day_detail_key(ch)
                continue

            if self.mode == "NORMAL":
                if not self._handle_normal_key(ch):
                    break
            elif self.mode == "INSERT":
                self._handle_insert_key(ch)

    def _render_header(self, stdscr, max_y: int, max_x: int):
        title = " ⚡ VLOGGER "
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        
        # Draw top banner
        try:
            stdscr.addstr(0, 2, title, curses.color_pair(1) | curses.A_BOLD)
            if max_x - len(now_str) - 3 > len(title) + 5:
                stdscr.addstr(0, max_x - len(now_str) - 2, now_str, curses.color_pair(9) | curses.A_DIM)
        except curses.error:
            pass

    def _render_timer_and_controls(self, stdscr, max_y: int, max_x: int):
        box_y = 1
        box_x = 2
        box_w = max_x - 4
        box_h = 8
        self._draw_box(stdscr, box_y, box_x, box_h, box_w, title="Active Tracker", color_pair=1)

        is_running = self.active_entry is not None
        
        # 1. Status badge & Timer Readout
        status_text = " ● RUNNING " if is_running else " ■ STOPPED "
        status_color = curses.color_pair(2) if is_running else curses.color_pair(3)
        
        elapsed_sec = self.active_entry.calculate_duration() if is_running else 0
        timer_str = TimeEntry.format_duration(elapsed_sec)
        
        try:
            stdscr.addstr(box_y + 1, box_x + 3, status_text, status_color | curses.A_BOLD | curses.A_REVERSE)
            stdscr.addstr(box_y + 1, box_x + 18, f"Elapsed: {timer_str}", curses.color_pair(4) | curses.A_BOLD)

            # If running, show when it started
            if is_running and self.active_entry.start_time:
                try:
                    s_dt = datetime.fromisoformat(self.active_entry.start_time)
                    started_str = f"(since {s_dt.strftime('%H:%M:%S')})"
                    started_x = box_x + 38
                    available = box_x + box_w - 1 - started_x
                    if available > 0:
                        stdscr.addstr(box_y + 1, started_x, self._fit_text(started_str, available), curses.color_pair(9) | curses.A_DIM)
                except Exception:
                    pass
        except curses.error:
            pass

        # 2. Description field
        desc_label = "Description: "
        field_x = box_x + 3 + len(desc_label)
        field_w = max(10, box_w - len(desc_label) - 6)
        
        display_desc, cursor_in_field = self._field_view(self.desc_buffer, self.cursor_pos, field_w)

        try:
            stdscr.addstr(box_y + 3, box_x + 3, desc_label, curses.color_pair(9) | curses.A_BOLD)
            field_attr = curses.color_pair(7) if self.mode == "INSERT" else curses.color_pair(9) | curses.A_UNDERLINE
            
            # Draw input field area
            stdscr.addstr(box_y + 3, field_x, self._fit_text(display_desc, field_w, pad=True), field_attr)
            
            if self.mode == "INSERT":
                # Show cursor inside field
                cursor_disp_x = field_x + cursor_in_field
                char_under = ' ' if self.cursor_pos >= len(self.desc_buffer) else self.desc_buffer[self.cursor_pos]
                if self._cell_width(char_under) > field_w - cursor_in_field:
                    char_under = ' '
                stdscr.addch(box_y + 3, cursor_disp_x, char_under, curses.A_REVERSE | curses.A_BLINK)
        except curses.error:
            pass

        # 3. Action Buttons
        btn_y = box_y + 5
        try:
            if is_running:
                stop_btn = " [s: STOP] "
                stdscr.addstr(btn_y, box_x + 3, stop_btn, curses.color_pair(6) | curses.A_BOLD)
            else:
                start_btn = " [s: START] "
                stdscr.addstr(btn_y, box_x + 3, start_btn, curses.color_pair(5) | curses.A_BOLD)

            btn_edit = " [i: Edit] "
            btn_pick = " [p: Pick Past] "
            btn_def = f" [d: Last Desc] "

            curr_bx = box_x + 18
            stdscr.addstr(btn_y, curr_bx, btn_edit, curses.color_pair(1) | curses.A_BOLD)
            curr_bx += len(btn_edit) + 1

            if curr_bx + len(btn_pick) < box_x + box_w - 2:
                stdscr.addstr(btn_y, curr_bx, btn_pick, curses.color_pair(4) | curses.A_BOLD)
                curr_bx += len(btn_pick) + 1

            if curr_bx + len(btn_def) < box_x + box_w - 2:
                stdscr.addstr(btn_y, curr_bx, btn_def, curses.color_pair(9))
                curr_bx += len(btn_def) + 1
        except curses.error:
            pass

    def _render_history_table(self, stdscr, max_y: int, max_x: int):
        box_y = 9
        box_x = 2
        box_w = max_x - 4
        box_h = max_y - box_y - 2
        
        if box_h < 5:
            return

        self._draw_box(stdscr, box_y, box_x, box_h, box_w, title="", color_pair=1)
        self._render_box_tabs(stdscr, box_y, box_x, box_w)

        # Header columns
        col_start = box_x + 2
        try:
            if box_w < 65:
                header_str = f"  {'ID':<5} {'START':<11} {'DURATION':<8} {'DESCRIPTION'}"
            else:
                header_str = f"  {'ID':<5} {'START':^11} {'END':<10} {'DURATION':<10} {'DESCRIPTION'}"
            stdscr.addstr(box_y + 1, col_start, header_str[:box_w - 4], curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(box_y + 2, col_start, "─" * (box_w - 4), curses.color_pair(1) | curses.A_DIM)
        except curses.error:
            pass

        visible_rows = box_h - 4
        if not self.entries:
            try:
                stdscr.addstr(box_y + 3, col_start, self._fit_text("No entries yet. Press 's' to start tracking your work!", box_w - 4), curses.color_pair(9) | curses.A_DIM)
            except curses.error:
                pass
            return

        # Adjust scrolling
        if self.selected_idx < self.history_offset:
            self.history_offset = self.selected_idx
        elif self.selected_idx >= self.history_offset + visible_rows:
            self.history_offset = self.selected_idx - visible_rows + 1

        for row_i in range(visible_rows):
            entry_idx = self.history_offset + row_i
            if entry_idx >= len(self.entries):
                break
            
            entry = self.entries[entry_idx]
            is_sel = (entry_idx == self.selected_idx) and (self.mode == "NORMAL")
            
            # Format columns
            eid = f"#{entry.id}"
            
            # Start / End time formatting
            try:
                s_dt = datetime.fromisoformat(entry.start_time)
                start_fmt = s_dt.strftime("%d.%m %H:%M")
            except Exception:
                start_fmt = entry.start_time[:10]

            if entry.is_active:
                end_fmt = "[Active]"
                dur_fmt = TimeEntry.format_duration(entry.calculate_duration())
            else:
                try:
                    e_dt = datetime.fromisoformat(entry.end_time)
                    end_fmt = e_dt.strftime("%H:%M")
                except Exception:
                    end_fmt = "-"
                dur_fmt = TimeEntry.format_duration(entry.calculate_duration())

            desc = entry.description
            if box_w < 65:
                row_str = f"{'>' if is_sel else ' '} {eid:<5} {start_fmt:<11} {dur_fmt:<8} {desc}"
            else:
                row_str = f"{'>' if is_sel else ' '} {eid:<5} {start_fmt:<11} {end_fmt:<10} {dur_fmt:<10} {desc}"

            row_y = box_y + 3 + row_i
            attr = curses.color_pair(7) | curses.A_BOLD if is_sel else curses.color_pair(9)
            if entry.is_active and not is_sel:
                attr = curses.color_pair(2) | curses.A_BOLD
            
            try:
                # Clear row and write
                stdscr.addstr(row_y, col_start, self._fit_text(row_str, box_w - 4, pad=True), attr)
            except curses.error:
                pass

    def _render_box_tabs(self, stdscr, box_y: int, box_x: int, box_w: int):
        """Draw interactive view tabs onto the top border of the lower panel."""
        if box_w < 70:
            tabs = [("LOGS", " [1:Log] "), ("STATS", " [2:Day] "),
                    ("WEEKLY", " [3:Wk] "), ("MONTHLY", " [4:Mo] ")]
        else:
            tabs = [("LOGS", " [1: Logs] "), ("STATS", " [2: Daily] "),
                    ("WEEKLY", " [3: Weekly] "), ("MONTHLY", " [4: Monthly] ")]

        attr_active = curses.color_pair(7) | curses.A_BOLD
        attr_inactive = curses.color_pair(1)

        try:
            cur_x = box_x + 2
            for view_key, tab_label in tabs:
                if cur_x + len(tab_label) >= box_x + box_w - 1:
                    break
                attr = attr_active if self.view == view_key else attr_inactive
                stdscr.addstr(box_y, cur_x, tab_label, attr)
                cur_x += len(tab_label) + 1

            if self.view == "LOGS":
                today_seconds = self.today_stats["total_seconds"]
                if self.active_entry and self.today_stats["count"]:
                    today_seconds += max(0, int(time.monotonic() - self._today_stats_at))
                dur_str = TimeEntry.format_duration(today_seconds)
                info = f"── (Today: {dur_str} in {self.today_stats['count']} entries)"
            elif self.view == "STATS":
                tot_str = self.daily_summary.get("compact_duration", "0s")
                days_cnt = self.daily_summary.get("active_days", 0)
                info = f"── (Total: {tot_str} across {days_cnt} active days)"
            elif self.view == "WEEKLY":
                tot_str = self.weekly_summary.get("compact_duration", "0s")
                weeks_cnt = self.weekly_summary.get("active_weeks", 0)
                info = f"── (Total: {tot_str} across {weeks_cnt} active weeks)"
            else:
                tot_str = self.monthly_summary.get("compact_duration", "0s")
                months_cnt = self.monthly_summary.get("active_months", 0)
                info = f"── (Total: {tot_str} across {months_cnt} active months)"

            if cur_x + len(info) < box_x + box_w - 2:
                stdscr.addstr(box_y, cur_x, info, curses.color_pair(9) | curses.A_DIM)
        except curses.error:
            pass

    def _render_daily_stats(self, stdscr, max_y: int, max_x: int):
        box_y = 9
        box_x = 2
        box_w = max_x - 4
        box_h = max_y - box_y - 2
        
        if box_h < 5:
            return

        self._draw_box(stdscr, box_y, box_x, box_h, box_w, title="", color_pair=1)
        self._render_box_tabs(stdscr, box_y, box_x, box_w)
        compact_height = box_h < 7
        header_y = box_y + (1 if compact_height else 3)
        first_row_y = header_y + 1

        col_start = box_x + 2
        total_str = self.daily_summary.get("compact_duration", "0s")
        avg_str = self.daily_summary.get("average_daily_formatted", "0s")
        active_days = self.daily_summary.get("active_days", 0)
        peak_day = self.daily_summary.get("peak_day", "-")
        try:
            peak_day = datetime.strptime(peak_day, "%Y-%m-%d").strftime("%d.%m.%Y")
        except Exception:
            pass
        peak_str = self.daily_summary.get("max_day_formatted", "0s")

        # Top summary stats line
        summary_line = f"  Total: {total_str} across {active_days} active days  │  Daily Avg: {avg_str}  │  Peak: {peak_day} ({peak_str})"
        if not compact_height:
            try:
                stdscr.addstr(box_y + 1, col_start, self._fit_text(summary_line, box_w - 4), curses.color_pair(4) | curses.A_BOLD)
                stdscr.addstr(box_y + 2, col_start, "─" * (box_w - 4), curses.color_pair(1) | curses.A_DIM)
            except curses.error:
                pass

        # Columns header
        if box_w >= 85:
            header_str = f"  {'DATE':<12} {'DAY':<11} {'DURATION':<10} {'ENTRIES':<9} {'ACTIVITY BAR':<12} {'TOP TASKS'}"
        elif box_w >= 65:
            header_str = f"  {'DATE':<12} {'DAY':<8} {'DURATION':<10} {'#':<5} {'TOP TASKS'}"
        else:
            header_str = f"  {'DATE':<11} {'DUR':<8} {'#':<4} {'TASKS'}"

        try:
            stdscr.addstr(header_y, col_start, self._fit_text(header_str, box_w - 4), curses.color_pair(1) | curses.A_BOLD)
        except curses.error:
            pass

        if not self.daily_stats or (len(self.daily_stats) == 1 and self.daily_stats[0]["count"] == 0):
            try:
                stdscr.addstr(first_row_y, col_start, self._fit_text("No entries yet. Press 's' to start tracking your work!", box_w - 4), curses.color_pair(9) | curses.A_DIM)
            except curses.error:
                pass
            return

        # Determine height allocation between days table and selected day breakdown
        if box_h >= 14:
            panel_height = 4  # 1 separator row + 3 task breakdown rows
            days_table_rows = max(3, box_h - 4 - panel_height - 1)
        else:
            days_table_rows = max(1, box_h - (3 if compact_height else 5))

        # Adjust scrolling
        if self.stats_selected_idx < self.stats_offset:
            self.stats_offset = self.stats_selected_idx
        elif self.stats_selected_idx >= self.stats_offset + days_table_rows:
            self.stats_offset = self.stats_selected_idx - days_table_rows + 1

        max_sec = max(self.daily_summary.get("max_day_seconds", 0), 28800)

        for row_i in range(days_table_rows):
            d_idx = self.stats_offset + row_i
            if d_idx >= len(self.daily_stats):
                break

            d = self.daily_stats[d_idx]
            is_sel = (d_idx == self.stats_selected_idx) and (self.mode == "NORMAL")

            raw_date = d["date"]
            try:
                date_str = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d.%m.%Y")
            except Exception:
                date_str = raw_date
            day_disp = d["day_abbr"]
            if d["is_today"]:
                day_disp += " [Today]"
            elif d["is_yesterday"]:
                day_disp += " [Yest]"

            dur_str = TimeEntry.format_duration(d["total_seconds"])
            cnt_str = f"{d['count']} ent"

            bar_w = 10
            ratio = min(1.0, d["total_seconds"] / max_sec) if max_sec > 0 else 0
            filled = int(round(ratio * bar_w))
            bar_str = "█" * filled + "░" * (bar_w - filled)

            top_parts = []
            for t in d.get("tasks", [])[:3]:
                dur_c = TimeEntry.format_duration(t["total_seconds"], compact=True)
                top_parts.append(f"{t['description']} ({dur_c})")
            top_tasks_str = ", ".join(top_parts) if top_parts else "-"

            if box_w >= 85:
                row_str = f"{'>' if is_sel else ' '} {date_str:<12} {day_disp:<11} {dur_str:<10} {cnt_str:<9} {bar_str:<12} {top_tasks_str}"
            elif box_w >= 65:
                row_str = f"{'>' if is_sel else ' '} {date_str:<12} {day_disp:<8} {dur_str:<10} {d['count']:<5} {top_tasks_str}"
            else:
                row_str = f"{'>' if is_sel else ' '} {date_str[:5]} {dur_str:<8} {d['count']:<4} {top_tasks_str}"

            row_y = first_row_y + row_i
            attr = curses.color_pair(7) | curses.A_BOLD if is_sel else curses.color_pair(9)
            if d["has_active"] and not is_sel:
                attr = curses.color_pair(2) | curses.A_BOLD

            try:
                stdscr.addstr(row_y, col_start, self._fit_text(row_str, box_w - 4, pad=True), attr)
            except curses.error:
                pass

        # Bottom panel for selected day breakdown (if box_h >= 14)
        if box_h >= 14 and 0 <= self.stats_selected_idx < len(self.daily_stats):
            sel_day = self.daily_stats[self.stats_selected_idx]
            panel_y = box_y + 4 + days_table_rows
            day_name_str = f" ({sel_day['day_name']})" if sel_day.get("day_name") else ""
            sel_dur_str = TimeEntry.format_duration(sel_day["total_seconds"])
            panel_title = f"── Breakdown: {sel_day['date']}{day_name_str} ─ {sel_dur_str} in {sel_day['count']} session{'s' if sel_day['count'] != 1 else ''} ──"
            
            try:
                stdscr.addstr(panel_y, col_start, panel_title[:box_w - 4], curses.color_pair(1) | curses.A_BOLD)
            except curses.error:
                pass

            tasks = sel_day.get("tasks", [])
            detail_rows = min(3, box_h - (4 + days_table_rows + 1) - 1)
            for ti in range(detail_rows):
                cur_y = panel_y + 1 + ti
                if ti < len(tasks):
                    t = tasks[ti]
                    dur_fmt = TimeEntry.format_duration(t["total_seconds"], compact=True)
                    pct = t["percentage"]
                    cnt = t["count"]
                    t_line = f"  • {t['description']}: {dur_fmt} ({pct}%) ─ {cnt} session{'s' if cnt > 1 else ''}"
                    try:
                        stdscr.addstr(cur_y, col_start, self._fit_text(t_line, box_w - 4, pad=True), curses.color_pair(9))
                    except curses.error:
                        pass
                elif ti == 0 and not tasks:
                    try:
                        stdscr.addstr(cur_y, col_start, "  • No tasks recorded for this day.".ljust(box_w - 4), curses.color_pair(9) | curses.A_DIM)
                    except curses.error:
                        pass

    def _render_weekly_stats(self, stdscr, max_y: int, max_x: int):
        box_y = 9
        box_x = 2
        box_w = max_x - 4
        box_h = max_y - box_y - 2

        if box_h < 5:
            return

        self._draw_box(stdscr, box_y, box_x, box_h, box_w, title="", color_pair=1)
        self._render_box_tabs(stdscr, box_y, box_x, box_w)
        compact_height = box_h < 7
        header_y = box_y + (1 if compact_height else 3)
        first_row_y = header_y + 1

        col_start = box_x + 2
        total_str = self.weekly_summary.get("compact_duration", "0s")
        avg_str = self.weekly_summary.get("average_weekly_formatted", "0s")
        active_weeks = self.weekly_summary.get("active_weeks", 0)
        peak_week = self.weekly_summary.get("peak_week", "-")
        peak_str = self.weekly_summary.get("max_week_formatted", "0s")

        # Top summary stats line
        summary_line = f"  Total: {total_str} across {active_weeks} active weeks  │  Weekly Avg: {avg_str}  │  Peak: {peak_week} ({peak_str})"
        if not compact_height:
            try:
                stdscr.addstr(box_y + 1, col_start, self._fit_text(summary_line, box_w - 4), curses.color_pair(4) | curses.A_BOLD)
                stdscr.addstr(box_y + 2, col_start, "─" * (box_w - 4), curses.color_pair(1) | curses.A_DIM)
            except curses.error:
                pass

        # Columns header
        if box_w >= 85:
            header_str = f"  {'WEEK':<14} {'DATE RANGE':<22} {'DURATION':<10} {'ENTRIES':<9} {'ACTIVITY BAR':<12} {'TOP TASKS'}"
        elif box_w >= 65:
            header_str = f"  {'WEEK':<12} {'DATE RANGE':<18} {'DURATION':<10} {'#':<5} {'TOP TASKS'}"
        else:
            header_str = f"  {'WEEK':<10} {'DUR':<8} {'#':<4} {'TASKS'}"

        try:
            stdscr.addstr(header_y, col_start, self._fit_text(header_str, box_w - 4), curses.color_pair(1) | curses.A_BOLD)
        except curses.error:
            pass

        if not self.weekly_stats or (len(self.weekly_stats) == 1 and self.weekly_stats[0]["count"] == 0):
            try:
                stdscr.addstr(first_row_y, col_start, self._fit_text("No weekly entries yet. Track time to see weekly statistics!", box_w - 4), curses.color_pair(9) | curses.A_DIM)
            except curses.error:
                pass
            return

        # Determine height allocation between table and selected week breakdown
        if box_h >= 14:
            panel_height = 4  # 1 separator row + 3 task breakdown rows
            table_rows = max(3, box_h - 4 - panel_height - 1)
        else:
            table_rows = max(1, box_h - (3 if compact_height else 5))

        # Adjust scrolling
        if self.weekly_selected_idx < self.weekly_offset:
            self.weekly_offset = self.weekly_selected_idx
        elif self.weekly_selected_idx >= self.weekly_offset + table_rows:
            self.weekly_offset = self.weekly_selected_idx - table_rows + 1

        max_sec = max(self.weekly_summary.get("max_week_seconds", 0), 40 * 3600)

        for row_i in range(table_rows):
            w_idx = self.weekly_offset + row_i
            if w_idx >= len(self.weekly_stats):
                break

            w = self.weekly_stats[w_idx]
            is_sel = (w_idx == self.weekly_selected_idx) and (self.mode == "NORMAL")

            week_disp = w["week"]
            if w.get("is_current_week"):
                week_disp += " [Cur]"
            elif w.get("is_last_week"):
                week_disp += " [Last]"

            range_disp = w.get("range_formatted", "")
            dur_str = TimeEntry.format_duration(w["total_seconds"])
            cnt_str = f"{w['count']} ent"

            bar_w = 10
            ratio = min(1.0, w["total_seconds"] / max_sec) if max_sec > 0 else 0
            filled = int(round(ratio * bar_w))
            bar_str = "█" * filled + "░" * (bar_w - filled)

            top_parts = []
            for t in w.get("tasks", [])[:3]:
                dur_c = TimeEntry.format_duration(t["total_seconds"], compact=True)
                top_parts.append(f"{t['description']} ({dur_c})")
            top_tasks_str = ", ".join(top_parts) if top_parts else "-"

            if box_w >= 85:
                row_str = f"{'>' if is_sel else ' '} {week_disp:<14} {range_disp:<22} {dur_str:<10} {cnt_str:<9} {bar_str:<12} {top_tasks_str}"
            elif box_w >= 65:
                row_str = f"{'>' if is_sel else ' '} {week_disp:<12} {range_disp:<18} {dur_str:<10} {w['count']:<5} {top_tasks_str}"
            else:
                row_str = f"{'>' if is_sel else ' '} {w['week']:<10} {dur_str:<8} {w['count']:<4} {top_tasks_str}"

            row_y = first_row_y + row_i
            attr = curses.color_pair(7) | curses.A_BOLD if is_sel else curses.color_pair(9)
            if w.get("has_active") and not is_sel:
                attr = curses.color_pair(2) | curses.A_BOLD

            try:
                stdscr.addstr(row_y, col_start, self._fit_text(row_str, box_w - 4, pad=True), attr)
            except curses.error:
                pass

        # Bottom panel for selected week breakdown (if box_h >= 14)
        if box_h >= 14 and 0 <= self.weekly_selected_idx < len(self.weekly_stats):
            sel_week = self.weekly_stats[self.weekly_selected_idx]
            panel_y = box_y + 4 + table_rows
            sel_dur_str = TimeEntry.format_duration(sel_week["total_seconds"])
            act_days = sel_week.get("active_days_count", 0)
            panel_title = f"── Breakdown: {sel_week['week']} ({sel_week['range_formatted']}) ─ {sel_dur_str} in {sel_week['count']} session{'s' if sel_week['count'] != 1 else ''} ({act_days} active days) ──"

            try:
                stdscr.addstr(panel_y, col_start, panel_title[:box_w - 4], curses.color_pair(1) | curses.A_BOLD)
            except curses.error:
                pass

            tasks = sel_week.get("tasks", [])
            detail_rows = min(3, box_h - (4 + table_rows + 1) - 1)
            for ti in range(detail_rows):
                cur_y = panel_y + 1 + ti
                if ti < len(tasks):
                    t = tasks[ti]
                    dur_fmt = TimeEntry.format_duration(t["total_seconds"], compact=True)
                    pct = t["percentage"]
                    cnt = t["count"]
                    t_line = f"  • {t['description']}: {dur_fmt} ({pct}%) ─ {cnt} session{'s' if cnt > 1 else ''}"
                    try:
                        stdscr.addstr(cur_y, col_start, self._fit_text(t_line, box_w - 4, pad=True), curses.color_pair(9))
                    except curses.error:
                        pass
                elif ti == 0 and not tasks:
                    try:
                        stdscr.addstr(cur_y, col_start, "  • No tasks recorded for this week.".ljust(box_w - 4), curses.color_pair(9) | curses.A_DIM)
                    except curses.error:
                        pass

    def _render_monthly_stats(self, stdscr, max_y: int, max_x: int):
        box_y = 9
        box_x = 2
        box_w = max_x - 4
        box_h = max_y - box_y - 2

        if box_h < 5:
            return

        self._draw_box(stdscr, box_y, box_x, box_h, box_w, title="", color_pair=1)
        self._render_box_tabs(stdscr, box_y, box_x, box_w)
        compact_height = box_h < 7
        header_y = box_y + (1 if compact_height else 3)
        first_row_y = header_y + 1

        col_start = box_x + 2
        total_str = self.monthly_summary.get("compact_duration", "0s")
        avg_str = self.monthly_summary.get("average_monthly_formatted", "0s")
        active_months = self.monthly_summary.get("active_months", 0)
        peak_month = self.monthly_summary.get("peak_month", "-")
        peak_str = self.monthly_summary.get("max_month_formatted", "0s")

        # Top summary stats line
        summary_line = f"  Total: {total_str} across {active_months} active months  │  Monthly Avg: {avg_str}  │  Peak: {peak_month} ({peak_str})"
        if not compact_height:
            try:
                stdscr.addstr(box_y + 1, col_start, self._fit_text(summary_line, box_w - 4), curses.color_pair(4) | curses.A_BOLD)
                stdscr.addstr(box_y + 2, col_start, "─" * (box_w - 4), curses.color_pair(1) | curses.A_DIM)
            except curses.error:
                pass

        # Columns header
        if box_w >= 85:
            header_str = f"  {'MONTH':<14} {'PERIOD':<22} {'DURATION':<10} {'ENTRIES':<9} {'ACTIVITY BAR':<12} {'TOP TASKS'}"
        elif box_w >= 65:
            header_str = f"  {'MONTH':<12} {'PERIOD':<18} {'DURATION':<10} {'#':<5} {'TOP TASKS'}"
        else:
            header_str = f"  {'MONTH':<10} {'DUR':<8} {'#':<4} {'TASKS'}"

        try:
            stdscr.addstr(header_y, col_start, self._fit_text(header_str, box_w - 4), curses.color_pair(1) | curses.A_BOLD)
        except curses.error:
            pass

        if not self.monthly_stats or (len(self.monthly_stats) == 1 and self.monthly_stats[0]["count"] == 0):
            try:
                stdscr.addstr(first_row_y, col_start, self._fit_text("No monthly entries yet. Track time to see monthly statistics!", box_w - 4), curses.color_pair(9) | curses.A_DIM)
            except curses.error:
                pass
            return

        # Determine height allocation between table and selected month breakdown
        if box_h >= 14:
            panel_height = 4  # 1 separator row + 3 task breakdown rows
            table_rows = max(3, box_h - 4 - panel_height - 1)
        else:
            table_rows = max(1, box_h - (3 if compact_height else 5))

        # Adjust scrolling
        if self.monthly_selected_idx < self.monthly_offset:
            self.monthly_offset = self.monthly_selected_idx
        elif self.monthly_selected_idx >= self.monthly_offset + table_rows:
            self.monthly_offset = self.monthly_selected_idx - table_rows + 1

        max_sec = max(self.monthly_summary.get("max_month_seconds", 0), 160 * 3600)

        for row_i in range(table_rows):
            m_idx = self.monthly_offset + row_i
            if m_idx >= len(self.monthly_stats):
                break

            m = self.monthly_stats[m_idx]
            is_sel = (m_idx == self.monthly_selected_idx) and (self.mode == "NORMAL")

            month_disp = m["month"]
            if m.get("is_current_month"):
                month_disp += " [Cur]"
            elif m.get("is_last_month"):
                month_disp += " [Last]"

            period_disp = f"{m.get('month_abbr', m['month'])} ({m.get('active_days_count', 0)}d)"
            dur_str = TimeEntry.format_duration(m["total_seconds"])
            cnt_str = f"{m['count']} ent"

            bar_w = 10
            ratio = min(1.0, m["total_seconds"] / max_sec) if max_sec > 0 else 0
            filled = int(round(ratio * bar_w))
            bar_str = "█" * filled + "░" * (bar_w - filled)

            top_parts = []
            for t in m.get("tasks", [])[:3]:
                dur_c = TimeEntry.format_duration(t["total_seconds"], compact=True)
                top_parts.append(f"{t['description']} ({dur_c})")
            top_tasks_str = ", ".join(top_parts) if top_parts else "-"

            if box_w >= 85:
                row_str = f"{'>' if is_sel else ' '} {month_disp:<14} {period_disp:<22} {dur_str:<10} {cnt_str:<9} {bar_str:<12} {top_tasks_str}"
            elif box_w >= 65:
                row_str = f"{'>' if is_sel else ' '} {month_disp:<12} {period_disp:<18} {dur_str:<10} {m['count']:<5} {top_tasks_str}"
            else:
                row_str = f"{'>' if is_sel else ' '} {m['month']:<10} {dur_str:<8} {m['count']:<4} {top_tasks_str}"

            row_y = first_row_y + row_i
            attr = curses.color_pair(7) | curses.A_BOLD if is_sel else curses.color_pair(9)
            if m.get("has_active") and not is_sel:
                attr = curses.color_pair(2) | curses.A_BOLD

            try:
                stdscr.addstr(row_y, col_start, self._fit_text(row_str, box_w - 4, pad=True), attr)
            except curses.error:
                pass

        # Bottom panel for selected month breakdown (if box_h >= 14)
        if box_h >= 14 and 0 <= self.monthly_selected_idx < len(self.monthly_stats):
            sel_month = self.monthly_stats[self.monthly_selected_idx]
            panel_y = box_y + 4 + table_rows
            sel_dur_str = TimeEntry.format_duration(sel_month["total_seconds"])
            act_days = sel_month.get("active_days_count", 0)
            panel_title = f"── Breakdown: {sel_month['month_name']} ({sel_month['range_formatted']}) ─ {sel_dur_str} in {sel_month['count']} session{'s' if sel_month['count'] != 1 else ''} ({act_days} active days) ──"

            try:
                stdscr.addstr(panel_y, col_start, panel_title[:box_w - 4], curses.color_pair(1) | curses.A_BOLD)
            except curses.error:
                pass

            tasks = sel_month.get("tasks", [])
            detail_rows = min(3, box_h - (4 + table_rows + 1) - 1)
            for ti in range(detail_rows):
                cur_y = panel_y + 1 + ti
                if ti < len(tasks):
                    t = tasks[ti]
                    dur_fmt = TimeEntry.format_duration(t["total_seconds"], compact=True)
                    pct = t["percentage"]
                    cnt = t["count"]
                    t_line = f"  • {t['description']}: {dur_fmt} ({pct}%) ─ {cnt} session{'s' if cnt > 1 else ''}"
                    try:
                        stdscr.addstr(cur_y, col_start, self._fit_text(t_line, box_w - 4, pad=True), curses.color_pair(9))
                    except curses.error:
                        pass
                elif ti == 0 and not tasks:
                    try:
                        stdscr.addstr(cur_y, col_start, "  • No tasks recorded for this month.".ljust(box_w - 4), curses.color_pair(9) | curses.A_DIM)
                    except curses.error:
                        pass

    def _render_day_detail_modal(self, stdscr, max_y: int, max_x: int):
        if not self.selected_day_detail:
            self.mode = "NORMAL"
            return

        modal_w = self._modal_width(74, max_x)
        modal_h = min(20, max_y - 2)
        modal_y = (max_y - modal_h) // 2
        modal_x = (max_x - modal_w) // 2

        d = self.selected_day_detail
        if "week" in d:
            title = f"Week Details: {d['week']} ({d.get('range_formatted', '')})"
        elif "month" in d:
            title = f"Month Details: {d.get('month_name', d['month'])} ({d.get('range_formatted', '')})"
        else:
            raw_date = d.get("date", "")
            try:
                date_str = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d.%m.%Y")
            except Exception:
                date_str = raw_date
            day_name = d.get("day_name", "")
            title = f"Day Details: {date_str} ({day_name})"
        dur_str = TimeEntry.format_duration(d["total_seconds"])
        count = d["count"]
        self._draw_box(
            stdscr,
            modal_y,
            modal_x,
            modal_h,
            modal_w,
            title=title,
            color_pair=11,
            fill=True,
            fill_pair=10,
        )

        try:
            # Summary info
            sub = f"Total Time: {dur_str} across {count} entry{'s' if count != 1 else ''}"
            stdscr.addstr(modal_y + 2, modal_x + 3, sub[:modal_w - 6], curses.color_pair(11) | curses.A_BOLD)
            stdscr.addstr(modal_y + 3, modal_x + 3, "─" * (modal_w - 6), curses.color_pair(10) | curses.A_DIM)

            # Entries table header
            eh = f"  {'ID':<5} {'START':<8} {'END':<8} {'DURATION':<9} {'DESCRIPTION'}"
            stdscr.addstr(modal_y + 4, modal_x + 3, eh[:modal_w - 6], curses.color_pair(13) | curses.A_BOLD)

            entries = d.get("entries", [])
            visible_entries = max(2, min(len(entries), modal_h - 10))

            # Adjust scrolling
            if self.day_detail_offset > len(entries) - visible_entries:
                self.day_detail_offset = max(0, len(entries) - visible_entries)

            for ei in range(visible_entries):
                idx = self.day_detail_offset + ei
                if idx >= len(entries):
                    break
                e = entries[idx]
                eid = f"#{e.id}"
                try:
                    s_dt = datetime.fromisoformat(e.start_time)
                    s_fmt = s_dt.strftime("%H:%M")
                except Exception:
                    s_fmt = e.start_time[:5]

                if e.is_active:
                    e_fmt = "Active"
                else:
                    try:
                        e_dt = datetime.fromisoformat(e.end_time)
                        e_fmt = e_dt.strftime("%H:%M")
                    except Exception:
                        e_fmt = "-"

                e_dur = TimeEntry.format_duration(e.calculate_duration())
                e_line = f"  {eid:<5} {s_fmt:<8} {e_fmt:<8} {e_dur:<9} {e.description}"
                row_y = modal_y + 5 + ei
                attr = curses.color_pair(2) if e.is_active else curses.color_pair(10)
                stdscr.addstr(row_y, modal_x + 3, self._fit_text(e_line, modal_w - 6, pad=True), attr)

            # Task breakdown footer
            tasks_y = modal_y + 5 + visible_entries + 1
            if tasks_y < modal_y + modal_h - 2:
                tasks_info = ", ".join(f"{t['description']} ({t['percentage']}%)" for t in d.get("tasks", [])[:3])
                if tasks_info:
                    stdscr.addstr(tasks_y, modal_x + 3, self._fit_text("Tasks: " + tasks_info, modal_w - 6), curses.color_pair(10) | curses.A_DIM)

            hint = "Press Esc, Enter, Space, or q to close"
            stdscr.addstr(modal_y + modal_h - 2, modal_x + (modal_w - len(hint)) // 2, hint, curses.color_pair(13) | curses.A_DIM)
        except curses.error:
            pass

    def _handle_day_detail_key(self, ch: int):
        if ch in (27, ord('q'), ord('Q'), 10, 13, curses.KEY_ENTER, ord(' ')):
            self.mode = "NORMAL"
            return
        elif ch in (ord('j'), curses.KEY_DOWN):
            entries = self.selected_day_detail.get("entries", []) if self.selected_day_detail else []
            if self.day_detail_offset < len(entries) - 1:
                self.day_detail_offset += 1
        elif ch in (ord('k'), curses.KEY_UP):
            if self.day_detail_offset > 0:
                self.day_detail_offset -= 1

    def _render_footer(self, stdscr, max_y: int, max_x: int):
        footer_y = max_y - 1
        mode_str = f"-- {self.mode} --"
        mode_color = curses.color_pair(7) if self.mode == "INSERT" else curses.color_pair(1) | curses.A_BOLD

        # Short help hints based on mode
        if self.mode == "INSERT":
            hints = "Enter: Accept & Save | Esc: Cancel | Tab: Pick Past | Ctrl-u: Clear"
        elif self.mode == "EDIT_HISTORY":
            hints = "Enter: Save Changes | Esc: Cancel | Ctrl-u: Clear"
        elif self.mode == "PICK_DESC":
            hints = "Enter: Choose Task | j/k or ↓/↑: Nav | Esc: Cancel"
        elif self.mode == "DAY_DETAIL":
            hints = "Esc / Enter / q: Close | j/k or ↓/↑: Scroll"
        else:
            if self.view == "LOGS":
                hints = "h/l: Switch Views | s: Start/Stop | i: Edit | p: Pick | y: Yank | e: Rename | ?: Help | q: Quit"
            else:
                hints = "h/l: Switch Views | Enter: View Details | j/k: Nav | y: Yank | s: Start/Stop | ?: Help | q: Quit"

        # Check if status message is still active
        if time.time() < self.status_message_time:
            display_msg = self.status_message
        else:
            display_msg = hints

        try:
            stdscr.addstr(footer_y, 2, mode_str, mode_color)
            message_x = max(16, len(mode_str) + 4)
            stdscr.addstr(footer_y, message_x, self._fit_text(display_msg, max_x - message_x - 2), curses.color_pair(9))
        except curses.error:
            pass

    def _render_help_modal(self, stdscr, max_y: int, max_x: int):
        modal_w = self._modal_width(68, max_x)
        modal_h = min(20, max_y - 2)
        modal_y = (max_y - modal_h) // 2
        modal_x = (max_x - modal_w) // 2

        self._draw_box(
            stdscr,
            modal_y,
            modal_x,
            modal_h,
            modal_w,
            title="Help & Vim Bindings",
            color_pair=11,
            fill=True,
            fill_pair=10,
        )

        lines = [
            ("h / l or ←/→", "Switch views left / right (Logs, Daily, Weekly, Monthly)"),
            ("Tab or v", "Cycle forward through Views"),
            ("Shift-Tab", "Cycle backward through Views"),
            ("1 / 2 / 3 / 4", "Switch view directly (Logs, Daily, Weekly, Monthly)"),
            ("s or Space", "Toggle Start / Stop timer"),
            ("i or a", "Insert mode: Edit active tracker description"),
            ("p", "Pick from list of unique past tasks"),
            ("y", "Yank highlighted history/task to active tracker"),
            ("e or Enter", "Edit selected log entry / View period details"),
            ("d", "Reset active description to last used task"),
            ("D", "Save current active description as new default"),
            ("j / k or ↓/↑", "Navigate history entries or summary statistics"),
            ("g / G", "Jump to top / bottom of current list"),
            ("x", "Delete selected history entry (with confirm)"),
            ("r", "Refresh data from database"),
            ("q", "Quit TUI (active timer continues in background)"),
            ("?", "Toggle this help modal"),
        ]
        if max_x < 70:
            lines = [
                ("h/l or ←/→", "Switch views"),
                ("Tab / v", "Next view; Shift-Tab: back"),
                ("1 / 2 / 3 / 4", "Open a view directly"),
                ("s / Space", "Start or stop timer"),
                ("i / a", "Edit task description"),
                ("p", "Pick a past task"),
                ("j/k or ↓/↑", "Move selection"),
                ("Enter / e", "Edit entry or show details"),
                ("x", "Delete selected log"),
                ("?", "Close help"),
            ]

        try:
            for i, (key, desc) in enumerate(lines[:modal_h - 4]):
                row_y = modal_y + 2 + i
                stdscr.addstr(row_y, modal_x + 3, f"{key:<15}", curses.color_pair(11) | curses.A_BOLD)
                stdscr.addstr(row_y, modal_x + 19, self._fit_text(desc, modal_w - 22), curses.color_pair(10))
            
            hint = "Press Esc, Space, or q to close"
            stdscr.addstr(modal_y + modal_h - 2, modal_x + (modal_w - len(hint)) // 2, hint, curses.color_pair(13) | curses.A_DIM)
        except curses.error:
            pass

    def _render_confirm_delete_modal(self, stdscr, max_y: int, max_x: int):
        modal_w = self._modal_width(50, max_x)
        modal_h = 7
        modal_y = (max_y - modal_h) // 2
        modal_x = (max_x - modal_w) // 2

        self._draw_box(
            stdscr,
            modal_y,
            modal_x,
            modal_h,
            modal_w,
            title="Confirm Deletion",
            color_pair=12,
            fill=True,
            fill_pair=10,
        )
        try:
            msg = f"Delete entry #{self.pending_delete_id}?"
            stdscr.addstr(modal_y + 2, modal_x + (modal_w - len(msg)) // 2, msg, curses.color_pair(12) | curses.A_BOLD)
            prompt = "Press 'y' to confirm, 'n' or Esc to cancel"
            stdscr.addstr(modal_y + 4, modal_x + (modal_w - len(prompt)) // 2, prompt, curses.color_pair(10))
        except curses.error:
            pass

    def _render_edit_history_modal(self, stdscr, max_y: int, max_x: int):
        modal_w = self._modal_width(68, max_x)
        modal_h = 8
        modal_y = (max_y - modal_h) // 2
        modal_x = (max_x - modal_w) // 2

        self._draw_box(
            stdscr,
            modal_y,
            modal_x,
            modal_h,
            modal_w,
            title=f"Edit Entry #{self.editing_entry_id}",
            color_pair=11,
            fill=True,
            fill_pair=10,
        )

        label = "Description: "
        field_x = modal_x + 3 + len(label)
        field_w = max(10, modal_w - len(label) - 6)

        display_text, cursor_in_field = self._field_view(self.edit_buffer, self.edit_cursor_pos, field_w)

        try:
            stdscr.addstr(modal_y + 2, modal_x + 3, label, curses.color_pair(10) | curses.A_BOLD)
            field_attr = curses.color_pair(7)  # Highlighted cyan background
            stdscr.addstr(modal_y + 2, field_x, self._fit_text(display_text, field_w, pad=True), field_attr)

            # Draw cursor
            cursor_disp_x = field_x + cursor_in_field
            char_under = ' ' if self.edit_cursor_pos >= len(self.edit_buffer) else self.edit_buffer[self.edit_cursor_pos]
            if self._cell_width(char_under) > field_w - cursor_in_field:
                char_under = ' '
            stdscr.addch(modal_y + 2, cursor_disp_x, char_under, curses.A_REVERSE | curses.A_BLINK)

            hints = "Enter: Save changes  |  Esc: Cancel  |  Ctrl-u: Clear"
            stdscr.addstr(modal_y + 5, modal_x + (modal_w - len(hints)) // 2, hints, curses.color_pair(10) | curses.A_DIM)
        except curses.error:
            pass

    def _handle_edit_history_key(self, ch: int):
        if ch in (27,):  # Escape
            self.mode = "NORMAL"
            self.set_status("Edit cancelled.")
            return

        elif ch in (10, 13, curses.KEY_ENTER):  # Enter key
            new_desc = self.edit_buffer.strip()
            if new_desc and self.editing_entry_id:
                self.core.update_entry(self.editing_entry_id, description=new_desc)
                self.set_status(f"Updated entry #{self.editing_entry_id}: '{new_desc}'")
            self.mode = "NORMAL"
            self.refresh_data()
            return

        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if self.edit_cursor_pos > 0:
                self.edit_buffer = self.edit_buffer[:self.edit_cursor_pos - 1] + self.edit_buffer[self.edit_cursor_pos:]
                self.edit_cursor_pos -= 1

        elif ch == curses.KEY_DC:
            if self.edit_cursor_pos < len(self.edit_buffer):
                self.edit_buffer = self.edit_buffer[:self.edit_cursor_pos] + self.edit_buffer[self.edit_cursor_pos + 1:]

        elif ch == curses.KEY_LEFT:
            if self.edit_cursor_pos > 0:
                self.edit_cursor_pos -= 1

        elif ch == curses.KEY_RIGHT:
            if self.edit_cursor_pos < len(self.edit_buffer):
                self.edit_cursor_pos += 1

        elif ch in (curses.KEY_HOME, 1):  # Ctrl-A or Home
            self.edit_cursor_pos = 0

        elif ch in (curses.KEY_END, 5):  # Ctrl-E or End
            self.edit_cursor_pos = len(self.edit_buffer)

        elif ch == 21:  # Ctrl-U (clear line)
            self.edit_buffer = ""
            self.edit_cursor_pos = 0

        elif ch == 23:  # Ctrl-W (delete word backward)
            left = self.edit_buffer[:self.edit_cursor_pos].rstrip()
            idx = left.rfind(' ')
            if idx == -1:
                self.edit_buffer = self.edit_buffer[self.edit_cursor_pos:]
                self.edit_cursor_pos = 0
            else:
                self.edit_buffer = left[:idx + 1] + self.edit_buffer[self.edit_cursor_pos:]
                self.edit_cursor_pos = idx + 1

        elif (isinstance(ch, str) and ch.isprintable()) or (isinstance(ch, int) and 32 <= ch <= 255 and chr(ch).isprintable()):
            char = ch if isinstance(ch, str) else chr(ch)
            self.edit_buffer = self.edit_buffer[:self.edit_cursor_pos] + char + self.edit_buffer[self.edit_cursor_pos:]
            self.edit_cursor_pos += 1

    def _render_pick_desc_modal(self, stdscr, max_y: int, max_x: int):
        modal_w = self._modal_width(68, max_x)
        modal_h = min(14, max_y - 4)
        modal_y = (max_y - modal_h) // 2
        modal_x = (max_x - modal_w) // 2

        self._draw_box(
            stdscr,
            modal_y,
            modal_x,
            modal_h,
            modal_w,
            title="Choose From Past Tasks",
            color_pair=11,
            fill=True,
            fill_pair=10,
        )

        visible_rows = modal_h - 4
        if not self.desc_options:
            try:
                stdscr.addstr(modal_y + 2, modal_x + 3, "No past tasks recorded yet.", curses.color_pair(10))
            except curses.error:
                pass
            return

        # Adjust scrolling
        if self.pick_idx < self.pick_offset:
            self.pick_offset = self.pick_idx
        elif self.pick_idx >= self.pick_offset + visible_rows:
            self.pick_offset = self.pick_idx - visible_rows + 1

        try:
            for row_i in range(visible_rows):
                opt_idx = self.pick_offset + row_i
                if opt_idx >= len(self.desc_options):
                    break

                item = self.desc_options[opt_idx]
                is_sel = (opt_idx == self.pick_idx)
                prefix = "> " if is_sel else "  "
                count_str = f"({item['count']}x)"

                # Format text
                max_text_w = max(5, modal_w - 6 - len(count_str) - len(prefix))
                desc_text = item["description"]
                if len(desc_text) > max_text_w:
                    desc_text = desc_text[:max_text_w - 1] + "…"

                line_str = f"{prefix}{desc_text:<{max_text_w}} {count_str}"
                row_y = modal_y + 2 + row_i
                attr = curses.color_pair(7) | curses.A_BOLD if is_sel else curses.color_pair(10)

                stdscr.addstr(row_y, modal_x + 2, self._fit_text(line_str, modal_w - 4, pad=True), attr)

            hints = "Enter: Choose  |  j/k or ↓/↑: Nav  |  Esc: Cancel"
            stdscr.addstr(modal_y + modal_h - 2, modal_x + (modal_w - len(hints)) // 2, hints, curses.color_pair(13) | curses.A_DIM)
        except curses.error:
            pass

    def _handle_pick_desc_key(self, ch: int):
        if ch in (27, ord('q'), ord('Q')):  # Escape or q
            self.mode = "NORMAL"
            self.set_status("Selection cancelled.")
            return

        elif ch in (ord('j'), curses.KEY_DOWN):
            if self.desc_options and self.pick_idx < len(self.desc_options) - 1:
                self.pick_idx += 1

        elif ch in (ord('k'), curses.KEY_UP):
            if self.pick_idx > 0:
                self.pick_idx -= 1

        elif ch in (ord('g'), curses.KEY_HOME):
            self.pick_idx = 0

        elif ch in (ord('G'), curses.KEY_END):
            if self.desc_options:
                self.pick_idx = len(self.desc_options) - 1

        elif ch in (10, 13, curses.KEY_ENTER, ord(' ')):
            if self.desc_options and 0 <= self.pick_idx < len(self.desc_options):
                chosen = self.desc_options[self.pick_idx]["description"]
                self.desc_buffer = chosen
                self.cursor_pos = len(self.desc_buffer)
                if self.active_entry:
                    self.core.update_entry(self.active_entry.id, description=chosen)
                    self.set_status(f"Updated active task description to: '{chosen}'")
                else:
                    self.set_status(f"Selected task: '{chosen}'. Press 's' to start.")
            self.mode = "NORMAL"
            self.refresh_data()

    def _handle_normal_key(self, ch: int) -> bool:
        """Returns False if quit requested."""
        if ch in (ord('q'), ord('Q')):
            self.core.wait_for_sync(timeout=3.0)
            return False

        elif ch in (ord('s'), ord(' ')):  # Toggle Start / Stop
            desc = self.desc_buffer.strip() or self.default_desc
            result = self.core.toggle(description=desc)
            self.set_status(result["message"])

        elif ch in (ord('\t'), ord('v'), ord('V'), ord('l'), ord('L'), curses.KEY_RIGHT):
            order = ["LOGS", "STATS", "WEEKLY", "MONTHLY"]
            cur_i = order.index(self.view) if self.view in order else 0
            self.view = order[(cur_i + 1) % len(order)]
            names = {"LOGS": "Recent Logs", "STATS": "Daily Stats", "WEEKLY": "Weekly Stats", "MONTHLY": "Monthly Stats"}
            self.set_status(f"Switched to {names.get(self.view, self.view)} view.")

        elif ch in (ord('h'), ord('H'), curses.KEY_LEFT, getattr(curses, 'KEY_BTAB', 353)):
            order = ["LOGS", "STATS", "WEEKLY", "MONTHLY"]
            cur_i = order.index(self.view) if self.view in order else 0
            self.view = order[(cur_i - 1 + len(order)) % len(order)]
            names = {"LOGS": "Recent Logs", "STATS": "Daily Stats", "WEEKLY": "Weekly Stats", "MONTHLY": "Monthly Stats"}
            self.set_status(f"Switched to {names.get(self.view, self.view)} view.")

        elif ch == ord('1'):
            self.view = "LOGS"
            self.set_status("Switched to Recent Logs view.")

        elif ch == ord('2'):
            self.view = "STATS"
            self.set_status("Switched to Daily Stats view.")

        elif ch == ord('3'):
            self.view = "WEEKLY"
            self.set_status("Switched to Weekly Stats view.")

        elif ch == ord('4'):
            self.view = "MONTHLY"
            self.set_status("Switched to Monthly Stats view.")

        elif ch in (ord('i'), ord('I'), ord('a'), ord('A')):
            self.mode = "INSERT"
            self.cursor_pos = len(self.desc_buffer)

        elif ch in (ord('p'), ord('P')):
            self.desc_options = self.core.get_unique_descriptions()
            if not self.desc_options:
                self.set_status("No past tasks recorded yet.")
            else:
                self.pick_idx = 0
                self.pick_offset = 0
                self.mode = "PICK_DESC"

        elif ch in (ord('y'), ord('Y')):
            if self.view == "LOGS":
                if self.entries and 0 <= self.selected_idx < len(self.entries):
                    chosen = self.entries[self.selected_idx].description
                    self.desc_buffer = chosen
                    self.cursor_pos = len(self.desc_buffer)
                    if self.active_entry:
                        self.core.update_entry(self.active_entry.id, description=chosen)
                        self.set_status(f"Yanked to active task: '{chosen}'")
                    else:
                        self.set_status(f"Yanked description: '{chosen}'")
            else:
                chosen = None
                if self.view == "STATS" and self.daily_stats and 0 <= self.stats_selected_idx < len(self.daily_stats):
                    tasks = self.daily_stats[self.stats_selected_idx].get("tasks", [])
                    if tasks:
                        chosen = tasks[0]["description"]
                elif self.view == "WEEKLY" and self.weekly_stats and 0 <= self.weekly_selected_idx < len(self.weekly_stats):
                    tasks = self.weekly_stats[self.weekly_selected_idx].get("tasks", [])
                    if tasks:
                        chosen = tasks[0]["description"]
                elif self.view == "MONTHLY" and self.monthly_stats and 0 <= self.monthly_selected_idx < len(self.monthly_stats):
                    tasks = self.monthly_stats[self.monthly_selected_idx].get("tasks", [])
                    if tasks:
                        chosen = tasks[0]["description"]

                if chosen:
                    self.desc_buffer = chosen
                    self.cursor_pos = len(self.desc_buffer)
                    if self.active_entry:
                        self.core.update_entry(self.active_entry.id, description=chosen)
                        self.set_status(f"Yanked top task '{chosen}' to active task.")
                    else:
                        self.set_status(f"Yanked description: '{chosen}'")

        elif ch in (10, 13, curses.KEY_ENTER):
            if self.view == "LOGS":
                if self.entries and 0 <= self.selected_idx < len(self.entries):
                    target = self.entries[self.selected_idx]
                    self.editing_entry_id = target.id
                    self.edit_buffer = target.description
                    self.edit_cursor_pos = len(self.edit_buffer)
                    self.mode = "EDIT_HISTORY"
            elif self.view == "STATS":
                if self.daily_stats and 0 <= self.stats_selected_idx < len(self.daily_stats):
                    self.selected_day_detail = self.daily_stats[self.stats_selected_idx]
                    self.day_detail_offset = 0
                    self.mode = "DAY_DETAIL"
            elif self.view == "WEEKLY":
                if self.weekly_stats and 0 <= self.weekly_selected_idx < len(self.weekly_stats):
                    self.selected_day_detail = self.weekly_stats[self.weekly_selected_idx]
                    self.day_detail_offset = 0
                    self.mode = "DAY_DETAIL"
            elif self.view == "MONTHLY":
                if self.monthly_stats and 0 <= self.monthly_selected_idx < len(self.monthly_stats):
                    self.selected_day_detail = self.monthly_stats[self.monthly_selected_idx]
                    self.day_detail_offset = 0
                    self.mode = "DAY_DETAIL"

        elif ch in (ord('e'), ord('E'), ord('c')):
            if self.view == "LOGS":
                if self.entries and 0 <= self.selected_idx < len(self.entries):
                    target = self.entries[self.selected_idx]
                    self.editing_entry_id = target.id
                    self.edit_buffer = target.description
                    self.edit_cursor_pos = len(self.edit_buffer)
                    self.mode = "EDIT_HISTORY"
            else:
                self.set_status("Cannot rename summary row. Switch to Logs view (1) to edit.")

        elif ch == ord('d'):  # Reset to the last used description
            self.desc_buffer = self.db.get_last_description() or self.default_desc
            self.cursor_pos = len(self.desc_buffer)
            if self.active_entry:
                self.core.update_entry(self.active_entry.id, description=self.desc_buffer)
            self.set_status(f"Reset description to: '{self.desc_buffer}'")

        elif ch == ord('D'):  # Set current as default description
            new_def = self.desc_buffer.strip()
            if new_def:
                self.core.default_description = new_def
                self.default_desc = new_def
                self.set_status(f"Saved '{new_def}' as default description.")

        elif ch in (ord('j'), curses.KEY_DOWN):
            if self.view == "LOGS":
                if self.entries and self.selected_idx < len(self.entries) - 1:
                    self.selected_idx += 1
            elif self.view == "STATS":
                if self.daily_stats and self.stats_selected_idx < len(self.daily_stats) - 1:
                    self.stats_selected_idx += 1
            elif self.view == "WEEKLY":
                if self.weekly_stats and self.weekly_selected_idx < len(self.weekly_stats) - 1:
                    self.weekly_selected_idx += 1
            elif self.view == "MONTHLY":
                if self.monthly_stats and self.monthly_selected_idx < len(self.monthly_stats) - 1:
                    self.monthly_selected_idx += 1

        elif ch in (ord('k'), curses.KEY_UP):
            if self.view == "LOGS":
                if self.selected_idx > 0:
                    self.selected_idx -= 1
            elif self.view == "STATS":
                if self.stats_selected_idx > 0:
                    self.stats_selected_idx -= 1
            elif self.view == "WEEKLY":
                if self.weekly_selected_idx > 0:
                    self.weekly_selected_idx -= 1
            elif self.view == "MONTHLY":
                if self.monthly_selected_idx > 0:
                    self.monthly_selected_idx -= 1

        elif ch in (ord('g'), curses.KEY_HOME):
            if self.view == "LOGS":
                self.selected_idx = 0
            elif self.view == "STATS":
                self.stats_selected_idx = 0
            elif self.view == "WEEKLY":
                self.weekly_selected_idx = 0
            elif self.view == "MONTHLY":
                self.monthly_selected_idx = 0

        elif ch in (ord('G'), curses.KEY_END):
            if self.view == "LOGS":
                if self.entries:
                    self.selected_idx = len(self.entries) - 1
            elif self.view == "STATS":
                if self.daily_stats:
                    self.stats_selected_idx = len(self.daily_stats) - 1
            elif self.view == "WEEKLY":
                if self.weekly_stats:
                    self.weekly_selected_idx = len(self.weekly_stats) - 1
            elif self.view == "MONTHLY":
                if self.monthly_stats:
                    self.monthly_selected_idx = len(self.monthly_stats) - 1

        elif ch in (ord('x'), curses.KEY_DC):
            if self.view == "LOGS":
                if self.entries and 0 <= self.selected_idx < len(self.entries):
                    target = self.entries[self.selected_idx]
                    self.pending_delete_id = target.id
                    self.mode = "CONFIRM_DELETE"
            else:
                self.set_status("Cannot delete summary row. Switch to Logs view (1) to delete entries.")

        elif ch == ord('r'):
            self.refresh_data()
            self.set_status("Data refreshed.")

        elif ch == ord('?'):
            self.mode = "HELP"

        return True

    def _handle_insert_key(self, ch: int):
        if ch in (27,):  # Escape key
            self.mode = "NORMAL"
            return

        elif ch in (9, 16):  # Tab (9) or Ctrl-P (16) to open pick list
            self.desc_options = self.core.get_unique_descriptions()
            if self.desc_options:
                self.pick_idx = 0
                self.pick_offset = 0
                self.mode = "PICK_DESC"
            return

        elif ch in (10, 13, curses.KEY_ENTER):  # Enter key
            self.mode = "NORMAL"
            new_desc = self.desc_buffer.strip()
            if not new_desc:
                new_desc = self.default_desc
                self.desc_buffer = new_desc

            # If currently active, update the running timer description in DB immediately
            if self.active_entry:
                self.core.update_entry(self.active_entry.id, description=new_desc)
                self.set_status(f"Updated active task description to: '{new_desc}'")
            else:
                self.set_status(f"Description set to: '{new_desc}'. Press 's' to start.")

        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if self.cursor_pos > 0:
                self.desc_buffer = self.desc_buffer[:self.cursor_pos - 1] + self.desc_buffer[self.cursor_pos:]
                self.cursor_pos -= 1

        elif ch == curses.KEY_DC:  # Delete key
            if self.cursor_pos < len(self.desc_buffer):
                self.desc_buffer = self.desc_buffer[:self.cursor_pos] + self.desc_buffer[self.cursor_pos + 1:]

        elif ch == curses.KEY_LEFT:
            if self.cursor_pos > 0:
                self.cursor_pos -= 1

        elif ch == curses.KEY_RIGHT:
            if self.cursor_pos < len(self.desc_buffer):
                self.cursor_pos += 1

        elif ch in (curses.KEY_HOME, 1):  # Ctrl-A or Home
            self.cursor_pos = 0

        elif ch in (curses.KEY_END, 5):  # Ctrl-E or End
            self.cursor_pos = len(self.desc_buffer)

        elif ch == 21:  # Ctrl-U (clear line)
            self.desc_buffer = ""
            self.cursor_pos = 0

        elif ch == 23:  # Ctrl-W (delete word backward)
            left = self.desc_buffer[:self.cursor_pos].rstrip()
            idx = left.rfind(' ')
            if idx == -1:
                self.desc_buffer = self.desc_buffer[self.cursor_pos:]
                self.cursor_pos = 0
            else:
                self.desc_buffer = left[:idx + 1] + self.desc_buffer[self.cursor_pos:]
                self.cursor_pos = idx + 1

        elif (isinstance(ch, str) and ch.isprintable()) or (isinstance(ch, int) and 32 <= ch <= 255 and chr(ch).isprintable()):
            char = ch if isinstance(ch, str) else chr(ch)
            self.desc_buffer = self.desc_buffer[:self.cursor_pos] + char + self.desc_buffer[self.cursor_pos:]
            self.cursor_pos += 1


def launch_tui(db: Optional[Database] = None):
    tui = VLoggerTUI(db=db)
    tui.run()
