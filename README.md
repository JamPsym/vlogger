# ⚡ vlogger

> **Minimalist, keyboard-first work time-logger with Vim keybindings, SQLite storage, and clean export.**
> Designed for Arch Linux + Hyprland, built with zero external dependencies (pure Python standard library).

---

## Features

- **Keyboard-First Vim Workflow**: Interactive curses TUI inside Kitty terminal with modal Vim controls (`s` to toggle, `i` to edit description, `j`/`k` to navigate history, `x` to delete, `d` to reset default).
- **Persistent SQLite Engine**: Stored in `~/.local/share/vlogger/vlogger.db` with WAL mode enabled for concurrent reads/writes without locks.
- **Future-Proof Clean Export**: Export your logs at any time to **JSON**, **JSONL (Lines)**, or **CSV** with standard ISO 8601 timestamps, duration in seconds, project labels, and tags.
- **Hyprland & Waybar Native**:
  - Launch as a floating Kitty scratchpad (`kitty --class vlogger -e vlogger`).
  - Single-key instant toggle shortcut (`vlogger toggle`).
  - Waybar module with live elapsed ticker, tooltip, and click-to-toggle (`vlogger status --waybar`).
- **Zero Dependencies**: Runs out of the box on Python 3.9+ with 0 third-party packages to install.

---

## Quick Start

The executable is symlinked to `~/.local/bin/vlogger` (already in your `$PATH`):

```bash
# Launch interactive TUI
vlogger

# Start timer directly from terminal
vlogger start "Developing parser" -p backend -t python,core

# Check live status
vlogger status

# Stop active timer
vlogger stop

# Toggle on/off (great for single-key shortcuts)
vlogger toggle "Deep Work"

# Manually log past work
vlogger add 45m "Code review" -p reviews

# Export for external databases, pipelines, or spreadsheets
vlogger export --format json --out work_logs.json
vlogger export --format csv --out work_logs.csv
```

---

## Interactive TUI (Vim Keybindings)

Run `vlogger` in any terminal (like Kitty):

```
┌──────────────────────────────── Active Tracker ────────────────────────────────┐
│  ● RUNNING      Elapsed: 01:24:35     (since 11:20:00)                         │
│                                                                                │
│  Description: [ Refactor authentication middleware ________________________ ] │
│                                                                                │
│  [s: STOP]      [i: Edit Desc]      [d: Reset Default]   [D: Save as Default]  │
└────────────────────────────────────────────────────────────────────────────────┘
┌───────────────────── Recent Work Logs (Today: 03h 45m in 4 entries) ────────────┐
│   ID    START      END        DURATION   DESCRIPTION                           │
│ ────────────────────────────────────────────────────────────────────────────── │
│ > #4    09-21 11:20 [Active]   01:24:35   Refactor authentication middleware   │
│   #3    09-21 10:15 11:00      00:45:00   Client sprint sync                   │
│   #2    09-21 09:00 10:00      01:00:00   Review pull requests                 │
└────────────────────────────────────────────────────────────────────────────────┘
-- NORMAL --   s: Start/Stop | i: Edit | d: Default | j/k: Nav | x: Del | ?: Help
```

### Keybinding Reference

| Mode | Key | Action |
| :--- | :--- | :--- |
| **Normal** | `s` or `<Space>` | **Toggle Start / Stop** timer |
| **Normal** | `i` or `a` or `e` | **Enter Insert Mode** to edit description field |
| **Normal** | `d` | **Reset description** to configured default |
| **Normal** | `D` | **Save current description** as the new default |
| **Normal** | `j` / `k` (or `↓` / `↑`) | Scroll through history entries |
| **Normal** | `g` / `G` | Jump to top / bottom of history |
| **Normal** | `x` | Delete selected entry (prompts `y/n` confirmation) |
| **Normal** | `r` | Reload/refresh data from SQLite |
| **Normal** | `?` | Toggle help modal cheat sheet |
| **Normal** | `q` | Quit TUI (*active timer keeps running in background!*) |
| **Insert** | `<Enter>` | Accept description, update timer in DB, return to Normal mode |
| **Insert** | `<Esc>` | Cancel edits, return to Normal mode |
| **Insert** | `Ctrl-u` | Clear description field |
| **Insert** | `Ctrl-w` | Delete previous word |
| **Insert** | `Ctrl-a` / `Ctrl-e` | Move cursor to beginning / end of line |

---

## Arch Linux & Hyprland Integration

### 1. Hyprland Floating Window & Keybindings

Add to your `~/.config/hypr/hyprland.conf`:

```conf
# Float and center vlogger Kitty window
windowrulev2 = float, class:^(vlogger)$
windowrulev2 = size 850 520, class:^(vlogger)$
windowrulev2 = center, class:^(vlogger)$

# Keybind: Open/toggle vlogger popup
bind = $mainMod, T, exec, kitty --class vlogger -e vlogger

# Keybind: Background toggle start/stop without opening window
bind = $mainMod SHIFT, T, exec, vlogger toggle
```

### 2. Waybar Live Status Bar Module

Add to your `~/.config/waybar/config` (in `modules-right` or `modules-center`):

```jsonc
"custom/vlogger": {
    "format": "{}",
    "exec": "vlogger status --waybar",
    "return-type": "json",
    "interval": 2,
    "on-click": "vlogger toggle",
    "on-click-right": "kitty --class vlogger -e vlogger"
}
```

- **Left click**: Toggles timer start/stop instantly.
- **Right click**: Opens the interactive TUI in Kitty.
- **Display**: Shows live elapsed ticker `󰔟 00:45:12 (Task Name)`.

---

## Exporting Data for Larger Systems

`vlogger` stores all entries in SQLite with ISO 8601 timestamps with explicit UTC timezone offsets and integer durations in seconds.

### Formats Supported

#### JSON
```bash
vlogger export --format json
```
```json
[
  {
    "id": 1,
    "description": "Refactor authentication middleware",
    "project": "backend",
    "tags": ["auth", "security"],
    "start_time": "2026-09-21T11:20:00.000000+02:00",
    "end_time": "2026-09-21T12:44:35.000000+02:00",
    "duration_seconds": 5075,
    "duration_formatted": "01:24:35",
    "created_at": "2026-09-21T11:20:00.000000+02:00",
    "updated_at": "2026-09-21T12:44:35.000000+02:00",
    "is_active": false
  }
]
```

#### JSON Lines (JSONL - Ideal for streaming / BigQuery / ELK pipelines)
```bash
vlogger export --format jsonl --out entries.jsonl
```

#### CSV (Spreadsheets, PostgreSQL COPY, ClickHouse)
```bash
vlogger export --format csv --out entries.csv
```

### Date and Project Filters
```bash
# Export entries since a specific date
vlogger export --since 2026-09-01 --out sept_work.csv

# Export by project
vlogger export --project backend --format json
```

---

## SQLite Database Direct Access

You can inspect or query the SQLite database directly with `sqlite3`:

```bash
sqlite3 ~/.local/share/vlogger/vlogger.db "SELECT id, description, duration_seconds FROM entries;"
```

### Schema

```sql
CREATE TABLE entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT 'default',
    tags TEXT NOT NULL DEFAULT '',
    start_time TEXT NOT NULL,
    end_time TEXT,
    duration_seconds INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

---

## Configuration

Settings are stored in the SQLite database and can be configured via CLI or directly in the TUI:

```bash
# List all settings
vlogger config list

# Set default description
vlogger config set default_description "Deep Work"

# Get current default description
vlogger config get default_description
```

---

## Running Tests

All unit tests use Python's built-in `unittest` runner:

```bash
python3 -m unittest discover -s tests
```
