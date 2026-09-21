"""Terminal User Interface (TUI) for vlogger using curses.

Keyboard-first, Vim-bindings, start/stop buttons, description field with default,
and live timer ticker.
"""

import curses
import os
import sys
import time
from datetime import datetime
from typing import Optional, List

from vlogger.db import Database
from vlogger.models import TimeEntry
from vlogger.core import VLoggerCore


class VLoggerTUI:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self.core = VLoggerCore(self.db)
        
        # State
        self.mode = "NORMAL"  # "NORMAL", "INSERT", "CONFIRM_DELETE", "HELP"
        self.default_desc = self.core.default_description
        self.desc_buffer = self.default_desc
        self.cursor_pos = len(self.desc_buffer)
        
        self.selected_idx = 0
        self.history_offset = 0
        self.entries: List[TimeEntry] = []
        self.active_entry: Optional[TimeEntry] = None
        
        self.status_message = "Ready. Press 's' to start/stop, 'i' to edit description, '?' for help."
        self.status_message_time = time.time()
        self.pending_delete_id: Optional[int] = None

    def set_status(self, msg: str, duration: float = 3.0):
        self.status_message = msg
        self.status_message_time = time.time() + duration

    def refresh_data(self):
        """Reload active entry and recent entries from SQLite."""
        self.active_entry = self.db.get_active_entry()
        self.entries = self.db.list_entries(limit=50)
        self.default_desc = self.core.default_description
        
        # If active entry exists and we are not currently editing, reflect its description
        if self.active_entry and self.mode != "INSERT":
            self.desc_buffer = self.active_entry.description
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

    def _draw_box(self, stdscr, y: int, x: int, h: int, w: int, title: str = "", color_pair: int = 1):
        """Draw a box with rounded corners and optional title."""
        if h < 2 or w < 2:
            return
        
        attr = curses.color_pair(color_pair)
        try:
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
                if len(t) < w - 4:
                    stdscr.addstr(y, x + 2, t, attr | curses.A_BOLD)
        except curses.error:
            pass

    def _main_loop(self, stdscr):
        self._init_colors()
        stdscr.timeout(500)  # 500ms timeout for non-blocking key reads & timer ticking

        while True:
            self.refresh_data()
            stdscr.erase()
            max_y, max_x = stdscr.getmaxyx()

            if max_y < 16 or max_x < 55:
                # Terminal too small warning
                msg = f"Terminal too small ({max_x}x{max_y}). Min: 55x16."
                try:
                    stdscr.addstr(0, 0, msg[:max_x - 1], curses.color_pair(3) | curses.A_BOLD)
                except curses.error:
                    pass
                ch = stdscr.getch()
                if ch in (ord('q'), ord('Q')):
                    break
                continue

            # Render UI Components
            self._render_header(stdscr, max_y, max_x)
            self._render_timer_and_controls(stdscr, max_y, max_x)
            self._render_history_table(stdscr, max_y, max_x)
            self._render_footer(stdscr, max_y, max_x)

            if self.mode == "HELP":
                self._render_help_modal(stdscr, max_y, max_x)
            elif self.mode == "CONFIRM_DELETE":
                self._render_confirm_delete_modal(stdscr, max_y, max_x)

            stdscr.refresh()

            # Handle Input
            ch = stdscr.getch()
            if ch == curses.ERR:
                continue

            if self.mode == "HELP":
                if ch in (27, ord('q'), ord('?'), ord(' '), 10, 13):
                    self.mode = "NORMAL"
                continue

            if self.mode == "CONFIRM_DELETE":
                if ch in (ord('y'), ord('Y')):
                    if self.pending_delete_id:
                        self.db.delete_entry(self.pending_delete_id)
                        self.set_status(f"Entry #{self.pending_delete_id} deleted.")
                    self.pending_delete_id = None
                    self.mode = "NORMAL"
                elif ch in (ord('n'), ord('N'), 27, ord('q')):
                    self.pending_delete_id = None
                    self.set_status("Deletion cancelled.")
                    self.mode = "NORMAL"
                continue

            if self.mode == "NORMAL":
                if not self._handle_normal_key(ch):
                    break
            elif self.mode == "INSERT":
                self._handle_insert_key(ch)

    def _render_header(self, stdscr, max_y: int, max_x: int):
        title = " ⚡ VLOGGER "
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
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
                    stdscr.addstr(box_y + 1, box_x + 38, started_str[:max_x - box_x - 40], curses.color_pair(9) | curses.A_DIM)
                except Exception:
                    pass
        except curses.error:
            pass

        # 2. Description field
        desc_label = "Description: "
        field_x = box_x + 3 + len(desc_label)
        field_w = max(10, box_w - len(desc_label) - 6)
        
        display_desc = self.desc_buffer
        if len(display_desc) > field_w:
            display_desc = display_desc[-(field_w - 1):]

        try:
            stdscr.addstr(box_y + 3, box_x + 3, desc_label, curses.color_pair(9) | curses.A_BOLD)
            field_attr = curses.color_pair(7) if self.mode == "INSERT" else curses.color_pair(9) | curses.A_UNDERLINE
            
            # Draw input field area
            padded_text = display_desc.ljust(field_w)
            stdscr.addstr(box_y + 3, field_x, padded_text[:field_w], field_attr)
            
            if self.mode == "INSERT":
                # Show cursor inside field
                cursor_disp_x = field_x + min(self.cursor_pos, field_w - 1)
                stdscr.addch(box_y + 3, cursor_disp_x, ' ' if self.cursor_pos >= len(self.desc_buffer) else self.desc_buffer[self.cursor_pos], curses.A_REVERSE | curses.A_BLINK)
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

            btn_edit = " [i: Edit Desc] "
            btn_def = f" [d: Reset Default] "
            btn_save_def = f" [D: Save as Default] "

            curr_bx = box_x + 18
            stdscr.addstr(btn_y, curr_bx, btn_edit, curses.color_pair(1) | curses.A_BOLD)
            curr_bx += len(btn_edit) + 1

            if curr_bx + len(btn_def) < box_x + box_w - 2:
                stdscr.addstr(btn_y, curr_bx, btn_def, curses.color_pair(9))
                curr_bx += len(btn_def) + 1

            if curr_bx + len(btn_save_def) < box_x + box_w - 2:
                stdscr.addstr(btn_y, curr_bx, btn_save_def, curses.color_pair(9))
        except curses.error:
            pass

    def _render_history_table(self, stdscr, max_y: int, max_x: int):
        box_y = 9
        box_x = 2
        box_w = max_x - 4
        box_h = max_y - box_y - 2
        
        if box_h < 5:
            return

        today_stats = self.db.get_stats_for_today()
        today_dur = TimeEntry.format_duration(today_stats["total_seconds"])
        today_count = today_stats["count"]
        table_title = f"Recent Work Logs (Today: {today_dur} in {today_count} entries)"

        self._draw_box(stdscr, box_y, box_x, box_h, box_w, title=table_title, color_pair=1)

        # Header columns
        col_start = box_x + 2
        try:
            header_str = f"  {'ID':<5} {'START':<10} {'END':<10} {'DURATION':<10} {'DESCRIPTION'}"
            stdscr.addstr(box_y + 1, col_start, header_str[:box_w - 4], curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(box_y + 2, col_start, "─" * (box_w - 4), curses.color_pair(1) | curses.A_DIM)
        except curses.error:
            pass

        visible_rows = box_h - 4
        if not self.entries:
            try:
                stdscr.addstr(box_y + 3, col_start + 2, "No entries yet. Press 's' to start tracking your work!", curses.color_pair(9) | curses.A_DIM)
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
                start_fmt = s_dt.strftime("%m-%d %H:%M")
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
            row_str = f"{'>' if is_sel else ' '} {eid:<5} {start_fmt:<10} {end_fmt:<10} {dur_fmt:<10} {desc}"

            row_y = box_y + 3 + row_i
            attr = curses.color_pair(7) | curses.A_BOLD if is_sel else curses.color_pair(9)
            if entry.is_active and not is_sel:
                attr = curses.color_pair(2) | curses.A_BOLD
            
            try:
                # Clear row and write
                stdscr.addstr(row_y, col_start, row_str[:box_w - 4].ljust(box_w - 4), attr)
            except curses.error:
                pass

    def _render_footer(self, stdscr, max_y: int, max_x: int):
        footer_y = max_y - 1
        mode_str = f"-- {self.mode} --"
        mode_color = curses.color_pair(7) if self.mode == "INSERT" else curses.color_pair(1) | curses.A_BOLD

        # Short help hints based on mode
        if self.mode == "INSERT":
            hints = "Enter: Accept & Save | Esc: Cancel | Ctrl-u: Clear"
        else:
            hints = "s: Start/Stop | i: Edit | d: Default | j/k: Nav | x: Del | ?: Help | q: Quit"

        # Check if status message is still active
        if time.time() < self.status_message_time:
            display_msg = self.status_message
        else:
            display_msg = hints

        try:
            stdscr.addstr(footer_y, 2, mode_str, mode_color)
            stdscr.addstr(footer_y, 16, display_msg[:max_x - 18], curses.color_pair(9))
        except curses.error:
            pass

    def _render_help_modal(self, stdscr, max_y: int, max_x: int):
        modal_w = min(68, max_x - 6)
        modal_h = min(16, max_y - 4)
        modal_y = (max_y - modal_h) // 2
        modal_x = (max_x - modal_w) // 2

        self._draw_box(stdscr, modal_y, modal_x, modal_h, modal_w, title="Help & Vim Bindings", color_pair=4)

        lines = [
            ("s or Space", "Toggle Start / Stop timer"),
            ("i, a, or e", "Insert mode: Edit description input field"),
            ("d", "Reset description to default ('" + self.default_desc + "')"),
            ("D", "Save current input field as the new default"),
            ("j / k or ↓/↑", "Navigate history entries"),
            ("g / G", "Jump to top / bottom of history list"),
            ("x", "Delete selected history entry (with confirm)"),
            ("r", "Refresh data from database"),
            ("q", "Quit TUI (active timer continues in background)"),
            ("?", "Toggle this help modal"),
        ]

        try:
            for i, (key, desc) in enumerate(lines[:modal_h - 4]):
                row_y = modal_y + 2 + i
                stdscr.addstr(row_y, modal_x + 3, f"{key:<15}", curses.color_pair(4) | curses.A_BOLD)
                stdscr.addstr(row_y, modal_x + 19, desc[:modal_w - 22], curses.color_pair(9))
            
            hint = "Press Esc, Space, or q to close"
            stdscr.addstr(modal_y + modal_h - 2, modal_x + (modal_w - len(hint)) // 2, hint, curses.color_pair(1) | curses.A_DIM)
        except curses.error:
            pass

    def _render_confirm_delete_modal(self, stdscr, max_y: int, max_x: int):
        modal_w = min(50, max_x - 6)
        modal_h = 7
        modal_y = (max_y - modal_h) // 2
        modal_x = (max_x - modal_w) // 2

        self._draw_box(stdscr, modal_y, modal_x, modal_h, modal_w, title="Confirm Deletion", color_pair=3)
        try:
            msg = f"Delete entry #{self.pending_delete_id}?"
            stdscr.addstr(modal_y + 2, modal_x + (modal_w - len(msg)) // 2, msg, curses.color_pair(3) | curses.A_BOLD)
            prompt = "Press 'y' to confirm, 'n' or Esc to cancel"
            stdscr.addstr(modal_y + 4, modal_x + (modal_w - len(prompt)) // 2, prompt, curses.color_pair(9))
        except curses.error:
            pass

    def _handle_normal_key(self, ch: int) -> bool:
        """Returns False if quit requested."""
        if ch in (ord('q'), ord('Q')):
            return False

        elif ch in (ord('s'), ord(' ')):  # Toggle Start / Stop
            if self.active_entry:
                stopped = self.core.stop()
                dur_str = TimeEntry.format_duration(stopped.calculate_duration())
                self.set_status(f"Stopped: '{stopped.description}' ({dur_str})")
            else:
                desc = self.desc_buffer.strip() or self.default_desc
                started = self.core.start(description=desc)
                self.set_status(f"Started: '{started.description}'")

        elif ch in (ord('i'), ord('I'), ord('a'), ord('A'), ord('e')):
            self.mode = "INSERT"
            self.cursor_pos = len(self.desc_buffer)

        elif ch == ord('d'):  # Reset to default description
            self.desc_buffer = self.default_desc
            self.cursor_pos = len(self.desc_buffer)
            self.set_status(f"Reset description to default: '{self.default_desc}'")

        elif ch == ord('D'):  # Set current as default description
            new_def = self.desc_buffer.strip()
            if new_def:
                self.core.default_description = new_def
                self.default_desc = new_def
                self.set_status(f"Saved '{new_def}' as default description.")

        elif ch in (ord('j'), curses.KEY_DOWN):
            if self.entries and self.selected_idx < len(self.entries) - 1:
                self.selected_idx += 1

        elif ch in (ord('k'), curses.KEY_UP):
            if self.selected_idx > 0:
                self.selected_idx -= 1

        elif ch in (ord('g'), curses.KEY_HOME):
            self.selected_idx = 0

        elif ch in (ord('G'), curses.KEY_END):
            if self.entries:
                self.selected_idx = len(self.entries) - 1

        elif ch in (ord('x'), curses.KEY_DC):
            if self.entries and 0 <= self.selected_idx < len(self.entries):
                target = self.entries[self.selected_idx]
                self.pending_delete_id = target.id
                self.mode = "CONFIRM_DELETE"

        elif ch == ord('r'):
            self.refresh_data()
            self.set_status("Data refreshed.")

        elif ch in (ord('?'), ord('h')):
            self.mode = "HELP"

        return True

    def _handle_insert_key(self, ch: int):
        if ch in (27,):  # Escape key
            self.mode = "NORMAL"
            return

        elif ch in (10, 13, curses.KEY_ENTER):  # Enter key
            self.mode = "NORMAL"
            new_desc = self.desc_buffer.strip()
            if not new_desc:
                new_desc = self.default_desc
                self.desc_buffer = new_desc

            # If currently active, update the running timer description in DB immediately
            if self.active_entry:
                self.db.update_entry(self.active_entry.id, description=new_desc)
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

        elif 32 <= ch <= 126:  # Printable ASCII characters
            char = chr(ch)
            self.desc_buffer = self.desc_buffer[:self.cursor_pos] + char + self.desc_buffer[self.cursor_pos:]
            self.cursor_pos += 1


def launch_tui(db: Optional[Database] = None):
    tui = VLoggerTUI(db=db)
    tui.run()
