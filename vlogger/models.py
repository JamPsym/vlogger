"""Data models for vlogger."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
import json


@dataclass
class TimeEntry:
    id: Optional[int] = None
    description: str = ""
    project: str = "default"
    tags: List[str] = field(default_factory=list)
    start_time: str = ""  # ISO 8601 string with timezone
    end_time: Optional[str] = None  # None if active
    duration_seconds: Optional[int] = None
    created_at: str = ""
    updated_at: str = ""

    @property
    def is_active(self) -> bool:
        return self.end_time is None

    def calculate_duration(self, current_dt: Optional[datetime] = None) -> int:
        """Returns duration in seconds. If active, calculates against current time."""
        if self.duration_seconds is not None and not self.is_active:
            return self.duration_seconds
        
        if not self.start_time:
            return 0
            
        try:
            start_dt = datetime.fromisoformat(self.start_time)
            if self.end_time:
                end_dt = datetime.fromisoformat(self.end_time)
            else:
                end_dt = current_dt or datetime.now().astimezone()
            diff = int((end_dt - start_dt).total_seconds())
            return max(0, diff)
        except Exception:
            return self.duration_seconds or 0

    @staticmethod
    def format_duration(seconds: int, compact: bool = False) -> str:
        """Format seconds into HH:MM:SS or 1h 23m 45s."""
        if seconds < 0:
            seconds = 0
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60

        if compact:
            if h > 0:
                return f"{h}h {m}m"
            if m > 0:
                return f"{m}m {s}s"
            return f"{s}s"
        return f"{h:02d}:{m:02d}:{s:02d}"

    def to_dict(self) -> dict:
        """Convert entry to dictionary for export."""
        dur = self.calculate_duration()
        return {
            "id": self.id,
            "description": self.description,
            "project": self.project,
            "tags": self.tags,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": dur,
            "duration_formatted": self.format_duration(dur),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_active": self.is_active,
        }
