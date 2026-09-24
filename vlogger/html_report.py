"""Static HTML generator for vlogger reproducing the exact Terminal User Interface (TUI) look.

Produces a pixel-perfect, interactive terminal replica styled after Kitty / Hyprland,
rendering curses-style rounded boxes, colors, active tracker controls, tabbed views
(Recent Work Logs and Daily Stats), and modals (Help and Day Details).
"""

import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from vlogger.db import Database
from vlogger.models import TimeEntry
from vlogger.core import VLoggerCore


def generate_html_report(
    db: Database,
    title: str = "ekselek — vlogger",
    days_limit: int = 30,
    weeks_limit: int = 26,
    months_limit: int = 12,
    read_only: bool = True,
) -> str:
    """Generate a standalone HTML file that duplicates the curses TUI layout, styling, and feel."""
    active_entry = db.get_active_entry()
    today_stats = db.get_stats_for_today()
    daily_stats = db.get_daily_stats(days_limit=days_limit)
    daily_summary = VLoggerCore.calculate_daily_summary(daily_stats)

    weekly_stats = db.get_weekly_stats(weeks_limit=weeks_limit)
    weekly_summary = VLoggerCore.calculate_weekly_summary(weekly_stats)

    monthly_stats = db.get_monthly_stats(months_limit=months_limit)
    monthly_summary = VLoggerCore.calculate_monthly_summary(monthly_stats)

    recent_entries = db.list_entries(limit=100)
    last_desc = db.get_last_description() or db.get_setting("default_description", "Work")

    now_dt = datetime.now().astimezone()
    now_str = now_dt.strftime("%d.%m.%Y %H:%M:%S")

    # Serialize data for client-side interactivity
    json_daily = []
    for d in daily_stats:
        d_copy = dict(d)
        d_copy["entries"] = [e.to_dict() for e in d.get("entries", [])]
        json_daily.append(d_copy)

    json_weekly = []
    for w in weekly_stats:
        w_copy = dict(w)
        w_copy["entries"] = [e.to_dict() for e in w.get("entries", [])]
        json_weekly.append(w_copy)

    json_monthly = []
    for m in monthly_stats:
        m_copy = dict(m)
        m_copy["entries"] = [e.to_dict() for e in m.get("entries", [])]
        json_monthly.append(m_copy)

    json_entries = [e.to_dict() for e in recent_entries]

    # Pre-render Tracker Box
    is_running = active_entry is not None
    active_epoch_ms = 0
    if is_running:
        status_badge_html = '<span class="tui-badge-running"> ● RUNNING </span>'
        elapsed_sec = active_entry.calculate_duration()
        elapsed_str = TimeEntry.format_duration(elapsed_sec)
        try:
            s_dt = datetime.fromisoformat(active_entry.start_time)
            since_str = f'<span class="tui-dim">(since {s_dt.strftime("%H:%M:%S")})</span>'
            active_epoch_ms = int(s_dt.timestamp() * 1000)
        except Exception:
            since_str = ""
        desc_val = active_entry.description
        btn_toggle_html = '<span class="tui-btn-stop" onclick="simulateToggleTimer()"> [s: STOP] </span>'
    else:
        status_badge_html = '<span class="tui-badge-stopped"> ■ STOPPED </span>'
        elapsed_str = "00:00:00"
        since_str = ""
        desc_val = last_desc
        btn_toggle_html = '<span class="tui-btn-start" onclick="simulateToggleTimer()"> [s: START] </span>'

    if read_only:
        row_3_html = '''<span class="tui-yellow bold">[ 🔒 READ-ONLY MONITOR ]</span>
          <span class="tui-btn-action tui-cyan bold" onclick="cycleTuiView()">[h/l or Tab: Switch View (1-4)]</span>
          <span class="tui-btn-action tui-dim" onclick="window.location.reload()">[r: Refresh]</span>
          <span class="tui-btn-action tui-dim" onclick="toggleHelpModal()">[?: Shortcuts]</span>'''
        mode_label = "-- READ-ONLY --"
        footer_hints = "h / l or Tab: Switch Views (1-4) │ Enter: Details │ j / k: Navigate │ r: Reload │ ?: Shortcuts"
        help_title = "Viewer Shortcuts & Help (Read-Only)"
        help_lines = '''<div class="tui-help-line"><span class="tui-help-key">h / l or ←/→</span><span class="tui-help-desc">Switch between tabs (Logs, Daily, Weekly, Monthly)</span></div>
          <div class="tui-help-line"><span class="tui-help-key">Tab or v</span><span class="tui-help-desc">Cycle through all 4 views (Shift+Tab to reverse)</span></div>
          <div class="tui-help-line"><span class="tui-help-key">1 / 2 / 3 / 4</span><span class="tui-help-desc">Direct jump to Logs (1), Daily (2), Weekly (3), Monthly (4)</span></div>
          <div class="tui-help-line"><span class="tui-help-key">j / k or ↓/↑</span><span class="tui-help-desc">Navigate entries or stats with cursor</span></div>
          <div class="tui-help-line"><span class="tui-help-key">Enter</span><span class="tui-help-desc">Open Details modal for selected entry, day, week, or month</span></div>
          <div class="tui-help-line"><span class="tui-help-key">g / G</span><span class="tui-help-desc">Jump to top / bottom of current list</span></div>
          <div class="tui-help-line"><span class="tui-help-key">r</span><span class="tui-help-desc">Reload / refresh latest progress from server</span></div>
          <div class="tui-help-line"><span class="tui-help-key">?</span><span class="tui-help-desc">Toggle this shortcuts & help dialog</span></div>
          <div style="margin-top: 12px; padding: 8px 10px; background: rgba(86,182,194,0.12); border-left: 3px solid #56b6c2; font-size: 12px; color: #abb2bf;">
            <strong style="color: #61afef;">💡 Vimium / SurfingKeys:</strong> Extension intercepts <code>j/k/h/l/r</code>. Press <code>i</code> (Vimium insert mode) or click the Vimium icon to exclude this URL.
          </div>'''
    else:
        row_3_html = f'''<span id="tui-btn-toggle">{btn_toggle_html}</span>
          <span class="tui-btn-action tui-cyan bold">[i: Edit]</span>
          <span class="tui-btn-action tui-yellow bold">[p: Pick Past]</span>
          <span class="tui-btn-action tui-dim">[d: Last Desc]</span>
          <span class="tui-btn-action tui-dim" onclick="toggleHelpModal()">[?: Help]</span>'''
        mode_label = "-- NORMAL --"
        footer_hints = "Tab: Cycle Views (1-4) | s: Start/Stop | i: Edit | p: Pick | y: Yank | ?: Help | q: Quit"
        help_title = "Help & Vim Bindings"
        help_lines = '''<div class="tui-help-line"><span class="tui-help-key">Tab or v</span><span class="tui-help-desc">Cycle between Logs, Daily, Weekly, and Monthly views</span></div>
          <div class="tui-help-line"><span class="tui-help-key">1 / 2 / 3 / 4</span><span class="tui-help-desc">Switch directly to Logs (1), Daily (2), Weekly (3), Monthly (4)</span></div>
          <div class="tui-help-line"><span class="tui-help-key">s or Space</span><span class="tui-help-desc">Toggle Start / Stop timer</span></div>
          <div class="tui-help-line"><span class="tui-help-key">i or a</span><span class="tui-help-desc">Insert mode: Edit active tracker description</span></div>
          <div class="tui-help-line"><span class="tui-help-key">p</span><span class="tui-help-desc">Pick from list of unique past tasks</span></div>
          <div class="tui-help-line"><span class="tui-help-key">y</span><span class="tui-help-desc">Yank highlighted history/task to active tracker</span></div>
          <div class="tui-help-line"><span class="tui-help-key">e or Enter</span><span class="tui-help-desc">Edit selected log entry / View details modal</span></div>
          <div class="tui-help-line"><span class="tui-help-key">d</span><span class="tui-help-desc">Reset active description to last used task</span></div>
          <div class="tui-help-line"><span class="tui-help-key">D</span><span class="tui-help-desc">Save current active description as new default</span></div>
          <div class="tui-help-line"><span class="tui-help-key">j / k or ↓/↑</span><span class="tui-help-desc">Navigate history entries or stats</span></div>
          <div class="tui-help-line"><span class="tui-help-key">g / G</span><span class="tui-help-desc">Jump to top / bottom of current list</span></div>
          <div class="tui-help-line"><span class="tui-help-key">x</span><span class="tui-help-desc">Delete selected history entry (with confirm)</span></div>
          <div class="tui-help-line"><span class="tui-help-key">r</span><span class="tui-help-desc">Refresh data from database</span></div>
          <div class="tui-help-line"><span class="tui-help-key">q</span><span class="tui-help-desc">Quit TUI (active timer continues in background)</span></div>
          <div class="tui-help-line"><span class="tui-help-key">?</span><span class="tui-help-desc">Toggle this help modal</span></div>'''

    # Pre-render Logs View Rows
    log_rows_html = []
    for i, e in enumerate(recent_entries):
        is_sel = (i == 0)
        eid = f"#{e.id}"
        try:
            s_dt = datetime.fromisoformat(e.start_time)
            start_fmt = s_dt.strftime("%d.%m %H:%M")
        except Exception:
            start_fmt = e.start_time[:10]

        if e.is_active:
            end_fmt = "[Active]"
            dur_fmt = TimeEntry.format_duration(e.calculate_duration())
            dur_cls = "tui-green bold"
        else:
            try:
                e_dt = datetime.fromisoformat(e.end_time)
                end_fmt = e_dt.strftime("%H:%M")
            except Exception:
                end_fmt = "-"
            dur_fmt = TimeEntry.format_duration(e.calculate_duration())
            dur_cls = "tui-white"

        desc = html.escape(e.description)
        sel_cls = "tui-row-selected" if is_sel else ""
        cursor_ch = ">" if is_sel else " "

        log_rows_html.append(f'''<div class="tui-table-row tui-log-grid {sel_cls}" id="log-row-{i}" onclick="selectLogRow({i})" ondblclick="openLogDetailModal()">
  <span class="tui-cursor">{cursor_ch}</span><span class="tui-cell-id">{eid}</span><span class="tui-cell-time">{start_fmt}</span><span class="tui-cell-time">{end_fmt}</span><span class="tui-cell-dur {dur_cls}">{dur_fmt}</span><span class="tui-cell-desc">{desc}</span>
</div>''')

    if not recent_entries:
        log_rows_html.append('<div class="tui-empty-msg tui-dim">  No entries yet. Press \'s\' to start tracking your work!</div>')

    # Pre-render Daily Stats View Rows
    max_sec = max(daily_summary.get("max_day_seconds", 0), 28800)
    daily_rows_html = []
    for i, d in enumerate(daily_stats):
        is_sel = (i == 0)
        cursor_ch = ">" if is_sel else " "
        sel_cls = "tui-row-selected" if is_sel else ""

        raw_date = d["date"]
        try:
            d_dt = datetime.strptime(raw_date, "%Y-%m-%d")
            date_str = d_dt.strftime("%d.%m.%Y")
        except Exception:
            date_str = raw_date
        day_disp = d["day_abbr"]
        if d.get("is_today"):
            day_disp += " [Today]"
        elif d.get("is_yesterday"):
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
            top_parts.append(f"{html.escape(t['description'])} ({dur_c})")
        top_tasks_str = ", ".join(top_parts) if top_parts else "-"

        daily_rows_html.append(f'''<div class="tui-table-row {sel_cls}" id="stats-row-{i}" onclick="selectStatsRow({i})" ondblclick="openDayDetailModal()">
  <span class="tui-cursor">{cursor_ch}</span> <span class="tui-cell-date">{date_str:<12}</span> <span class="tui-cell-day">{day_disp:<11}</span> <span class="tui-cell-dur tui-white">{dur_str:<10}</span> <span class="tui-cell-cnt tui-dim">{cnt_str:<8}</span> <span class="tui-cell-bar tui-cyan">[{bar_str}]</span>  <span class="tui-cell-desc">{top_tasks_str}</span>
</div>''')

    if not daily_stats or (len(daily_stats) == 1 and daily_stats[0]["count"] == 0):
        daily_rows_html.append('<div class="tui-empty-msg tui-dim">  No entries yet. Press \'s\' to start tracking your work!</div>')

    # Initial breakdown for first day
    init_day = daily_stats[0] if daily_stats else None
    init_breakdown_html = _render_breakdown_block(init_day)

    today_dur_str = TimeEntry.format_duration(today_stats["total_seconds"])
    total_compact = daily_summary.get("compact_duration", "0s")
    active_days_cnt = daily_summary.get("active_days", 0)
    avg_compact = daily_summary.get("average_daily_formatted", "0s")
    peak_day_str = daily_summary.get("peak_day", "-")
    try:
        peak_day_str = datetime.strptime(peak_day_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        pass
    peak_compact = daily_summary.get("max_day_formatted", "0s")

    # Pre-render Weekly Stats View Rows
    max_week_sec = max(weekly_summary.get("max_week_seconds", 0), 40 * 3600)
    weekly_rows_html = []
    for i, w in enumerate(weekly_stats):
        is_sel = (i == 0)
        cursor_ch = ">" if is_sel else " "
        sel_cls = "tui-row-selected" if is_sel else ""

        week_disp = w["week"]
        if w.get("is_current_week"):
            week_disp += " [Cur]"
        elif w.get("is_last_week"):
            week_disp += " [Last]"

        range_disp = w.get("range_formatted", "")
        dur_str = TimeEntry.format_duration(w["total_seconds"])
        cnt_str = f"{w['count']} ent"

        bar_w = 10
        ratio = min(1.0, w["total_seconds"] / max_week_sec) if max_week_sec > 0 else 0
        filled = int(round(ratio * bar_w))
        bar_str = "█" * filled + "░" * (bar_w - filled)

        top_parts = []
        for t in w.get("tasks", [])[:3]:
            dur_c = TimeEntry.format_duration(t["total_seconds"], compact=True)
            top_parts.append(f"{html.escape(t['description'])} ({dur_c})")
        top_tasks_str = ", ".join(top_parts) if top_parts else "-"

        weekly_rows_html.append(f'''<div class="tui-table-row {sel_cls}" id="weekly-row-{i}" onclick="selectWeeklyRow({i})" ondblclick="openWeekDetailModal()">
  <span class="tui-cursor">{cursor_ch}</span> <span class="tui-cell-week">{week_disp:<14}</span> <span class="tui-cell-range">{range_disp:<22}</span> <span class="tui-cell-dur tui-white">{dur_str:<10}</span> <span class="tui-cell-cnt tui-dim">{cnt_str:<8}</span> <span class="tui-cell-bar tui-cyan">[{bar_str}]</span>  <span class="tui-cell-desc">{top_tasks_str}</span>
</div>''')

    if not weekly_stats or (len(weekly_stats) == 1 and weekly_stats[0]["count"] == 0):
        weekly_rows_html.append('<div class="tui-empty-msg tui-dim">  No weekly entries yet. Track time to see weekly statistics!</div>')

    init_week = weekly_stats[0] if weekly_stats else None
    init_weekly_breakdown_html = _render_weekly_breakdown_block(init_week)

    weekly_total_compact = weekly_summary.get("compact_duration", "0s")
    active_weeks_cnt = weekly_summary.get("active_weeks", 0)
    weekly_avg_compact = weekly_summary.get("average_weekly_formatted", "0s")
    peak_week_str = weekly_summary.get("peak_week", "-")
    peak_week_compact = weekly_summary.get("max_week_formatted", "0s")

    # Pre-render Monthly Stats View Rows
    max_month_sec = max(monthly_summary.get("max_month_seconds", 0), 160 * 3600)
    monthly_rows_html = []
    for i, m in enumerate(monthly_stats):
        is_sel = (i == 0)
        cursor_ch = ">" if is_sel else " "
        sel_cls = "tui-row-selected" if is_sel else ""

        month_disp = m["month"]
        if m.get("is_current_month"):
            month_disp += " [Cur]"
        elif m.get("is_last_month"):
            month_disp += " [Last]"

        period_disp = f"{m.get('month_abbr', m['month'])} ({m.get('active_days_count', 0)}d)"
        dur_str = TimeEntry.format_duration(m["total_seconds"])
        cnt_str = f"{m['count']} ent"

        bar_w = 10
        ratio = min(1.0, m["total_seconds"] / max_month_sec) if max_month_sec > 0 else 0
        filled = int(round(ratio * bar_w))
        bar_str = "█" * filled + "░" * (bar_w - filled)

        top_parts = []
        for t in m.get("tasks", [])[:3]:
            dur_c = TimeEntry.format_duration(t["total_seconds"], compact=True)
            top_parts.append(f"{html.escape(t['description'])} ({dur_c})")
        top_tasks_str = ", ".join(top_parts) if top_parts else "-"

        monthly_rows_html.append(f'''<div class="tui-table-row {sel_cls}" id="monthly-row-{i}" onclick="selectMonthlyRow({i})" ondblclick="openMonthDetailModal()">
  <span class="tui-cursor">{cursor_ch}</span> <span class="tui-cell-month">{month_disp:<14}</span> <span class="tui-cell-range">{period_disp:<22}</span> <span class="tui-cell-dur tui-white">{dur_str:<10}</span> <span class="tui-cell-cnt tui-dim">{cnt_str:<8}</span> <span class="tui-cell-bar tui-cyan">[{bar_str}]</span>  <span class="tui-cell-desc">{top_tasks_str}</span>
</div>''')

    if not monthly_stats or (len(monthly_stats) == 1 and monthly_stats[0]["count"] == 0):
        monthly_rows_html.append('<div class="tui-empty-msg tui-dim">  No monthly entries yet. Track time to see monthly statistics!</div>')

    init_month = monthly_stats[0] if monthly_stats else None
    init_monthly_breakdown_html = _render_monthly_breakdown_block(init_month)

    monthly_total_compact = monthly_summary.get("compact_duration", "0s")
    active_months_cnt = monthly_summary.get("active_months", 0)
    monthly_avg_compact = monthly_summary.get("average_monthly_formatted", "0s")
    peak_month_str = monthly_summary.get("peak_month", "-")
    peak_month_compact = monthly_summary.get("max_month_formatted", "0s")

    html_code = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --tui-bg: #090c10;
      --tui-window-bg: #0f141c;
      --tui-cyan: #38bdf8;
      --tui-green: #4ade80;
      --tui-red: #f87171;
      --tui-yellow: #facc15;
      --tui-magenta: #c084fc;
      --tui-white: #f1f5f9;
      --tui-dim: #64748b;
      --tui-border: #38bdf8;
      --tui-border-dim: #1e293b;
      --tui-font: "JetBrains Mono", "Cascadia Code", "Fira Code", "Liberation Mono", Menlo, Monaco, Consolas, monospace;
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      background-color: var(--tui-bg);
      color: var(--tui-white);
      font-family: var(--tui-font);
      font-size: 13.5px;
      line-height: 1.42;
      padding: 24px 16px;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }}

    /* Terminal Window Container */
    .terminal-window {{
      width: 100%;
      max-width: 960px;
      background: var(--tui-window-bg);
      border-radius: 10px;
      box-shadow: 0 25px 65px rgba(0, 0, 0, 0.75), 0 0 0 1px #1e293b;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }}

    /* Titlebar */
    .terminal-titlebar {{
      background: #161e2e;
      padding: 10px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid #1f293d;
      user-select: none;
    }}

    .window-controls {{
      display: flex;
      align-items: center;
      gap: 7px;
    }}

    .control-dot {{
      width: 11px;
      height: 11px;
      border-radius: 50%;
      display: inline-block;
    }}

    .dot-close {{ background: #ff5f56; }}
    .dot-minimize {{ background: #ffbd2e; }}
    .dot-maximize {{ background: #27c93f; }}

    .window-title {{
      font-size: 12px;
      color: var(--tui-dim);
      font-weight: 600;
      letter-spacing: 0.02em;
    }}

    .window-actions {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}

    .tui-nav-hint {{
      font-size: 11px;
      color: var(--tui-cyan);
      opacity: 0.8;
    }}

    .btn-pdf {{
      background: #1f293d;
      color: var(--tui-white);
      border: 1px solid #334155;
      border-radius: 4px;
      padding: 3px 8px;
      font-size: 11px;
      font-family: var(--tui-font);
      cursor: pointer;
      font-weight: 600;
    }}

    .btn-pdf:hover {{
      background: #334155;
    }}

    /* Terminal Screen */
    .terminal-screen {{
      padding: 16px 20px;
      background: var(--tui-window-bg);
      position: relative;
    }}

    /* TUI Banner */
    .tui-header {{
      display: flex;
      justify-content: space-between;
      margin-bottom: 12px;
      font-weight: 700;
      font-size: 14px;
    }}

    .tui-app-title {{
      color: var(--tui-cyan);
      letter-spacing: 0.05em;
    }}

    .tui-clock {{
      color: var(--tui-dim);
      font-size: 12.5px;
    }}

    /* Box Drawing */
    .tui-box {{
      position: relative;
      border: 1px solid var(--tui-cyan);
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 16px;
      background: var(--tui-window-bg);
    }}

    .tui-box-title {{
      position: absolute;
      top: -10px;
      left: 18px;
      background: var(--tui-window-bg);
      padding: 0 8px;
      font-weight: 700;
      color: var(--tui-cyan);
      font-size: 13px;
      letter-spacing: 0.02em;
    }}

    /* Tracker Content */
    .tracker-row-1 {{
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }}

    .tui-badge-running {{
      background: var(--tui-green);
      color: #000000;
      font-weight: 800;
      padding: 1px 6px;
      border-radius: 2px;
    }}

    .tui-badge-stopped {{
      background: var(--tui-red);
      color: #ffffff;
      font-weight: 800;
      padding: 1px 6px;
      border-radius: 2px;
    }}

    .tui-elapsed-val {{
      color: var(--tui-yellow);
      font-weight: 800;
    }}

    .tracker-row-2 {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }}

    .tui-field-display {{
      flex: 1;
      min-width: 250px;
      color: var(--tui-white);
      text-decoration: underline;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .tracker-row-3 {{
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      font-size: 13px;
    }}

    .tui-btn-start {{
      background: var(--tui-green);
      color: #000000;
      font-weight: 800;
      padding: 1px 6px;
      border-radius: 2px;
      cursor: pointer;
      user-select: none;
    }}

    .tui-btn-stop {{
      background: var(--tui-red);
      color: #ffffff;
      font-weight: 800;
      padding: 1px 6px;
      border-radius: 2px;
      cursor: pointer;
      user-select: none;
    }}

    .tui-btn-action {{
      cursor: pointer;
      user-select: none;
    }}

    .tui-btn-action:hover {{
      text-decoration: underline;
    }}

    /* Lower Panel & Interactive Tabs */
    .tui-tabs-bar {{
      position: absolute;
      top: -12px;
      left: 14px;
      background: var(--tui-window-bg);
      padding: 0 4px;
      display: flex;
      align-items: center;
      gap: 4px;
      flex-wrap: wrap;
    }}

    .tui-tab-btn {{
      font-family: var(--tui-font);
      font-size: 13px;
      padding: 1px 6px;
      border: none;
      background: transparent;
      color: var(--tui-cyan);
      cursor: pointer;
      border-radius: 3px;
      font-weight: 600;
    }}

    .tui-tab-btn.active {{
      background: var(--tui-cyan);
      color: #000000;
      font-weight: 800;
    }}

    .tui-tab-info {{
      color: var(--tui-dim);
      font-size: 12px;
      padding-left: 6px;
    }}

    /* Table & Rows */
    .tui-panel-content {{
      margin-top: 6px;
    }}

    .tui-table-header {{
      color: var(--tui-cyan);
      font-weight: 700;
      white-space: pre;
      margin-bottom: 2px;
    }}

    .tui-divider {{
      color: #27354a;
      white-space: pre;
      margin-bottom: 6px;
      overflow: hidden;
    }}

    .tui-summary-stat-line {{
      color: var(--tui-yellow);
      font-weight: 700;
      margin-bottom: 4px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .tui-rows-scrollbox {{
      max-height: 280px;
      overflow-y: auto;
      margin-bottom: 8px;
    }}

    .tui-rows-scrollbox::-webkit-scrollbar {{
      width: 6px;
    }}
    .tui-rows-scrollbox::-webkit-scrollbar-thumb {{
      background: #1e293b;
      border-radius: 3px;
    }}

    .tui-table-row {{
      white-space: pre;
      padding: 2px 4px;
      border-radius: 2px;
      cursor: pointer;
      display: flex;
      align-items: center;
    }}

    .tui-log-grid {{
      display: grid;
      grid-template-columns: 2ch 5ch 11ch 10ch 10ch minmax(0, 1fr);
      column-gap: 1.25ch;
      align-items: center;
      padding: 2px 4px;
    }}

    .tui-log-grid > span {{
      display: block;
      width: auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .tui-table-header.tui-log-grid > span:nth-child(3),
    .tui-th-center {{
      text-align: center;
    }}

    @media (max-width: 620px) {{
      .tui-log-grid {{ grid-template-columns: 2ch 11ch 10ch minmax(0, 1fr); }}
      .tui-log-grid > span:nth-child(2),
      .tui-log-grid > span:nth-child(4) {{ display: none; }}
    }}

    @media (max-width: 450px) {{
      .tui-log-grid {{ grid-template-columns: 2ch 11ch minmax(0, 1fr); }}
      .tui-log-grid > span:nth-child(5) {{ display: none; }}
    }}

    .tui-table-row:hover {{
      background: #162032;
    }}

    .tui-table-row.tui-row-selected {{
      background: var(--tui-cyan);
      color: #000000 !important;
      font-weight: 700;
    }}

    .tui-table-row.tui-row-selected * {{
      color: #000000 !important;
    }}

    /* Cell Widths for the Stats views */
    .tui-cursor {{ width: 14px; display: inline-block; font-weight: 800; }}
    .tui-cell-id {{ width: 50px; display: inline-block; }}
    .tui-cell-time {{ width: 85px; display: inline-block; }}
    .tui-cell-date {{ width: 95px; display: inline-block; }}
    .tui-cell-day {{ width: 90px; display: inline-block; }}
    .tui-cell-week {{ width: 110px; display: inline-block; }}
    .tui-cell-month {{ width: 110px; display: inline-block; }}
    .tui-cell-range {{ width: 165px; display: inline-block; }}
    .tui-cell-dur {{ width: 85px; display: inline-block; }}
    .tui-cell-cnt {{ width: 55px; display: inline-block; }}
    .tui-cell-bar {{ width: 105px; display: inline-block; letter-spacing: -0.05em; }}
    .tui-cell-desc {{ flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

    /* Breakdown panel at bottom of stats view */
    .tui-breakdown-panel {{
      border-top: 1px dashed #27354a;
      padding-top: 8px;
      margin-top: 8px;
      font-size: 13px;
    }}

    .tui-breakdown-title {{
      color: var(--tui-cyan);
      font-weight: 700;
      margin-bottom: 4px;
    }}

    .tui-breakdown-item {{
      color: var(--tui-white);
      padding: 1px 0;
    }}

    /* Footer */
    .tui-footer {{
      display: flex;
      align-items: center;
      gap: 16px;
      font-size: 12.5px;
      margin-top: 4px;
      padding-top: 6px;
      border-top: 1px solid #1e293b;
      flex-wrap: wrap;
    }}

    .tui-mode {{
      color: var(--tui-cyan);
      font-weight: 800;
      letter-spacing: 0.05em;
    }}

    .tui-hints {{
      color: var(--tui-white);
    }}

    /* Modals (Help & Day Details) */
    .tui-modal-overlay {{
      display: none;
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0, 0, 0, 0.65);
      z-index: 50;
      justify-content: center;
      align-items: center;
      border-radius: 10px;
    }}

    .tui-modal-overlay.active {{
      display: flex;
    }}

    .tui-modal-box {{
      width: 90%;
      max-width: 620px;
      background: #000000;
      border: 1px solid var(--tui-yellow);
      border-radius: 6px;
      padding: 16px 20px;
      position: relative;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.95);
    }}

    .tui-modal-title {{
      position: absolute;
      top: -11px;
      left: 20px;
      background: #000000;
      padding: 0 8px;
      color: var(--tui-yellow);
      font-weight: 800;
      font-size: 13px;
    }}

    .tui-help-line {{
      display: flex;
      justify-content: space-between;
      padding: 2px 0;
      font-size: 13px;
    }}

    .tui-help-key {{
      color: var(--tui-yellow);
      font-weight: 700;
      width: 160px;
    }}

    .tui-help-desc {{
      color: #ffffff;
      flex: 1;
    }}

    .tui-modal-close-hint {{
      text-align: center;
      color: var(--tui-cyan);
      font-size: 12px;
      margin-top: 14px;
      opacity: 0.8;
      cursor: pointer;
    }}

    /* Utility Color Classes */
    .tui-cyan {{ color: var(--tui-cyan); }}
    .tui-green {{ color: var(--tui-green); }}
    .tui-yellow {{ color: var(--tui-yellow); }}
    .tui-red {{ color: var(--tui-red); }}
    .tui-white {{ color: var(--tui-white); }}
    .tui-dim {{ color: var(--tui-dim); }}
    .bold {{ font-weight: 700; }}

    @media print {{
      body {{ background: #fff; padding: 0; }}
      .terminal-window {{ box-shadow: none; border: 1px solid #000; max-width: 100%; }}
      .terminal-titlebar, .btn-pdf {{ display: none; }}
      .tui-modal-overlay {{ display: none !important; }}
    }}
  </style>
</head>
<body>

  <div class="terminal-window">
    <!-- Window Titlebar -->
    <div class="terminal-titlebar">
      <div class="window-controls">
        <span class="control-dot dot-close" title="Close"></span>
        <span class="control-dot dot-minimize" title="Minimize"></span>
        <span class="control-dot dot-maximize" title="Maximize"></span>
      </div>
      <div class="window-title">kitty: ekselek</div>
      <div class="window-actions">
        <span class="tui-nav-hint">⌨ Tab/h/l/j/k/r/?</span>
        <button class="btn-pdf" onclick="window.location.reload()" title="Reload page (r)">🔄 Reload</button>
        <button class="btn-pdf" onclick="window.print()">🖨️ Print / PDF</button>
      </div>
    </div>

    <!-- Terminal Screen Area -->
    <div class="terminal-screen" tabindex="0" id="terminalScreen">

      <!-- Header Banner -->
      <div class="tui-header">
        <span class="tui-app-title">⚡ EKSELEK</span>
        <span class="tui-clock">{now_str}</span>
      </div>

      <!-- Upper Box: Active Tracker -->
      <div class="tui-box tracker-box">
        <div class="tui-box-title">Active Tracker</div>

        <div class="tracker-row-1">
          <span id="tui-status-badge">{status_badge_html}</span>
          <span>Elapsed: <span id="tui-elapsed-val" class="tui-elapsed-val">{elapsed_str}</span></span>
          <span id="tui-since-str">{since_str}</span>
        </div>

        <div class="tracker-row-2">
          <span class="tui-white bold">Description:</span>
          <span class="tui-field-display">[ {html.escape(desc_val)} ]</span>
        </div>

        <div class="tracker-row-3">
          {row_3_html}
        </div>
      </div>

      <!-- Lower Box: Interactive Tabbed Panel -->
      <div class="tui-box main-panel-box">
        <div class="tui-tabs-bar">
          <button id="tab-btn-logs" class="tui-tab-btn active" onclick="setTuiView('LOGS')">[ 1: Logs ]</button>
          <button id="tab-btn-stats" class="tui-tab-btn" onclick="setTuiView('STATS')">[ 2: Daily Stats ]</button>
          <button id="tab-btn-weekly" class="tui-tab-btn" onclick="setTuiView('WEEKLY')">[ 3: Weekly Stats ]</button>
          <button id="tab-btn-monthly" class="tui-tab-btn" onclick="setTuiView('MONTHLY')">[ 4: Monthly Stats ]</button>
          <span id="tui-tab-info" class="tui-tab-info">── (Today: {today_dur_str} in {today_stats['count']} entries)</span>
        </div>

        <div class="tui-panel-content">
          <!-- View 1: Logs View -->
          <div id="tui-view-logs" style="display: block;">
            <div class="tui-table-header tui-log-grid"><span></span><span>ID</span><span class="tui-th-center">START</span><span>END</span><span>DURATION</span><span>DESCRIPTION</span></div>
            <div class="tui-divider">──────────────────────────────────────────────────────────────────────────────────</div>
            <div class="tui-rows-scrollbox" id="logsScrollbox">
              {"".join(log_rows_html)}
            </div>
          </div>

          <!-- View 2: Daily Stats View -->
          <div id="tui-view-stats" style="display: none;">
            <div class="tui-summary-stat-line">  Total: {total_compact} across {active_days_cnt} active days  │  Daily Avg: {avg_compact}  │  Peak: {peak_day_str} ({peak_compact})</div>
            <div class="tui-divider">──────────────────────────────────────────────────────────────────────────────────</div>
            <div class="tui-table-header">  DATE         DAY        DURATION   ENTRIES  BAR          TOP TASKS</div>
            <div class="tui-rows-scrollbox" id="statsScrollbox">
              {"".join(daily_rows_html)}
            </div>
            <!-- Bottom Breakdown for selected day -->
            <div id="tui-stats-breakdown" class="tui-breakdown-panel">
              {init_breakdown_html}
            </div>
          </div>

          <!-- View 3: Weekly Stats View -->
          <div id="tui-view-weekly" style="display: none;">
            <div class="tui-summary-stat-line">  Total: {weekly_total_compact} across {active_weeks_cnt} active weeks  │  Weekly Avg: {weekly_avg_compact}  │  Peak: {peak_week_str} ({peak_week_compact})</div>
            <div class="tui-divider">──────────────────────────────────────────────────────────────────────────────────</div>
            <div class="tui-table-header">  WEEK           DATES                 DURATION   ENTRIES  BAR          TOP TASKS</div>
            <div class="tui-rows-scrollbox" id="weeklyScrollbox">
              {"".join(weekly_rows_html)}
            </div>
            <!-- Bottom Breakdown for selected week -->
            <div id="tui-weekly-breakdown" class="tui-breakdown-panel">
              {init_weekly_breakdown_html}
            </div>
          </div>

          <!-- View 4: Monthly Stats View -->
          <div id="tui-view-monthly" style="display: none;">
            <div class="tui-summary-stat-line">  Total: {monthly_total_compact} across {active_months_cnt} active months  │  Monthly Avg: {monthly_avg_compact}  │  Peak: {peak_month_str} ({peak_month_compact})</div>
            <div class="tui-divider">──────────────────────────────────────────────────────────────────────────────────</div>
            <div class="tui-table-header">  MONTH          PERIOD / ACTIVE DAYS  DURATION   ENTRIES  BAR          TOP TASKS</div>
            <div class="tui-rows-scrollbox" id="monthlyScrollbox">
              {"".join(monthly_rows_html)}
            </div>
            <!-- Bottom Breakdown for selected month -->
            <div id="tui-monthly-breakdown" class="tui-breakdown-panel">
              {init_monthly_breakdown_html}
            </div>
          </div>
        </div>
      </div>

      <!-- Footer Bar -->
      <div class="tui-footer">
        <span class="tui-mode">{mode_label}</span>
        <span id="tui-footer-hints" class="tui-hints">{footer_hints}</span>
      </div>

      <!-- Help Modal Overlay -->
      <div id="tuiModalHelp" class="tui-modal-overlay" onclick="closeModalOnOverlay(event, this)">
        <div class="tui-modal-box">
          <div class="tui-modal-title">{help_title}</div>
          {help_lines}
          <div class="tui-modal-close-hint" onclick="closeAllModals()">Press Esc, Space, or q to close</div>
        </div>
      </div>

      <!-- Day Details Modal Overlay -->
      <div id="tuiModalDayDetail" class="tui-modal-overlay" onclick="closeModalOnOverlay(event, this)">
        <div class="tui-modal-box" style="max-width: 680px;">
          <div class="tui-modal-title" id="dayDetailTitle">Day Details</div>
          <div id="dayDetailContent" style="margin-top: 4px; font-size: 13px;">
            <!-- Injected via JS -->
          </div>
          <div class="tui-modal-close-hint" onclick="closeAllModals()">Press Esc, Enter, or q to close</div>
        </div>
      </div>

    </div>
  </div>

  <script>
    const DAILY_DATA = {json.dumps(json_daily)};
    const WEEKLY_DATA = {json.dumps(json_weekly)};
    const MONTHLY_DATA = {json.dumps(json_monthly)};
    const LOGS_DATA = {json.dumps(json_entries)};
    const IS_ACTIVE = {json.dumps(is_running)};
    const ACTIVE_START_EPOCH = {active_epoch_ms};
    const TODAY_INFO = "── (Today: {today_dur_str} in {today_stats['count']} entries)";
    const STATS_INFO = "── (Total: {total_compact} across {active_days_cnt} active days)";
    const WEEKLY_INFO = "── (Total: {weekly_total_compact} across {active_weeks_cnt} active weeks)";
    const MONTHLY_INFO = "── (Total: {monthly_total_compact} across {active_months_cnt} active months)";

    // Live ticking timer for active running task
    if (IS_ACTIVE && ACTIVE_START_EPOCH > 0) {{
      setInterval(() => {{
        const diffSec = Math.max(0, Math.floor((Date.now() - ACTIVE_START_EPOCH) / 1000));
        const durStr = formatSeconds(diffSec);
        const elapsedEl = document.getElementById('tui-elapsed-val');
        if (elapsedEl) elapsedEl.textContent = durStr;
        const activeRowDur = document.querySelector('#logsScrollbox .tui-cell-dur.tui-green');
        if (activeRowDur) activeRowDur.textContent = durStr;
      }}, 1000);
    }}

    // Auto-reload when served over HTTP if report file updates on disk
    if (window.location.protocol.startsWith('http')) {{
      let lastTag = null;
      setInterval(() => {{
        fetch(window.location.href, {{ method: 'HEAD', cache: 'no-store' }})
          .then(res => {{
            const tag = res.headers.get('ETag') || res.headers.get('Last-Modified');
            if (lastTag && tag && tag !== lastTag) {{
              window.location.reload();
            }}
            if (!lastTag && tag) lastTag = tag;
          }})
          .catch(() => {{}});
      }}, 3000);
    }}

    const VIEWS = ["LOGS", "STATS", "WEEKLY", "MONTHLY"];
    let currentView = "LOGS";
    let selectedLogIdx = 0;
    let selectedStatsIdx = 0;
    let selectedWeeklyIdx = 0;
    let selectedMonthlyIdx = 0;
    let isHelpOpen = false;
    let isDetailOpen = false;

    function cycleTuiView(direction = 1) {{
      const curIdx = VIEWS.indexOf(currentView);
      const nextIdx = (curIdx + direction + VIEWS.length) % VIEWS.length;
      setTuiView(VIEWS[nextIdx]);
    }}

    function setTuiView(view) {{
      currentView = view;
      const btnLogs = document.getElementById('tab-btn-logs');
      const btnStats = document.getElementById('tab-btn-stats');
      const btnWeekly = document.getElementById('tab-btn-weekly');
      const btnMonthly = document.getElementById('tab-btn-monthly');

      const viewLogs = document.getElementById('tui-view-logs');
      const viewStats = document.getElementById('tui-view-stats');
      const viewWeekly = document.getElementById('tui-view-weekly');
      const viewMonthly = document.getElementById('tui-view-monthly');

      const tabInfo = document.getElementById('tui-tab-info');
      const footerHints = document.getElementById('tui-footer-hints');

      if (btnLogs) btnLogs.classList.toggle('active', view === 'LOGS');
      if (btnStats) btnStats.classList.toggle('active', view === 'STATS');
      if (btnWeekly) btnWeekly.classList.toggle('active', view === 'WEEKLY');
      if (btnMonthly) btnMonthly.classList.toggle('active', view === 'MONTHLY');

      if (viewLogs) viewLogs.style.display = (view === 'LOGS') ? 'block' : 'none';
      if (viewStats) viewStats.style.display = (view === 'STATS') ? 'block' : 'none';
      if (viewWeekly) viewWeekly.style.display = (view === 'WEEKLY') ? 'block' : 'none';
      if (viewMonthly) viewMonthly.style.display = (view === 'MONTHLY') ? 'block' : 'none';

      if (tabInfo) {{
        if (view === 'LOGS') tabInfo.textContent = TODAY_INFO;
        else if (view === 'STATS') tabInfo.textContent = STATS_INFO;
        else if (view === 'WEEKLY') tabInfo.textContent = WEEKLY_INFO;
        else if (view === 'MONTHLY') tabInfo.textContent = MONTHLY_INFO;
      }}

      if (footerHints) footerHints.textContent = "{footer_hints}";

      if (view === 'STATS') {{
        updateStatsBreakdown(selectedStatsIdx);
      }} else if (view === 'WEEKLY') {{
        updateWeeklyBreakdown(selectedWeeklyIdx);
      }} else if (view === 'MONTHLY') {{
        updateMonthlyBreakdown(selectedMonthlyIdx);
      }}
    }}

    function selectLogRow(idx) {{
      if (!LOGS_DATA || LOGS_DATA.length === 0) return;
      const clamped = Math.max(0, Math.min(idx, LOGS_DATA.length - 1));
      selectedLogIdx = clamped;
      document.querySelectorAll('#logsScrollbox .tui-table-row').forEach((row, i) => {{
        const isSel = (i === clamped);
        row.classList.toggle('tui-row-selected', isSel);
        const cursor = row.querySelector('.tui-cursor');
        if (cursor) cursor.textContent = isSel ? '>' : ' ';
        if (isSel) {{
          row.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
        }}
      }});
    }}

    function selectStatsRow(idx) {{
      if (!DAILY_DATA || DAILY_DATA.length === 0) return;
      const clamped = Math.max(0, Math.min(idx, DAILY_DATA.length - 1));
      selectedStatsIdx = clamped;
      document.querySelectorAll('#statsScrollbox .tui-table-row').forEach((row, i) => {{
        const isSel = (i === clamped);
        row.classList.toggle('tui-row-selected', isSel);
        const cursor = row.querySelector('.tui-cursor');
        if (cursor) cursor.textContent = isSel ? '>' : ' ';
        if (isSel) {{
          row.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
        }}
      }});
      updateStatsBreakdown(clamped);
    }}

    function selectWeeklyRow(idx) {{
      if (!WEEKLY_DATA || WEEKLY_DATA.length === 0) return;
      const clamped = Math.max(0, Math.min(idx, WEEKLY_DATA.length - 1));
      selectedWeeklyIdx = clamped;
      document.querySelectorAll('#weeklyScrollbox .tui-table-row').forEach((row, i) => {{
        const isSel = (i === clamped);
        row.classList.toggle('tui-row-selected', isSel);
        const cursor = row.querySelector('.tui-cursor');
        if (cursor) cursor.textContent = isSel ? '>' : ' ';
        if (isSel) {{
          row.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
        }}
      }});
      updateWeeklyBreakdown(clamped);
    }}

    function selectMonthlyRow(idx) {{
      if (!MONTHLY_DATA || MONTHLY_DATA.length === 0) return;
      const clamped = Math.max(0, Math.min(idx, MONTHLY_DATA.length - 1));
      selectedMonthlyIdx = clamped;
      document.querySelectorAll('#monthlyScrollbox .tui-table-row').forEach((row, i) => {{
        const isSel = (i === clamped);
        row.classList.toggle('tui-row-selected', isSel);
        const cursor = row.querySelector('.tui-cursor');
        if (cursor) cursor.textContent = isSel ? '>' : ' ';
        if (isSel) {{
          row.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
        }}
      }});
      updateMonthlyBreakdown(clamped);
    }}

    function formatPolishDate(dStr) {{
      if (!dStr) return '';
      const m = dStr.match(/^(\\d{{4}})-(\\d{{2}})-(\\d{{2}})/);
      if (m) return `${{m[3]}}.${{m[2]}}.${{m[1]}}`;
      return dStr;
    }}

    function formatPolishDateTime(dtStr) {{
      if (!dtStr || dtStr === '-') return dtStr;
      const clean = dtStr.replace('T', ' ');
      const m = clean.match(/^(\\d{{4}})-(\\d{{2}})-(\\d{{2}})[ T](\\d{{2}}:\\d{{2}}(?::\\d{{2}})?)/);
      if (m) return `${{m[3]}}.${{m[2]}}.${{m[1]}} ${{m[4]}}`;
      return dtStr;
    }}

    function updateStatsBreakdown(idx) {{
      const container = document.getElementById('tui-stats-breakdown');
      if (!container || !DAILY_DATA || idx >= DAILY_DATA.length) return;
      const d = DAILY_DATA[idx];
      const dayName = d.day_name ? ` (${{d.day_name}})` : '';
      const dur = formatSeconds(d.total_seconds);
      const cnt = d.count;

      let html = `<div class="tui-breakdown-title">── Breakdown: ${{formatPolishDate(d.date)}}${{dayName}} ─ ${{dur}} in ${{cnt}} session${{cnt !== 1 ? 's' : ''}} ──</div>`;
      if (d.tasks && d.tasks.length > 0) {{
        d.tasks.slice(0, 3).forEach(t => {{
          const tDur = formatCompactSeconds(t.total_seconds);
          html += `<div class="tui-breakdown-item">  • ${{escapeHtml(t.description)}}: ${{tDur}} (${{t.percentage}}%) ─ ${{t.count}} session${{t.count !== 1 ? 's' : ''}}</div>`;
        }});
      }} else {{
        html += `<div class="tui-breakdown-item tui-dim">  • No tasks recorded for this day.</div>`;
      }}
      container.innerHTML = html;
    }}

    function updateWeeklyBreakdown(idx) {{
      const container = document.getElementById('tui-weekly-breakdown');
      if (!container || !WEEKLY_DATA || idx >= WEEKLY_DATA.length) return;
      const w = WEEKLY_DATA[idx];
      const dur = formatSeconds(w.total_seconds);
      const cnt = w.count;
      const actDays = w.active_days_count || 0;

      let html = `<div class="tui-breakdown-title">── Breakdown: ${{w.week}} (${{w.range_formatted}}) ─ ${{dur}} in ${{cnt}} session${{cnt !== 1 ? 's' : ''}} (${{actDays}} active day${{actDays !== 1 ? 's' : ''}}) ──</div>`;
      if (w.tasks && w.tasks.length > 0) {{
        w.tasks.slice(0, 3).forEach(t => {{
          const tDur = formatCompactSeconds(t.total_seconds);
          html += `<div class="tui-breakdown-item">  • ${{escapeHtml(t.description)}}: ${{tDur}} (${{t.percentage}}%) ─ ${{t.count}} session${{t.count !== 1 ? 's' : ''}}</div>`;
        }});
      }} else {{
        html += `<div class="tui-breakdown-item tui-dim">  • No tasks recorded for this week.</div>`;
      }}

      if (w.days_breakdown && w.days_breakdown.length > 0) {{
        const daysStr = w.days_breakdown.map(d => `${{d.day_abbr}} (${{formatCompactSeconds(d.total_seconds)}})`).join(' • ');
        html += `<div class="tui-breakdown-item tui-cyan" style="margin-top: 2px;">  • Daily: ${{daysStr}}</div>`;
      }}
      container.innerHTML = html;
    }}

    function updateMonthlyBreakdown(idx) {{
      const container = document.getElementById('tui-monthly-breakdown');
      if (!container || !MONTHLY_DATA || idx >= MONTHLY_DATA.length) return;
      const m = MONTHLY_DATA[idx];
      const dur = formatSeconds(m.total_seconds);
      const cnt = m.count;
      const actDays = m.active_days_count || 0;

      let html = `<div class="tui-breakdown-title">── Breakdown: ${{m.month_name}} (${{m.range_formatted}}) ─ ${{dur}} in ${{cnt}} session${{cnt !== 1 ? 's' : ''}} (${{actDays}} active day${{actDays !== 1 ? 's' : ''}}) ──</div>`;
      if (m.tasks && m.tasks.length > 0) {{
        m.tasks.slice(0, 3).forEach(t => {{
          const tDur = formatCompactSeconds(t.total_seconds);
          html += `<div class="tui-breakdown-item">  • ${{escapeHtml(t.description)}}: ${{tDur}} (${{t.percentage}}%) ─ ${{t.count}} session${{t.count !== 1 ? 's' : ''}}</div>`;
        }});
      }} else {{
        html += `<div class="tui-breakdown-item tui-dim">  • No tasks recorded for this month.</div>`;
      }}

      if (m.weeks_breakdown && m.weeks_breakdown.length > 0) {{
        const weeksStr = m.weeks_breakdown.map(w => `${{w.week}} (${{formatCompactSeconds(w.total_seconds)}})`).join(' • ');
        html += `<div class="tui-breakdown-item tui-cyan" style="margin-top: 2px;">  • Weekly: ${{weeksStr}}</div>`;
      }}
      container.innerHTML = html;
    }}

    function openDayDetailModal() {{
      if (!DAILY_DATA || selectedStatsIdx >= DAILY_DATA.length) return;
      const d = DAILY_DATA[selectedStatsIdx];
      const modal = document.getElementById('tuiModalDayDetail');
      const title = document.getElementById('dayDetailTitle');
      const content = document.getElementById('dayDetailContent');

      title.textContent = `Day Details: ${{formatPolishDate(d.date)}} (${{d.day_name || ''}})`;
      const totalDur = formatSeconds(d.total_seconds);

      let subHtml = `<div class="tui-yellow bold" style="margin-bottom: 8px;">Total Time: ${{totalDur}} across ${{d.count}} entries</div>`;
      subHtml += `<div class="tui-cyan bold" style="margin-bottom: 4px;">  ID    START    END      DURATION   DESCRIPTION</div>`;
      subHtml += `<div class="tui-divider">─────────────────────────────────────────────────────────────</div>`;

      if (d.entries && d.entries.length > 0) {{
        d.entries.forEach(e => {{
          const sFmt = e.start_time ? e.start_time.substring(11, 16) : '-';
          const eFmt = e.is_active ? '[Active]' : (e.end_time ? e.end_time.substring(11, 16) : '-');
          const durStr = e.duration_formatted || formatSeconds(e.duration_seconds || 0);
          const actCls = e.is_active ? 'tui-green bold' : 'tui-white';
          subHtml += `<div style="white-space: pre; padding: 2px 0;">  #${{e.id}}   ${{sFmt}}    ${{eFmt}}    <span class="${{actCls}}">${{durStr}}</span>   ${{escapeHtml(e.description)}}</div>`;
        }});
      }} else {{
        subHtml += `<div class="tui-dim">  No sessions recorded for this day.</div>`;
      }}

      if (d.tasks && d.tasks.length > 0) {{
        subHtml += `<div class="tui-divider" style="margin-top: 8px;">─────────────────────────────────────────────────────────────</div>`;
        subHtml += `<div class="tui-dim" style="font-size: 12px;">Tasks: ` + d.tasks.slice(0, 4).map(t => `${{escapeHtml(t.description)}} (${{t.percentage}}%)`).join(' • ') + `</div>`;
      }}

      content.innerHTML = subHtml;
      modal.classList.add('active');
      isDetailOpen = true;
    }}

    function openWeekDetailModal() {{
      if (!WEEKLY_DATA || selectedWeeklyIdx >= WEEKLY_DATA.length) return;
      const w = WEEKLY_DATA[selectedWeeklyIdx];
      const modal = document.getElementById('tuiModalDayDetail');
      const title = document.getElementById('dayDetailTitle');
      const content = document.getElementById('dayDetailContent');

      title.textContent = `Week Details: ${{w.week}} (${{w.range_formatted}})`;
      const totalDur = formatSeconds(w.total_seconds);
      const actDays = w.active_days_count || 0;

      let subHtml = `<div class="tui-yellow bold" style="margin-bottom: 8px;">Total Time: ${{totalDur}} across ${{w.count}} entries (${{actDays}} active days)</div>`;

      if (w.days_breakdown && w.days_breakdown.length > 0) {{
        subHtml += `<div class="tui-cyan bold" style="margin-bottom: 4px;">  DATE         DAY        DURATION   ENTRIES</div>`;
        subHtml += `<div class="tui-divider">─────────────────────────────────────────────────────────────</div>`;
        w.days_breakdown.forEach(d => {{
          const durStr = formatSeconds(d.total_seconds);
          subHtml += `<div style="white-space: pre; padding: 2px 0;">  ${{formatPolishDate(d.date)}}   ${{d.day_name}}   <span class="tui-white">${{durStr}}</span>   ${{d.count}} entries</div>`;
        }});
        subHtml += `<div class="tui-divider" style="margin: 6px 0;">─────────────────────────────────────────────────────────────</div>`;
      }}

      subHtml += `<div class="tui-cyan bold" style="margin-bottom: 4px;">  ID    DATE         START    END      DURATION   DESCRIPTION</div>`;
      subHtml += `<div class="tui-divider">─────────────────────────────────────────────────────────────</div>`;

      if (w.entries && w.entries.length > 0) {{
        subHtml += `<div style="max-height: 200px; overflow-y: auto;">`;
        w.entries.forEach(e => {{
          const dFmt = e.start_time ? formatPolishDate(e.start_time.substring(0, 10)) : '-';
          const sFmt = e.start_time ? e.start_time.substring(11, 16) : '-';
          const eFmt = e.is_active ? '[Active]' : (e.end_time ? e.end_time.substring(11, 16) : '-');
          const durStr = e.duration_formatted || formatSeconds(e.duration_seconds || 0);
          const actCls = e.is_active ? 'tui-green bold' : 'tui-white';
          subHtml += `<div style="white-space: pre; padding: 2px 0;">  #${{e.id}}   ${{dFmt}}   ${{sFmt}}    ${{eFmt}}    <span class="${{actCls}}">${{durStr}}</span>   ${{escapeHtml(e.description)}}</div>`;
        }});
        subHtml += `</div>`;
      }} else {{
        subHtml += `<div class="tui-dim">  No sessions recorded for this week.</div>`;
      }}

      if (w.tasks && w.tasks.length > 0) {{
        subHtml += `<div class="tui-divider" style="margin-top: 8px;">─────────────────────────────────────────────────────────────</div>`;
        subHtml += `<div class="tui-dim" style="font-size: 12px;">Tasks: ` + w.tasks.slice(0, 5).map(t => `${{escapeHtml(t.description)}} (${{t.percentage}}%)`).join(' • ') + `</div>`;
      }}

      content.innerHTML = subHtml;
      modal.classList.add('active');
      isDetailOpen = true;
    }}

    function openMonthDetailModal() {{
      if (!MONTHLY_DATA || selectedMonthlyIdx >= MONTHLY_DATA.length) return;
      const m = MONTHLY_DATA[selectedMonthlyIdx];
      const modal = document.getElementById('tuiModalDayDetail');
      const title = document.getElementById('dayDetailTitle');
      const content = document.getElementById('dayDetailContent');

      title.textContent = `Month Details: ${{m.month_name}} (${{m.range_formatted}})`;
      const totalDur = formatSeconds(m.total_seconds);
      const actDays = m.active_days_count || 0;

      let subHtml = `<div class="tui-yellow bold" style="margin-bottom: 8px;">Total Time: ${{totalDur}} across ${{m.count}} entries (${{actDays}} active days)</div>`;

      if (m.weeks_breakdown && m.weeks_breakdown.length > 0) {{
        subHtml += `<div class="tui-cyan bold" style="margin-bottom: 4px;">  WEEK           DATES                DURATION   ENTRIES</div>`;
        subHtml += `<div class="tui-divider">─────────────────────────────────────────────────────────────</div>`;
        m.weeks_breakdown.forEach(w => {{
          const durStr = formatSeconds(w.total_seconds);
          subHtml += `<div style="white-space: pre; padding: 2px 0;">  ${{w.week}}   ${{w.range_formatted}}   <span class="tui-white">${{durStr}}</span>   ${{w.count}} entries</div>`;
        }});
        subHtml += `<div class="tui-divider" style="margin: 6px 0;">─────────────────────────────────────────────────────────────</div>`;
      }}

      subHtml += `<div class="tui-cyan bold" style="margin-bottom: 4px;">  ID    DATE         START    END      DURATION   DESCRIPTION</div>`;
      subHtml += `<div class="tui-divider">─────────────────────────────────────────────────────────────</div>`;

      if (m.entries && m.entries.length > 0) {{
        subHtml += `<div style="max-height: 200px; overflow-y: auto;">`;
        m.entries.forEach(e => {{
          const dFmt = e.start_time ? formatPolishDate(e.start_time.substring(0, 10)) : '-';
          const sFmt = e.start_time ? e.start_time.substring(11, 16) : '-';
          const eFmt = e.is_active ? '[Active]' : (e.end_time ? e.end_time.substring(11, 16) : '-');
          const durStr = e.duration_formatted || formatSeconds(e.duration_seconds || 0);
          const actCls = e.is_active ? 'tui-green bold' : 'tui-white';
          subHtml += `<div style="white-space: pre; padding: 2px 0;">  #${{e.id}}   ${{dFmt}}   ${{sFmt}}    ${{eFmt}}    <span class="${{actCls}}">${{durStr}}</span>   ${{escapeHtml(e.description)}}</div>`;
        }});
        subHtml += `</div>`;
      }} else {{
        subHtml += `<div class="tui-dim">  No sessions recorded for this month.</div>`;
      }}

      if (m.tasks && m.tasks.length > 0) {{
        subHtml += `<div class="tui-divider" style="margin-top: 8px;">─────────────────────────────────────────────────────────────</div>`;
        subHtml += `<div class="tui-dim" style="font-size: 12px;">Tasks: ` + m.tasks.slice(0, 5).map(t => `${{escapeHtml(t.description)}} (${{t.percentage}}%)`).join(' • ') + `</div>`;
      }}

      content.innerHTML = subHtml;
      modal.classList.add('active');
      isDetailOpen = true;
    }}

    function openLogDetailModal() {{
      if (!LOGS_DATA || selectedLogIdx >= LOGS_DATA.length) return;
      const e = LOGS_DATA[selectedLogIdx];
      const modal = document.getElementById('tuiModalDayDetail');
      const title = document.getElementById('dayDetailTitle');
      const content = document.getElementById('dayDetailContent');

      title.textContent = `Entry Details: #${{e.id}}`;
      const sFmt = formatPolishDateTime(e.start_time) || '-';
      const eFmt = e.is_active ? '[Active / Running]' : (formatPolishDateTime(e.end_time) || '-');
      const durStr = e.duration_formatted || formatSeconds(e.duration_seconds || 0);
      const actCls = e.is_active ? 'tui-green bold' : 'tui-yellow bold';

      let subHtml = `<div class="${{actCls}}" style="margin-bottom: 8px;">Status: ${{e.is_active ? '● RUNNING' : '■ COMPLETED'}} ─ Duration: ${{durStr}}</div>`;
      subHtml += `<div class="tui-cyan bold" style="margin-bottom: 4px;">Task Description:</div>`;
      subHtml += `<div class="tui-white" style="margin-bottom: 8px; font-size: 14px;">[ ${{escapeHtml(e.description)}} ]</div>`;
      subHtml += `<div class="tui-divider">─────────────────────────────────────────────────────────────</div>`;
      subHtml += `<div style="padding: 2px 0;"><span class="tui-dim">Start Time: </span><span class="tui-white">${{sFmt}}</span></div>`;
      subHtml += `<div style="padding: 2px 0;"><span class="tui-dim">End Time:   </span><span class="tui-white">${{eFmt}}</span></div>`;
      subHtml += `<div style="padding: 2px 0;"><span class="tui-dim">Project:    </span><span class="tui-white">${{escapeHtml(e.project || 'default')}}</span></div>`;
      if (e.tags && e.tags.length > 0) {{
        subHtml += `<div style="padding: 2px 0;"><span class="tui-dim">Tags:       </span><span class="tui-white">${{escapeHtml(e.tags.join(', '))}}</span></div>`;
      }}

      content.innerHTML = subHtml;
      modal.classList.add('active');
      isDetailOpen = true;
    }}

    function toggleHelpModal() {{
      const modal = document.getElementById('tuiModalHelp');
      isHelpOpen = !isHelpOpen;
      modal.classList.toggle('active', isHelpOpen);
    }}

    function closeAllModals() {{
      document.getElementById('tuiModalHelp').classList.remove('active');
      document.getElementById('tuiModalDayDetail').classList.remove('active');
      isHelpOpen = false;
      isDetailOpen = false;
    }}

    function closeModalOnOverlay(e, overlay) {{
      if (e.target === overlay) {{
        closeAllModals();
      }}
    }}

    // Keyboard Vim-like interactions matching TUI
    document.addEventListener('keydown', (e) => {{
      // Do not intercept if browser modifier keys (Ctrl, Alt, Meta) are held
      if (e.ctrlKey || e.altKey || e.metaKey) return;

      const key = e.key.toLowerCase();

      // If a modal is open, allow closing it with Esc, Enter, Space, q
      if (isHelpOpen || isDetailOpen) {{
        if (['escape', 'q', 'enter', ' '].includes(key) || e.key === 'Escape') {{
          e.preventDefault();
          closeAllModals();
        }}
        return;
      }}

      // Switch tabs: h/l or arrow keys or Tab or 1/2/3/4 or v
      if (e.key === 'Tab' || key === 'v') {{
        e.preventDefault();
        cycleTuiView(e.shiftKey ? -1 : 1);
      }} else if (key === 'h' || e.key === 'ArrowLeft') {{
        e.preventDefault();
        cycleTuiView(-1);
      }} else if (key === 'l' || e.key === 'ArrowRight') {{
        e.preventDefault();
        cycleTuiView(1);
      }} else if (key === '1') {{
        e.preventDefault();
        setTuiView('LOGS');
      }} else if (key === '2') {{
        e.preventDefault();
        setTuiView('STATS');
      }} else if (key === '3') {{
        e.preventDefault();
        setTuiView('WEEKLY');
      }} else if (key === '4') {{
        e.preventDefault();
        setTuiView('MONTHLY');
      }}
      // Navigate rows: j/k or down/up
      else if (key === 'j' || e.key === 'ArrowDown') {{
        e.preventDefault();
        if (currentView === 'LOGS') {{
          selectLogRow(selectedLogIdx + 1);
        }} else if (currentView === 'STATS') {{
          selectStatsRow(selectedStatsIdx + 1);
        }} else if (currentView === 'WEEKLY') {{
          selectWeeklyRow(selectedWeeklyIdx + 1);
        }} else if (currentView === 'MONTHLY') {{
          selectMonthlyRow(selectedMonthlyIdx + 1);
        }}
      }} else if (key === 'k' || e.key === 'ArrowUp') {{
        e.preventDefault();
        if (currentView === 'LOGS') {{
          selectLogRow(selectedLogIdx - 1);
        }} else if (currentView === 'STATS') {{
          selectStatsRow(selectedStatsIdx - 1);
        }} else if (currentView === 'WEEKLY') {{
          selectWeeklyRow(selectedWeeklyIdx - 1);
        }} else if (currentView === 'MONTHLY') {{
          selectMonthlyRow(selectedMonthlyIdx - 1);
        }}
      }}
      // Jump to top / bottom: g / G / Home / End
      else if (key === 'g' || e.key === 'Home') {{
        e.preventDefault();
        if (currentView === 'LOGS') selectLogRow(0);
        else if (currentView === 'STATS') selectStatsRow(0);
        else if (currentView === 'WEEKLY') selectWeeklyRow(0);
        else if (currentView === 'MONTHLY') selectMonthlyRow(0);
      }} else if (e.key === 'G' || e.key === 'End') {{
        e.preventDefault();
        if (currentView === 'LOGS') selectLogRow(LOGS_DATA.length - 1);
        else if (currentView === 'STATS') selectStatsRow(DAILY_DATA.length - 1);
        else if (currentView === 'WEEKLY') selectWeeklyRow(WEEKLY_DATA.length - 1);
        else if (currentView === 'MONTHLY') selectMonthlyRow(MONTHLY_DATA.length - 1);
      }}
      // Details modal: Enter
      else if (e.key === 'Enter') {{
        e.preventDefault();
        if (currentView === 'LOGS') {{
          openLogDetailModal();
        }} else if (currentView === 'STATS') {{
          openDayDetailModal();
        }} else if (currentView === 'WEEKLY') {{
          openWeekDetailModal();
        }} else if (currentView === 'MONTHLY') {{
          openMonthDetailModal();
        }}
      }}
      // Reload: r
      else if (key === 'r') {{
        e.preventDefault();
        window.location.reload();
      }}
      // Shortcuts / Help: ?
      else if (e.key === '?') {{
        e.preventDefault();
        toggleHelpModal();
      }}
    }});

    function formatSeconds(sec) {{
      if (!sec || sec < 0) sec = 0;
      const h = Math.floor(sec / 3600).toString().padStart(2, '0');
      const m = Math.floor((sec % 3600) / 60).toString().padStart(2, '0');
      const s = (sec % 60).toString().padStart(2, '0');
      return `${{h}}:${{m}}:${{s}}`;
    }}

    function formatCompactSeconds(sec) {{
      if (!sec || sec < 0) return '0s';
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const s = sec % 60;
      if (h > 0) return `${{h}}h ${{m}}m`;
      if (m > 0) return `${{m}}m ${{s}}s`;
      return `${{s}}s`;
    }}

    function escapeHtml(str) {{
      if (!str) return '';
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }}
  </script>
</body>
</html>
'''
    return html_code


def _render_breakdown_block(day: Optional[Dict[str, Any]]) -> str:
    """Render the bottom task breakdown block for the selected day in daily stats."""
    if not day:
        return '<div class="tui-dim">  • No tasks recorded.</div>'

    raw_date = day.get("date", "")
    try:
        date_str = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        date_str = raw_date
    day_name = f" ({day['day_name']})" if day.get("day_name") else ""
    dur_str = TimeEntry.format_duration(day.get("total_seconds", 0))
    cnt = day.get("count", 0)

    lines = [
        f'<div class="tui-breakdown-title">── Breakdown: {date_str}{day_name} ─ {dur_str} in {cnt} session{"s" if cnt != 1 else ""} ──</div>'
    ]

    tasks = day.get("tasks", [])
    if tasks:
        for t in tasks[:3]:
            dur_c = TimeEntry.format_duration(t["total_seconds"], compact=True)
            pct = t["percentage"]
            t_cnt = t["count"]
            lines.append(
                f'<div class="tui-breakdown-item">  • {html.escape(t["description"])}: {dur_c} ({pct}%) ─ {t_cnt} session{"s" if t_cnt != 1 else ""}</div>'
            )
    else:
        lines.append('<div class="tui-breakdown-item tui-dim">  • No tasks recorded for this day.</div>')

    return "\n".join(lines)


def _render_weekly_breakdown_block(week: Optional[Dict[str, Any]]) -> str:
    """Render the bottom task breakdown block for the selected week in weekly stats."""
    if not week:
        return '<div class="tui-dim">  • No tasks recorded for this week.</div>'

    w_lbl = week.get("week", "")
    r_fmt = week.get("range_formatted", "")
    dur_str = TimeEntry.format_duration(week.get("total_seconds", 0))
    cnt = week.get("count", 0)
    act_days = week.get("active_days_count", 0)

    lines = [
        f'<div class="tui-breakdown-title">── Breakdown: {w_lbl} ({r_fmt}) ─ {dur_str} in {cnt} session{"s" if cnt != 1 else ""} ({act_days} active day{"s" if act_days != 1 else ""}) ──</div>'
    ]

    tasks = week.get("tasks", [])
    if tasks:
        for t in tasks[:3]:
            dur_c = TimeEntry.format_duration(t["total_seconds"], compact=True)
            pct = t["percentage"]
            t_cnt = t["count"]
            lines.append(
                f'<div class="tui-breakdown-item">  • {html.escape(t["description"])}: {dur_c} ({pct}%) ─ {t_cnt} session{"s" if t_cnt != 1 else ""}</div>'
            )
    else:
        lines.append('<div class="tui-breakdown-item tui-dim">  • No tasks recorded for this week.</div>')

    days = week.get("days_breakdown", [])
    if days:
        days_str = " • ".join(f"{d['day_abbr']} ({TimeEntry.format_duration(d['total_seconds'], compact=True)})" for d in days)
        lines.append(f'<div class="tui-breakdown-item tui-cyan" style="margin-top: 2px;">  • Daily: {days_str}</div>')

    return "\n".join(lines)


def _render_monthly_breakdown_block(month: Optional[Dict[str, Any]]) -> str:
    """Render the bottom task breakdown block for the selected month in monthly stats."""
    if not month:
        return '<div class="tui-dim">  • No tasks recorded for this month.</div>'

    m_name = month.get("month_name", month.get("month", ""))
    r_fmt = month.get("range_formatted", "")
    dur_str = TimeEntry.format_duration(month.get("total_seconds", 0))
    cnt = month.get("count", 0)
    act_days = month.get("active_days_count", 0)

    lines = [
        f'<div class="tui-breakdown-title">── Breakdown: {m_name} ({r_fmt}) ─ {dur_str} in {cnt} session{"s" if cnt != 1 else ""} ({act_days} active day{"s" if act_days != 1 else ""}) ──</div>'
    ]

    tasks = month.get("tasks", [])
    if tasks:
        for t in tasks[:3]:
            dur_c = TimeEntry.format_duration(t["total_seconds"], compact=True)
            pct = t["percentage"]
            t_cnt = t["count"]
            lines.append(
                f'<div class="tui-breakdown-item">  • {html.escape(t["description"])}: {dur_c} ({pct}%) ─ {t_cnt} session{"s" if t_cnt != 1 else ""}</div>'
            )
    else:
        lines.append('<div class="tui-breakdown-item tui-dim">  • No tasks recorded for this month.</div>')

    weeks = month.get("weeks_breakdown", [])
    if weeks:
        weeks_str = " • ".join(f"{w['week']} ({TimeEntry.format_duration(w['total_seconds'], compact=True)})" for w in weeks)
        lines.append(f'<div class="tui-breakdown-item tui-cyan" style="margin-top: 2px;">  • Weekly: {weeks_str}</div>')

    return "\n".join(lines)


def write_html_report(
    db: Database,
    file_path: Optional[Path] = None,
    title: str = "ekselek — vlogger",
    days_limit: int = 30,
    weeks_limit: int = 26,
    months_limit: int = 12,
    read_only: bool = True,
) -> Path:
    """Generate and write the static HTML TUI progress dashboard to the target file path atomically with read-only permissions."""
    if file_path:
        target_path = Path(file_path).expanduser().resolve()
    else:
        setting_val = db.get_setting("html_report_path")
        if setting_val:
            target_path = Path(setting_val).expanduser().resolve()
        else:
            target_path = db.db_path.parent / "ekselek.html"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    content = generate_html_report(
        db,
        title=title,
        days_limit=days_limit,
        weeks_limit=weeks_limit,
        months_limit=months_limit,
        read_only=read_only,
    )

    tmp_path = target_path.with_name(f".{target_path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(content, encoding="utf-8")
    if read_only:
        try:
            os.chmod(tmp_path, 0o444)
        except Exception:
            pass
    os.replace(tmp_path, target_path)
    return target_path
