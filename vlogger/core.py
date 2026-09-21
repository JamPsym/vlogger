"""Core business logic and duration parsing for vlogger."""

import re
from datetime import datetime
from typing import Optional, Dict, Any, List

from vlogger.db import Database
from vlogger.models import TimeEntry


def parse_duration(duration_str: str) -> int:
    """Parse string representations like '45m', '1h30m', '2.5h', '90s', '1h 15m' into seconds."""
    s = duration_str.strip().lower()
    
    # Try pure integer/float assumed as minutes or hours? Better require unit or default to minutes if bare number
    if s.isdigit():
        # Bare number: treat as minutes
        return int(s) * 60

    # Match decimal hours e.g. "1.5h" or "2.5 hrs"
    m_dec = re.match(r"^(\d+(?:\.\d+)?)\s*(?:h|hr|hours?)$", s)
    if m_dec:
        return int(float(m_dec.group(1)) * 3600)

    # General pattern for sequences of (\d+)([hms])
    tokens = re.findall(r"(\d+)\s*([hms])", s)
    if not tokens:
        raise ValueError(
            f"Cannot parse duration '{duration_str}'. Use formats like '45m', '1h30m', '2h', or '90s'."
        )

    total_seconds = 0
    for val, unit in tokens:
        n = int(val)
        if unit == "h":
            total_seconds += n * 3600
        elif unit == "m":
            total_seconds += n * 60
        elif unit == "s":
            total_seconds += n

    return total_seconds


class VLoggerCore:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()

    @property
    def default_description(self) -> str:
        last = self.db.get_last_description()
        if last:
            return last
        return self.db.get_setting("default_description", "Work")

    @default_description.setter
    def default_description(self, val: str) -> None:
        self.db.set_setting("default_description", val.strip())

    def get_unique_descriptions(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.db.get_recent_descriptions(limit=limit)

    def start(
        self,
        description: Optional[str] = None,
        project: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> TimeEntry:
        desc = description.strip() if description and description.strip() else self.default_description
        return self.db.start_timer(description=desc, project=project, tags=tags)

    def stop(self) -> Optional[TimeEntry]:
        return self.db.stop_timer()

    def toggle(
        self,
        description: Optional[str] = None,
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Toggles timer on/off. Useful for single Hyprland keybind or waybar click."""
        active = self.db.get_active_entry()
        if active:
            stopped = self.stop()
            return {
                "action": "stopped",
                "entry": stopped,
                "message": f"Stopped: '{stopped.description}' ({TimeEntry.format_duration(stopped.calculate_duration())})"
            }
        else:
            started = self.start(description=description, project=project)
            return {
                "action": "started",
                "entry": started,
                "message": f"Started: '{started.description}'"
            }

    def add_manual(
        self,
        duration_str: str,
        description: Optional[str] = None,
        project: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> TimeEntry:
        sec = parse_duration(duration_str)
        desc = description.strip() if description and description.strip() else self.default_description
        return self.db.add_manual_entry(
            description=desc,
            duration_seconds=sec,
            project=project,
            tags=tags,
        )

    def get_status_info(self) -> Dict[str, Any]:
        active = self.db.get_active_entry()
        today_stats = self.db.get_stats_for_today()
        if active:
            elapsed = active.calculate_duration()
            return {
                "is_active": True,
                "entry": active,
                "elapsed_seconds": elapsed,
                "elapsed_formatted": TimeEntry.format_duration(elapsed),
                "description": active.description,
                "project": active.project,
                "start_time": active.start_time,
                "today_total_seconds": today_stats["total_seconds"],
                "today_total_formatted": TimeEntry.format_duration(today_stats["total_seconds"]),
                "today_count": today_stats["count"],
            }
        else:
            return {
                "is_active": False,
                "entry": None,
                "elapsed_seconds": 0,
                "elapsed_formatted": "00:00:00",
                "description": None,
                "project": None,
                "start_time": None,
                "today_total_seconds": today_stats["total_seconds"],
                "today_total_formatted": TimeEntry.format_duration(today_stats["total_seconds"]),
                "today_count": today_stats["count"],
            }

    def get_waybar_payload(self) -> Dict[str, Any]:
        """Generate JSON payload compatible with Waybar custom module."""
        status = self.get_status_info()
        today_fmt = status["today_total_formatted"]
        if status["is_active"]:
            elapsed = status["elapsed_formatted"]
            desc = status["description"]
            text = f"󰔟 {elapsed} ({desc})"
            tooltip = (
                f"Task: {desc}\n"
                f"Elapsed: {elapsed}\n"
                f"Started: {status['start_time']}\n"
                f"Today Total: {today_fmt} ({status['today_count']} entries)\n"
                f"Click: Toggle Start/Stop"
            )
            return {
                "text": text,
                "tooltip": tooltip,
                "class": "running",
                "alt": "running",
            }
        else:
            text = f"󰔟 Idle (Today: {today_fmt})"
            tooltip = f"No active timer.\nToday Total: {today_fmt} ({status['today_count']} entries)\nClick: Start timer"
            return {
                "text": text,
                "tooltip": tooltip,
                "class": "stopped",
                "alt": "stopped",
            }
