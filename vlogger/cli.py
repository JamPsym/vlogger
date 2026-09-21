"""Command Line Interface for vlogger."""

import argparse
import json
import sys
from datetime import datetime
from typing import Optional

from vlogger.db import Database
from vlogger.models import TimeEntry
from vlogger.core import VLoggerCore, parse_duration
from vlogger.export import export_entries, export_to_file
from vlogger.tui import launch_tui


def format_table(entries, today_stats):
    lines = []
    lines.append(f"{'ID':<5} {'START':<16} {'END':<16} {'DURATION':<10} {'DESCRIPTION'}")
    lines.append("-" * 75)
    for e in entries:
        eid = f"#{e.id}"
        try:
            s_dt = datetime.fromisoformat(e.start_time)
            s_fmt = s_dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            s_fmt = e.start_time[:16]

        if e.is_active:
            e_fmt = "[Active]"
            dur_fmt = TimeEntry.format_duration(e.calculate_duration())
        else:
            try:
                e_dt = datetime.fromisoformat(e.end_time)
                e_fmt = e_dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                e_fmt = "-"
            dur_fmt = TimeEntry.format_duration(e.calculate_duration())

        lines.append(f"{eid:<5} {s_fmt:<16} {e_fmt:<16} {dur_fmt:<10} {e.description}")

    lines.append("-" * 75)
    today_dur = TimeEntry.format_duration(today_stats["total_seconds"])
    lines.append(f"Today's Total: {today_dur} across {today_stats['count']} entries")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        prog="vlogger",
        description="A keyboard-first time logger with Vim bindings, SQLite storage, and clean export.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # TUI
    subparsers.add_parser("tui", help="Launch interactive Vim-style Terminal UI (default)")

    # Start
    p_start = subparsers.add_parser("start", help="Start a new work timer")
    p_start.add_argument("description", nargs="?", help="Task description (defaults to configured default)")
    p_start.add_argument("-p", "--project", help="Project name (default: 'default')")
    p_start.add_argument("-t", "--tags", help="Comma-separated tags")

    # Stop
    subparsers.add_parser("stop", help="Stop currently active work timer")

    # Toggle
    p_toggle = subparsers.add_parser("toggle", help="Toggle timer start/stop (ideal for hotkeys)")
    p_toggle.add_argument("description", nargs="?", help="Description to use if starting")
    p_toggle.add_argument("-p", "--project", help="Project name if starting")

    # Status
    p_status = subparsers.add_parser("status", help="Show current timer status")
    p_status.add_argument("--json", action="store_true", help="Output status as JSON")
    p_status.add_argument("--waybar", action="store_true", help="Output JSON payload for Waybar module")

    # Add (manual entry)
    p_add = subparsers.add_parser("add", help="Manually log completed work (e.g. 45m, 1.5h)")
    p_add.add_argument("duration", help="Duration string, e.g., '45m', '1h30m', '2h', '90s'")
    p_add.add_argument("description", nargs="?", help="Task description")
    p_add.add_argument("-p", "--project", help="Project name")
    p_add.add_argument("-t", "--tags", help="Comma-separated tags")

    # List
    p_list = subparsers.add_parser("list", help="List recent work logs")
    p_list.add_argument("-n", "--limit", type=int, default=20, help="Number of entries to show (default: 20)")
    p_list.add_argument("--since", help="Filter since ISO date/time, e.g. 2026-09-21")
    p_list.add_argument("--until", help="Filter until ISO date/time")
    p_list.add_argument("-p", "--project", help="Filter by project")

    # Export
    p_export = subparsers.add_parser("export", help="Export entries for use in larger systems (JSON, JSONL, CSV)")
    p_export.add_argument("-f", "--format", choices=["json", "jsonl", "csv"], default="json", help="Export format (default: json)")
    p_export.add_argument("-o", "--out", help="Output file path (prints to stdout if not specified)")
    p_export.add_argument("--since", help="Filter since ISO date/time")
    p_export.add_argument("--until", help="Filter until ISO date/time")
    p_export.add_argument("-p", "--project", help="Filter by project")

    # Edit / Rename
    p_edit = subparsers.add_parser("edit", aliases=["rename"], help="Edit description of an existing entry")
    p_edit.add_argument("id", type=int, help="Entry ID to edit (e.g. 1)")
    p_edit.add_argument("description", nargs="?", help="New description (prompts if omitted)")

    # Tasks / Descriptions list
    subparsers.add_parser("tasks", aliases=["descriptions"], help="List unique past task descriptions")

    # Config
    p_config = subparsers.add_parser("config", help="Get or set configuration values")
    p_config.add_argument("action", choices=["get", "set", "list"], help="Action to perform")
    p_config.add_argument("key", nargs="?", help="Config key (e.g. default_description)")
    p_config.add_argument("value", nargs="?", help="Config value to set")

    args = parser.parse_args()
    db = Database()
    core = VLoggerCore(db)

    if not args.command:
        # Default behavior: Launch TUI if running interactively in terminal
        if sys.stdin.isatty() and sys.stdout.isatty():
            launch_tui(db)
            return
        else:
            # Fallback to status if non-interactive
            status = core.get_status_info()
            if status["is_active"]:
                print(f"● RUNNING: {status['description']} ({status['elapsed_formatted']})")
            else:
                print("■ STOPPED: No active timer")
            return

    if args.command == "tui":
        launch_tui(db)

    elif args.command == "start":
        tags = [t.strip() for t in args.tags.split(",")] if args.tags else None
        entry = core.start(description=args.description, project=args.project, tags=tags)
        print(f"Started timer #{entry.id}: '{entry.description}' at {entry.start_time}")

    elif args.command == "stop":
        entry = core.stop()
        if entry:
            dur = TimeEntry.format_duration(entry.calculate_duration())
            print(f"Stopped timer #{entry.id}: '{entry.description}' (Duration: {dur})")
        else:
            print("No active timer to stop.")

    elif args.command == "toggle":
        res = core.toggle(description=args.description, project=args.project)
        print(res["message"])

    elif args.command == "status":
        if args.waybar:
            print(json.dumps(core.get_waybar_payload()))
        elif args.json:
            status_data = core.get_status_info()
            if status_data["entry"]:
                status_data["entry"] = status_data["entry"].to_dict()
            print(json.dumps(status_data, indent=2))
        else:
            status = core.get_status_info()
            if status["is_active"]:
                print(f"● ACTIVE: '{status['description']}' | Elapsed: {status['elapsed_formatted']} (Started: {status['start_time']})")
            else:
                print("■ IDLE: No timer running.")
            print(f"Today's Total: {status['today_total_formatted']} ({status['today_count']} entries)")

    elif args.command == "add":
        tags = [t.strip() for t in args.tags.split(",")] if args.tags else None
        entry = core.add_manual(
            duration_str=args.duration,
            description=args.description,
            project=args.project,
            tags=tags,
        )
        dur = TimeEntry.format_duration(entry.calculate_duration())
        print(f"Added manual entry #{entry.id}: '{entry.description}' ({dur})")

    elif args.command == "list":
        entries = db.list_entries(limit=args.limit, since=args.since, until=args.until, project=args.project)
        today_stats = db.get_stats_for_today()
        print(format_table(entries, today_stats))

    elif args.command == "export":
        if args.out:
            count = export_to_file(
                db,
                file_path=args.out,
                fmt=args.format,
                since=args.since,
                until=args.until,
                project=args.project,
            )
            print(f"Exported {count} entries to '{args.out}' in {args.format.upper()} format.")
        else:
            output = export_entries(
                db,
                fmt=args.format,
                since=args.since,
                until=args.until,
                project=args.project,
            )
            print(output, end="")

    elif args.command in ("edit", "rename"):
        entry = db.get_entry(args.id)
        if not entry:
            print(f"Error: Entry #{args.id} not found.")
            sys.exit(1)
        new_desc = args.description
        if not new_desc:
            print(f"Current description: '{entry.description}'")
            try:
                new_desc = input("New description: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nCancelled.")
                sys.exit(0)
        if not new_desc:
            print("Description cannot be empty.")
            sys.exit(1)
        updated = db.update_entry(args.id, description=new_desc)
        print(f"Updated entry #{updated.id}: '{updated.description}'")

    elif args.command in ("tasks", "descriptions"):
        items = core.get_unique_descriptions()
        if not items:
            print("No past tasks recorded yet.")
        else:
            print(f"{'COUNT':<7} {'LAST USED':<18} {'DESCRIPTION'}")
            print("-" * 65)
            for it in items:
                cnt = f"{it['count']}x"
                last_u = it['last_used'][:16] if it['last_used'] else "-"
                print(f"{cnt:<7} {last_u:<18} {it['description']}")

    elif args.command == "config":
        if args.action == "list":
            with db.get_connection() as conn:
                rows = conn.execute("SELECT key, value FROM settings").fetchall()
                for r in rows:
                    print(f"{r['key']} = {r['value']}")
        elif args.action == "get":
            if not args.key:
                print("Error: key is required for 'config get'.")
                sys.exit(1)
            val = db.get_setting(args.key)
            if val is not None:
                print(val)
            else:
                print(f"Key '{args.key}' not found.")
                sys.exit(1)
        elif args.action == "set":
            if not args.key or args.value is None:
                print("Error: key and value are required for 'config set'.")
                sys.exit(1)
            db.set_setting(args.key, args.value)
            print(f"Saved: {args.key} = {args.value}")


if __name__ == "__main__":
    main()
