# ⚡ vlogger

> **Minimalist, keyboard-first work time-logger with Vim keybindings, SQLite storage, and clean export.**
> Designed for Arch Linux + Hyprland, built with zero external dependencies (pure Python standard library).

---

## Features

- **Keyboard-First Vim Workflow**: Interactive curses TUI inside Kitty terminal with modal Vim controls (`s` to toggle, `i` to edit description, `j`/`k` to navigate history, `x` to delete, `d` to reset default).
- **Persistent SQLite Engine**: Stored in `~/.local/share/vlogger/vlogger.db` with WAL mode enabled for concurrent reads/writes without locks.
- **Auto-Generated Static HTML Dashboard**: Automatically refreshed after each task completion to `~/.local/share/vlogger/progress.html`. Self-contained with pure CSS & SVG (zero external CDNs or network requests), responsive dark theme, daily stats, visual activity bar chart, live log filter, and print-to-PDF support.
- **Future-Proof Clean Export**: Export your logs at any time to **JSON**, **JSONL (Lines)**, **CSV**, or **HTML** with standard ISO 8601 timestamps, duration in seconds, project labels, and tags.
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

# Edit / rename a past entry
vlogger edit 4 "Refactored user authentication"

# View daily statistics and summary breakdown
vlogger stats
vlogger stats --days 30
vlogger stats --json

# View and generate static HTML progress dashboard
vlogger report
vlogger report --open

