import atexit
import os
import re
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from vlogger.db import Database
from vlogger.models import TimeEntry

_ACTIVE_SYNC_THREADS: List[threading.Thread] = []


def _cleanup_sync_threads(timeout: float = 3.0) -> None:
    for t in list(_ACTIVE_SYNC_THREADS):
        if t.is_alive():
            t.join(timeout=timeout)


atexit.register(_cleanup_sync_threads)


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

    @property
    def html_report_path(self) -> Path:
        env_path = os.environ.get("VLOGGER_REPORT_PATH") or os.environ.get("VLOGGER_HTML")
        if env_path:
            return Path(env_path).expanduser().resolve()
        setting_val = self.db.get_setting("html_report_path")
        if setting_val:
            return Path(setting_val).expanduser().resolve()
        return self.db.db_path.parent / "ekselek.html"

    @property
    def html_report_readonly(self) -> bool:
        setting_val = self.db.get_setting("html_report_readonly", "true").lower()
        return setting_val in ("1", "true", "yes", "on")

    @property
    def auto_generate_html(self) -> bool:
        setting_val = self.db.get_setting("auto_generate_html", "true").lower()
        return setting_val in ("1", "true", "yes", "on")

    def generate_html_report(self, out_path: Optional[Path] = None) -> Path:
        """Generate the static HTML progress report."""
        from vlogger.html_report import write_html_report
        target = out_path or self.html_report_path
        return write_html_report(self.db, target, read_only=self.html_report_readonly)

    def generate_html_report_safe(self, out_path: Optional[Path] = None) -> Optional[Path]:
        """Safely generate the static HTML progress report, ignoring any errors."""
        if not self.auto_generate_html:
            return None
        try:
            target = self.generate_html_report(out_path=out_path)
            self._trigger_sync_cmd_safe(target)
            return target
        except Exception:
            return None

    def _log_sync_error(self, error_msg: str) -> None:
        """Append sync failures with timestamp to ~/.local/share/vlogger/sync.log."""
        try:
            log_file = self.db.db_path.parent / "sync.log"
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{now_str}] Sync error: {error_msg}\n")
        except Exception:
            pass

    def _run_sync_worker(self, target_path: Path, cmd_formatted: str) -> None:
        current_thread = threading.current_thread()
        try:
            import subprocess
            res = subprocess.run(
                ["sh", "-c", cmd_formatted],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30.0,
                text=True,
            )
            if res.returncode != 0:
                err = res.stderr.strip() or res.stdout.strip() or f"exit code {res.returncode}"
                self._log_sync_error(err)
        except Exception as ex:
            self._log_sync_error(str(ex))
        finally:
            if current_thread in _ACTIVE_SYNC_THREADS:
                try:
                    _ACTIVE_SYNC_THREADS.remove(current_thread)
                except ValueError:
                    pass

    def wait_for_sync(self, timeout: float = 3.0) -> None:
        """Wait for any background sync operation to complete."""
        t = getattr(self, "_active_sync_thread", None)
        if t and t.is_alive():
            t.join(timeout=timeout)

    def sync_html_report(
        self,
        path: Optional[Path] = None,
        wait: bool = False,
        timeout: Optional[float] = 30.0,
    ) -> tuple[bool, str]:
        """Run post-generate sync hook if configured in settings (e.g. scp or rsync).
        Returns (success: bool, message: str)."""
        cmd = self.db.get_setting("html_sync_cmd")
        if not cmd or not cmd.strip():
            return False, "No 'html_sync_cmd' configured in settings."

        target_path = path or self.html_report_path
        cmd_formatted = cmd.replace("{file}", str(target_path)).replace("{path}", str(target_path))
        try:
            import subprocess
            if wait:
                res = subprocess.run(
                    ["sh", "-c", cmd_formatted],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                    text=True,
                )
                if res.returncode == 0:
                    return True, "Synced successfully."
                else:
                    err = res.stderr.strip() or res.stdout.strip() or f"exit code {res.returncode}"
                    self._log_sync_error(err)
                    return False, f"Sync command failed: {err}"
            else:
                t = threading.Thread(
                    target=self._run_sync_worker,
                    args=(target_path, cmd_formatted),
                    daemon=False,
                )
                _ACTIVE_SYNC_THREADS.append(t)
                self._active_sync_thread = t
                t.start()
                return True, "Sync command started in background."
        except Exception as ex:
            self._log_sync_error(str(ex))
            return False, f"Failed to execute sync command: {ex}"

    def _trigger_sync_cmd_safe(self, path: Path) -> None:
        """Run post-generate sync hook safely in background worker without throwing exceptions."""
        try:
            self.sync_html_report(path, wait=False)
        except Exception:
            pass

    def start(
        self,
        description: Optional[str] = None,
        project: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> TimeEntry:
        desc = description.strip() if description and description.strip() else self.default_description
        entry = self.db.start_timer(description=desc, project=project, tags=tags)
        self.generate_html_report_safe()
        return entry

    def stop(self) -> Optional[TimeEntry]:
        stopped = self.db.stop_timer()
        if stopped:
            self.generate_html_report_safe()
        return stopped

    def update_entry(
        self,
        entry_id: int,
        description: Optional[str] = None,
        project: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[TimeEntry]:
        entry = self.db.update_entry(entry_id, description=description, project=project, tags=tags)
        if entry:
            self.generate_html_report_safe()
        return entry

    def delete_entry(self, entry_id: int) -> bool:
        deleted = self.db.delete_entry(entry_id)
        if deleted:
            self.generate_html_report_safe()
        return deleted

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
        entry = self.db.add_manual_entry(
            description=desc,
            duration_seconds=sec,
            project=project,
            tags=tags,
        )
        self.generate_html_report_safe()
        return entry

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

    @staticmethod
    def calculate_daily_summary(daily_stats: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute aggregate summary metrics across daily stats."""
        total_sec = sum(d["total_seconds"] for d in daily_stats)
        total_cnt = sum(d["count"] for d in daily_stats)
        active_days = [d for d in daily_stats if d["total_seconds"] > 0 or d["count"] > 0]
        active_days_cnt = len(active_days)

        avg_sec = total_sec // active_days_cnt if active_days_cnt > 0 else 0

        peak_day_str = "-"
        max_sec = 0
        for d in daily_stats:
            if d["total_seconds"] > max_sec:
                max_sec = d["total_seconds"]
                peak_day_str = d["date"]

        return {
            "total_seconds": total_sec,
            "total_formatted": TimeEntry.format_duration(total_sec),
            "compact_duration": TimeEntry.format_duration(total_sec, compact=True),
            "total_entries": total_cnt,
            "active_days": active_days_cnt,
            "average_daily_seconds": avg_sec,
            "average_daily_formatted": TimeEntry.format_duration(avg_sec, compact=True),
            "max_day_seconds": max_sec,
            "max_day_formatted": TimeEntry.format_duration(max_sec, compact=True),
            "peak_day": peak_day_str,
        }

    def get_daily_stats(
        self,
        days_limit: int = 30,
        since: Optional[str] = None,
        until: Optional[str] = None,
        project: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Return daily aggregated statistics and overall summary."""
        days = self.db.get_daily_stats(
            days_limit=days_limit,
            since=since,
            until=until,
            project=project,
        )
        summary = self.calculate_daily_summary(days)
        return days, summary

    @staticmethod
    def calculate_weekly_summary(weekly_stats: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute aggregate summary metrics across weekly stats."""
        total_sec = sum(w["total_seconds"] for w in weekly_stats)
        total_cnt = sum(w["count"] for w in weekly_stats)
        active_weeks = [w for w in weekly_stats if w["total_seconds"] > 0 or w["count"] > 0]
        active_weeks_cnt = len(active_weeks)

        avg_sec = total_sec // active_weeks_cnt if active_weeks_cnt > 0 else 0

        peak_week_str = "-"
        max_sec = 0
        for w in weekly_stats:
            if w["total_seconds"] > max_sec:
                max_sec = w["total_seconds"]
                peak_week_str = w.get("week", "-")

        return {
            "total_seconds": total_sec,
            "total_formatted": TimeEntry.format_duration(total_sec),
            "compact_duration": TimeEntry.format_duration(total_sec, compact=True),
            "total_entries": total_cnt,
            "active_weeks": active_weeks_cnt,
            "average_weekly_seconds": avg_sec,
            "average_weekly_formatted": TimeEntry.format_duration(avg_sec, compact=True),
            "max_week_seconds": max_sec,
            "max_week_formatted": TimeEntry.format_duration(max_sec, compact=True),
            "peak_week": peak_week_str,
        }

    def get_weekly_stats(
        self,
        weeks_limit: int = 26,
        since: Optional[str] = None,
        until: Optional[str] = None,
        project: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Return weekly aggregated statistics and overall summary."""
        weeks = self.db.get_weekly_stats(
            weeks_limit=weeks_limit,
            since=since,
            until=until,
            project=project,
        )
        summary = self.calculate_weekly_summary(weeks)
        return weeks, summary

    @staticmethod
    def calculate_monthly_summary(monthly_stats: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute aggregate summary metrics across monthly stats."""
        total_sec = sum(m["total_seconds"] for m in monthly_stats)
        total_cnt = sum(m["count"] for m in monthly_stats)
        active_months = [m for m in monthly_stats if m["total_seconds"] > 0 or m["count"] > 0]
        active_months_cnt = len(active_months)

        avg_sec = total_sec // active_months_cnt if active_months_cnt > 0 else 0

        peak_month_str = "-"
        max_sec = 0
        for m in monthly_stats:
            if m["total_seconds"] > max_sec:
                max_sec = m["total_seconds"]
                peak_month_str = m.get("month_name") or m.get("month", "-")

        return {
            "total_seconds": total_sec,
            "total_formatted": TimeEntry.format_duration(total_sec),
            "compact_duration": TimeEntry.format_duration(total_sec, compact=True),
            "total_entries": total_cnt,
            "active_months": active_months_cnt,
            "average_monthly_seconds": avg_sec,
            "average_monthly_formatted": TimeEntry.format_duration(avg_sec, compact=True),
            "max_month_seconds": max_sec,
            "max_month_formatted": TimeEntry.format_duration(max_sec, compact=True),
            "peak_month": peak_month_str,
        }

    def get_monthly_stats(
        self,
        months_limit: int = 12,
        since: Optional[str] = None,
        until: Optional[str] = None,
        project: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Return monthly aggregated statistics and overall summary."""
        months = self.db.get_monthly_stats(
            months_limit=months_limit,
            since=since,
            until=until,
            project=project,
        )
        summary = self.calculate_monthly_summary(months)
        return months, summary