# Export for external databases, pipelines, or spreadsheets
vlogger export --format json --out work_logs.json
vlogger export --format csv --out work_logs.csv
vlogger export --format html --out progress.html
```

---

## Interactive TUI (Vim Keybindings & Views)

Run `vlogger` in any terminal (like Kitty):

```
┌──────────────────────────────── Active Tracker ────────────────────────────────┐
│  ● RUNNING      Elapsed: 01:24:35     (since 11:20:00)                         │
│                                                                                │
│  Description: [ Refactor authentication middleware ________________________ ] │
│                                                                                │
│  [s: STOP]      [i: Edit]      [p: Pick Past]       [d: Last Desc]             │
└────────────────────────────────────────────────────────────────────────────────┘
╭──[ 1: Logs ]──[ 2: Daily ]──[ 3: Weekly ]──[ 4: Monthly ]── (Today: 03h 45m) ──╮
│   ID    START      END        DURATION   DESCRIPTION                           │
│ ────────────────────────────────────────────────────────────────────────────── │
│ > #4    09-21 11:20 [Active]   01:24:35   Refactor authentication middleware   │
│   #3    09-21 10:15 11:00      00:45:00   Client sprint sync                   │
│   #2    09-21 09:00 10:00      01:00:00   Review pull requests                 │
╰────────────────────────────────────────────────────────────────────────────────╯
-- NORMAL --   Tab/v: Switch view (1-4) | s: Start/Stop | i: Edit | p: Pick | y: Yank
```

Press **`<Tab>`**, **`v`**, or **`1`** / **`2`** / **`3`** / **`4`** to switch between views:
- **`1: Logs`**: Chronological log of recent time entries with inline editing and deletion.
- **`2: Daily Stats`**: Daily aggregates with activity bars, top task breakdowns, and session details modal.
- **`3: Weekly Stats`**: ISO week summaries (`YYYY-Www`), weekly averages, active day counts, and daily breakdowns.
- **`4: Monthly Stats`**: Monthly summaries (`YYYY-MM`), active day counts, top projects, and weekly breakdowns.

```
╭──[ 1: Logs ]──[ 2: Daily ]──[ 3: Weekly ]──[ 4: Monthly ]── (Total: 42h 10m) ──╮
│   Total: 42h 10m across 7 active days  │  Daily Avg: 06h 01m  │  Peak: 09-21    │
│ ────────────────────────────────────────────────────────────────────────────── │
│   DATE         DAY         DURATION   ENTRIES   ACTIVITY BAR TOP TASKS         │
│ > 2026-09-22   Tue [Today] 04:15:00   3 ent     ██████░░░░   Refactor auth ... │
│   2026-09-21   Mon         07:45:00   5 ent     ██████████   API dev, Sync ... │
│ ── Breakdown: 2026-09-22 (Tuesday) ─ 04:15:00 in 3 sessions ─────────────────── │
│   • Refactor authentication middleware: 3h 00m (70.6%) ─ 2 sessions            │
│   • Code review: 1h 15m (29.4%) ─ 1 session                                    │
╰────────────────────────────────────────────────────────────────────────────────╯
-- NORMAL --   Tab/v: Switch view (1-4) | Enter: View Details | j/k: Nav | y: Yank
```

### Keybinding Reference

| Mode | Key | Action |
| :--- | :--- | :--- |
| **Normal** | `<Tab>` or `v` | **Cycle through Views** (Logs → Daily → Weekly → Monthly) |
| **Normal** | `1` / `2` / `3` / `4` | **Switch directly** to Logs (`1`), Daily (`2`), Weekly (`3`), or Monthly (`4`) view |
| **Normal** | `s` or `<Space>` | **Toggle Start / Stop** timer (runs across all views) |
| **Normal** | `i` or `a` | **Edit active tracker description** |
| **Normal** | `p` | **Pick from list of unique past tasks** (prevents duplicate typos) |
| **Normal** | `y` | **Yank (copy)** selected history entry or period's top task to tracker |
| **Normal** | `e` or `<Enter>` | **Edit log entry** (Logs view) / **Open period details modal** (Stats/Weekly/Monthly) |
| **Normal** | `d` | **Reset active description** to the last used task |
| **Normal** | `D` | **Save current active description** as the new fallback default |
| **Normal** | `j` / `k` (or `↓` / `↑`) | Scroll through history entries or summary statistics |
| **Normal** | `g` / `G` | Jump to top / bottom of current list |
| **Normal** | `x` | Delete selected entry (prompts `y/n` confirmation) |
| **Normal** | `r` | Reload/refresh data from SQLite |
| **Normal** | `?` | Toggle help modal cheat sheet |
| **Normal** | `q` | Quit TUI (*active timer keeps running in background!*) |
| **Insert** | `<Tab>` or `Ctrl-p` | **Open pick list** while typing |
| **Insert / Edit** | `<Enter>` | Save changes and return to Normal mode |
| **Insert / Edit** | `<Esc>` | Cancel edits, return to Normal mode |
| **Insert / Edit** | `Ctrl-u` | Clear description field |
| **Insert / Edit** | `Ctrl-w` | Delete previous word |
| **Insert / Edit** | `Ctrl-a` / `Ctrl-e` | Move cursor to beginning / end of line |
| **Modal / Detail** | `<Esc>` / `<Enter>` / `q` | Close details modal |

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

#### HTML (Interactive Static Progress Dashboard — "ekselek")
```bash
vlogger export --format html --out ekselek.html
# Or directly via report command:
vlogger report --open
```

> **Automatic Generation & Read-Only Permissions**:
> The HTML dashboard (`~/.local/share/vlogger/ekselek.html`) regenerates automatically every time any action is taken (`start`, `stop`, `toggle`, manual `add`, rename/edit, or deletion).
> - Written atomically with **read-only permissions** (`chmod 444` / `r--r--r--`), making it tamper-proof and safe for public hosting.
> - Displayed as a clean **`[ 🔒 READ-ONLY MONITOR ]`** with viewer shortcuts (<kbd>Tab</kbd>, <kbd>1</kbd>, <kbd>2</kbd>, <kbd>j</kbd>/<kbd>k</kbd>, <kbd>Enter</kbd> for day details, <kbd>r</kbd> to reload).
> - Active task displays `● RUNNING` in green with a live JavaScript ticking timer.
> - Automatically detects file updates on disk and reloads seamlessly when hosted over HTTP.

### Public Hosting & Network Synchronization (Passwordless SSH / SCP / rsync)

To automatically sync the read-only `ekselek` dashboard to a publicly hosted machine on your local network:

1. **Set up SSH key authentication** (run once):
   ```bash
   ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
   ssh-copy-id user@remote-ip
   ```
   *(After this, `ssh`, `scp`, and `rsync` connect instantly without password prompts!)*

2. **Configure an automatic sync hook in vlogger**:
   ```bash
   # Sync via rsync with remote read-only permissions (chmod 444)
   vlogger config set html_sync_cmd "rsync -az --chmod=ugo=r {file} user@remote-ip:/var/www/html/ekselek.html"

   # Or sync directly as a file named 'ekselek'
   vlogger config set html_sync_cmd "rsync -az --chmod=ugo=r {file} user@remote-ip:/var/www/html/ekselek"

   # Or via SCP with remote chmod 444
   vlogger config set html_sync_cmd "scp {file} user@remote-ip:/var/www/html/ekselek.html && ssh user@remote-ip 'chmod 444 /var/www/html/ekselek.html'"
   ```

3. **Public Web Server Configuration (Nginx / Caddy / Python)**:
   - **Nginx** (serve at `/ekselek`):
     ```nginx
     location /ekselek {
         default_type text/html;
         alias /var/www/html/ekselek.html;
     }
     ```
   - **Caddy**:
     ```caddy
     route /ekselek* {
         file_server {
             index ekselek.html
         }
     }
     ```
   - **Quick Python LAN server on remote host**:
     ```bash
     python3 -m http.server 80 --directory /var/www/html
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
