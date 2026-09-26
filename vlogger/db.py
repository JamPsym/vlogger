"""SQLite Database layer with WAL mode and robust schema for vlogger."""

import os
import sqlite3
from pathlib import Path
from datetime import date, datetime, time, timedelta
from typing import Optional, List, Dict, Any

from vlogger.models import TimeEntry

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "vlogger" / "vlogger.db"


def get_db_path() -> Path:
    env_path = os.environ.get("VLOGGER_DB")
    if env_path:
        p = Path(env_path).expanduser().resolve()
    else:
        p = DEFAULT_DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


from contextlib import contextmanager


class Database:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_db_path()
        self._init_db()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self.get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS entries (
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

                CREATE INDEX IF NOT EXISTS idx_entries_start_time ON entries(start_time);
                CREATE INDEX IF NOT EXISTS idx_entries_project ON entries(project);
                CREATE INDEX IF NOT EXISTS idx_entries_end_time ON entries(end_time);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

            # Set default settings if not exists
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM settings WHERE key = 'default_description'")
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO settings (key, value) VALUES ('default_description', ?)",
                    ("Work",),
                )
            cursor.execute("SELECT 1 FROM settings WHERE key = 'default_project'")
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO settings (key, value) VALUES ('default_project', 'default')"
                )
            cursor.execute("SELECT 1 FROM settings WHERE key = 'auto_generate_html'")
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO settings (key, value) VALUES ('auto_generate_html', 'true')"
                )

            # Older versions could leave several timers active after concurrent starts.
            # Close the older ones at the newest timer's start before enforcing the invariant.
            active_rows = conn.execute(
                "SELECT id, start_time FROM entries WHERE end_time IS NULL"
            ).fetchall()
            active_rows = sorted(
                active_rows,
                key=lambda row: (datetime.fromisoformat(row["start_time"]).astimezone(), row["id"]),
                reverse=True,
            )
            if len(active_rows) > 1:
                newest_start = active_rows[0]["start_time"]
                newest_dt = datetime.fromisoformat(newest_start).astimezone()
                for row in active_rows[1:]:
                    duration = max(0, int((newest_dt - datetime.fromisoformat(row["start_time"]).astimezone()).total_seconds()))
                    conn.execute(
                        "UPDATE entries SET end_time = ?, duration_seconds = ?, updated_at = ? WHERE id = ?",
                        (newest_start, duration, newest_start, row["id"]),
                    )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_entries_one_active ON entries((1)) WHERE end_time IS NULL"
            )
            conn.commit()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> TimeEntry:
        tags_raw = row["tags"]
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
        return TimeEntry(
            id=row["id"],
            description=row["description"],
            project=row["project"],
            tags=tags,
            start_time=row["start_time"],
            end_time=row["end_time"],
            duration_seconds=row["duration_seconds"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            if key == "default_description":
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('default_description_explicit', 'true') "
                    "ON CONFLICT(key) DO UPDATE SET value = 'true'"
                )
            conn.commit()

    def get_active_entry(self) -> Optional[TimeEntry]:
        """Return the currently running active timer, if any."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM entries WHERE end_time IS NULL ORDER BY julianday(start_time) DESC, id DESC LIMIT 1"
            )
            row = cur.fetchone()
            return self._row_to_entry(row) if row else None

    def start_timer(
        self,
        description: str,
        project: Optional[str] = None,
        tags: Optional[List[str]] = None,
        start_dt: Optional[datetime] = None,
    ) -> TimeEntry:
        """Atomically stop the old timer and start a new one."""
        proj = project or self.get_setting("default_project", "default")
        tags_str = ",".join(tags) if tags else ""

        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now_dt = (start_dt or datetime.now().astimezone()).astimezone()
            now_str = now_dt.isoformat()
            active_rows = conn.execute("SELECT id, start_time FROM entries WHERE end_time IS NULL").fetchall()
            for active in active_rows:
                duration = max(0, int((now_dt - datetime.fromisoformat(active["start_time"]).astimezone()).total_seconds()))
                conn.execute(
                    "UPDATE entries SET end_time = ?, duration_seconds = ?, updated_at = ? WHERE id = ?",
                    (now_str, duration, now_str, active["id"]),
                )
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO entries (description, project, tags, start_time, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (description.strip(), proj, tags_str, now_str, now_str, now_str),
            )
            conn.commit()
            entry_id = cur.lastrowid
            return self._row_to_entry(conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone())

    def stop_timer(self, end_dt: Optional[datetime] = None) -> Optional[TimeEntry]:
        """Stop the currently active timer."""
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                "SELECT * FROM entries WHERE end_time IS NULL ORDER BY julianday(start_time) DESC, id DESC LIMIT 1"
            ).fetchone()
            if not active:
                return None
            stop_time = (end_dt or datetime.now().astimezone()).astimezone()
            stop_time_str = stop_time.isoformat()
            duration = max(0, int((stop_time - datetime.fromisoformat(active["start_time"]).astimezone()).total_seconds()))
            conn.execute(
                """
                UPDATE entries
                SET end_time = ?, duration_seconds = ?, updated_at = ?
                WHERE id = ?
                """,
                (stop_time_str, duration, stop_time_str, active["id"]),
            )
            conn.commit()
            return self._row_to_entry(conn.execute("SELECT * FROM entries WHERE id = ?", (active["id"],)).fetchone())

    def toggle_timer(self, description: str, project: Optional[str] = None) -> tuple[str, TimeEntry]:
        """Toggle under one write lock, including concurrent hotkey presses."""
        proj = project or self.get_setting("default_project", "default")
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now_dt = datetime.now().astimezone()
            now_str = now_dt.isoformat()
            active = conn.execute(
                "SELECT * FROM entries WHERE end_time IS NULL ORDER BY julianday(start_time) DESC, id DESC LIMIT 1"
            ).fetchone()
            if active:
                duration = max(0, int((now_dt - datetime.fromisoformat(active["start_time"]).astimezone()).total_seconds()))
                conn.execute(
                    "UPDATE entries SET end_time = ?, duration_seconds = ?, updated_at = ? WHERE id = ?",
                    (now_str, duration, now_str, active["id"]),
                )
                entry_id = active["id"]
                action = "stopped"
            else:
                entry_id = conn.execute(
                    "INSERT INTO entries(description, project, tags, start_time, created_at, updated_at) VALUES (?, ?, '', ?, ?, ?)",
                    (description.strip(), proj, now_str, now_str, now_str),
                ).lastrowid
                action = "started"
            conn.commit()
            entry = self._row_to_entry(conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone())
        return action, entry

    def add_manual_entry(
        self,
        description: str,
        duration_seconds: int,
        start_dt: Optional[datetime] = None,
        end_dt: Optional[datetime] = None,
        project: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> TimeEntry:
        """Add an already completed time entry."""
        if duration_seconds < 0:
            raise ValueError("Duration must be non-negative")
        if start_dt:
            start_dt = start_dt.astimezone()
        if end_dt:
            end_dt = end_dt.astimezone()
        if end_dt and not start_dt:
            start_time = datetime.fromtimestamp(end_dt.timestamp() - duration_seconds, tz=end_dt.tzinfo)
            stop_time = end_dt
        elif start_dt and not end_dt:
            start_time = start_dt
            stop_time = datetime.fromtimestamp(start_dt.timestamp() + duration_seconds, tz=start_dt.tzinfo)
        elif start_dt and end_dt:
            start_time = start_dt
            stop_time = end_dt
            duration_seconds = max(0, int((stop_time - start_time).total_seconds()))
        else:
            stop_time = datetime.now().astimezone()
            start_time = datetime.fromtimestamp(stop_time.timestamp() - duration_seconds, tz=stop_time.tzinfo)

        start_time = start_time.astimezone()
        stop_time = stop_time.astimezone()

        now_str = datetime.now().astimezone().isoformat()
        proj = project or self.get_setting("default_project", "default")
        tags_str = ",".join(tags) if tags else ""

        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO entries (description, project, tags, start_time, end_time, duration_seconds, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    description.strip(),
                    proj,
                    tags_str,
                    start_time.isoformat(),
                    stop_time.isoformat(),
                    duration_seconds,
                    now_str,
                    now_str,
                ),
            )
            conn.commit()
            return self.get_entry(cur.lastrowid)

    def get_entry(self, entry_id: int) -> Optional[TimeEntry]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
            row = cur.fetchone()
            return self._row_to_entry(row) if row else None

    def update_entry(
        self,
        entry_id: int,
        description: Optional[str] = None,
        project: Optional[str] = None,
        tags: Optional[List[str]] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> Optional[TimeEntry]:
        entry = self.get_entry(entry_id)
        if not entry:
            return None

        new_desc = description if description is not None else entry.description
        new_proj = project if project is not None else entry.project
        new_tags_str = ",".join(tags) if tags is not None else ",".join(entry.tags)
        new_start = start_time if start_time is not None else entry.start_time
        new_end = end_time if end_time is not None else entry.end_time

        duration = None
        if new_start and new_end:
            s_dt = datetime.fromisoformat(new_start)
            e_dt = datetime.fromisoformat(new_end)
            duration = max(0, int((e_dt - s_dt).total_seconds()))

        now_str = datetime.now().astimezone().isoformat()
        with self.get_connection() as conn:
            conn.execute(
                """
                UPDATE entries
                SET description = ?, project = ?, tags = ?, start_time = ?, end_time = ?, duration_seconds = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_desc.strip(), new_proj, new_tags_str, new_start, new_end, duration, now_str, entry_id),
            )
            conn.commit()
        return self.get_entry(entry_id)

    def delete_entry(self, entry_id: int) -> bool:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _filter_bound(value: Optional[str], end: bool = False) -> Optional[datetime]:
        if not value:
            return None
        if len(value) == 10:
            day = date.fromisoformat(value)
            if end:
                day += timedelta(days=1)
            return datetime.combine(day, time.min).astimezone()
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone()

    def _includes_today(self, since: Optional[str], until: Optional[str], now: datetime) -> bool:
        day_start = datetime.combine(now.date(), time.min).astimezone()
        day_end = datetime.combine(now.date() + timedelta(days=1), time.min).astimezone()
        lower = self._filter_bound(since)
        upper = self._filter_bound(until, end=True)
        return (lower is None or lower < day_end) and (upper is None or upper > day_start)

    def _stats_entries(
        self,
        limit_entries: Optional[int] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        project: Optional[str] = None,
    ) -> List[TimeEntry]:
        """Split sessions at local midnights, clipping to the requested period."""
        lower = self._filter_bound(since)
        upper = self._filter_bound(until, end=True)
        now = datetime.now().astimezone()
        portions: List[TimeEntry] = []
        for entry in self.list_entries(limit=limit_entries, project=project):
            start = datetime.fromisoformat(entry.start_time).astimezone()
            end = datetime.fromisoformat(entry.end_time).astimezone() if entry.end_time else now
            if end < start:
                end = start
            if lower and end <= lower:
                continue
            if upper and start >= upper:
                continue
            start = max(start, lower) if lower else start
            end = min(end, upper) if upper else end

            if start == end:
                boundaries = [(start, end)]
            else:
                boundaries = []
                cursor = start
                while cursor < end:
                    next_day = datetime.combine(cursor.date() + timedelta(days=1), time.min).astimezone()
                    segment_end = min(end, next_day)
                    boundaries.append((cursor, segment_end))
                    cursor = segment_end

            total_seconds = max(0, int((end.timestamp() - start.timestamp())))
            assigned = 0
            for index, (segment_start, segment_end) in enumerate(boundaries):
                last = index == len(boundaries) - 1
                seconds = total_seconds - assigned if last else max(0, int((segment_end.timestamp() - segment_start.timestamp())))
                assigned += seconds
                still_active = entry.is_active and last and segment_end == now
                portions.append(TimeEntry(
                    id=entry.id,
                    description=entry.description,
                    project=entry.project,
                    tags=entry.tags,
                    start_time=segment_start.isoformat(),
                    end_time=None if still_active else segment_end.isoformat(),
                    duration_seconds=None if still_active else seconds,
                    created_at=entry.created_at,
                    updated_at=entry.updated_at,
                ))
        return portions

    def list_entries(
        self,
        limit: Optional[int] = 50,
        offset: int = 0,
        since: Optional[str] = None,
        until: Optional[str] = None,
        project: Optional[str] = None,
    ) -> List[TimeEntry]:
        query = "SELECT * FROM entries WHERE 1=1"
        params: List[Any] = []
        if project:
            query += " AND project = ?"
            params.append(project)

        # ISO strings with different UTC offsets do not sort chronologically.
        # Filter and sort parsed instants when a date window is requested.
        if since or until:
            lower = self._filter_bound(since)
            upper = self._filter_bound(until, end=True)
            upper_inclusive = bool(until and len(until) != 10)
            with self.get_connection() as conn:
                rows = conn.execute(query, params).fetchall()
            entries = [self._row_to_entry(row) for row in rows]
            def started_at(entry: TimeEntry) -> datetime:
                return datetime.fromisoformat(entry.start_time).astimezone()
            entries = [
                entry for entry in entries
                if (lower is None or started_at(entry) >= lower)
                and (upper is None or (started_at(entry) <= upper if upper_inclusive else started_at(entry) < upper))
            ]
            entries.sort(key=started_at, reverse=True)
            return entries[offset:offset + limit] if limit is not None else entries[offset:]

        query += " ORDER BY julianday(start_time) DESC, id DESC"
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        elif offset:
            query += " LIMIT -1 OFFSET ?"
            params.append(offset)

        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            return [self._row_to_entry(row) for row in cur.fetchall()]

    def get_stats_for_today(self, entries_override: Optional[List[TimeEntry]] = None) -> Dict[str, Any]:
        """Compute total seconds and entry count for today."""
        today_prefix = datetime.now().astimezone().strftime("%Y-%m-%d")
        if entries_override is None:
            entries = self._stats_entries(since=today_prefix, until=today_prefix)
        else:
            entries = [e for e in entries_override if e.start_time[:10] == today_prefix]
        total_sec = sum(e.calculate_duration() for e in entries)
        return {
            "total_seconds": total_sec,
            "count": len({e.id for e in entries}),
            "date": today_prefix,
        }

    def get_last_description(self) -> Optional[str]:
        """Return the description of the most recent entry."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT description FROM entries
                WHERE trim(description) != ''
                ORDER BY julianday(start_time) DESC, id DESC LIMIT 1
            """)
            row = cur.fetchone()
            return row["description"] if row else None

    def get_recent_descriptions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return unique descriptions ordered by most recent use, with usage count."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                WITH ranked AS (
                    SELECT description, start_time,
                           COUNT(*) OVER (PARTITION BY description) AS count,
                           ROW_NUMBER() OVER (
                               PARTITION BY description
                               ORDER BY julianday(start_time) DESC, id DESC
                           ) AS recent_rank
                    FROM entries
                    WHERE trim(description) != ''
                )
                SELECT description, start_time AS last_used, count
                FROM ranked
                WHERE recent_rank = 1
                ORDER BY julianday(start_time) DESC
                LIMIT ?
            """, (limit,))
            rows = cur.fetchall()
            return [
                {
                    "description": r["description"],
                    "count": r["count"],
                    "last_used": r["last_used"],
                }
                for r in rows
            ]

    def get_daily_stats(
        self,
        days_limit: int = 30,
        limit_entries: Optional[int] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        project: Optional[str] = None,
        include_today: bool = True,
        entries_override: Optional[List[TimeEntry]] = None,
    ) -> List[Dict[str, Any]]:
        """Return aggregated statistics grouped by day (YYYY-MM-DD), ordered newest first."""
        from datetime import timedelta

        entries = entries_override if entries_override is not None else self._stats_entries(
            limit_entries=limit_entries,
            since=since,
            until=until,
            project=project,
        )

        now_local = datetime.now().astimezone()
        today_date = now_local.date()
        today_str = today_date.strftime("%Y-%m-%d")
        yesterday_str = (today_date - timedelta(days=1)).strftime("%Y-%m-%d")

        # Group entries by local date
        grouped: Dict[str, List[TimeEntry]] = {}
        for entry in entries:
            try:
                s_dt = datetime.fromisoformat(entry.start_time)
                if s_dt.tzinfo is not None:
                    day_key = s_dt.astimezone().strftime("%Y-%m-%d")
                else:
                    day_key = s_dt.strftime("%Y-%m-%d")
            except Exception:
                day_key = entry.start_time[:10] if entry.start_time else today_str

            grouped.setdefault(day_key, []).append(entry)

        # Optionally include today if no entries exist for today and not filtering by past until
        if include_today and today_str not in grouped:
            if self._includes_today(since, until, now_local):
                grouped[today_str] = []

        # Sort dates descending (newest first)
        sorted_dates = sorted(grouped.keys(), reverse=True)
        if days_limit is not None and days_limit > 0:
            sorted_dates = sorted_dates[:days_limit]

        result: List[Dict[str, Any]] = []
        for d_str in sorted_dates:
            day_entries = grouped[d_str]
            total_sec = sum(e.calculate_duration() for e in day_entries)
            has_active = any(e.is_active for e in day_entries)

            try:
                d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
                day_name = d_obj.strftime("%A")
                day_abbr = d_obj.strftime("%a")
            except Exception:
                day_name = ""
                day_abbr = ""

            # Group by task description
            task_groups: Dict[str, Dict[str, Any]] = {}
            for e in day_entries:
                desc = e.description.strip() or "Untitled"
                dur = e.calculate_duration()
                if desc not in task_groups:
                    task_groups[desc] = {"description": desc, "total_seconds": 0, "count": 0}
                task_groups[desc]["total_seconds"] += dur
                task_groups[desc]["count"] += 1

            tasks_list = list(task_groups.values())
            for t in tasks_list:
                t["percentage"] = round((t["total_seconds"] / total_sec * 100), 1) if total_sec > 0 else 0.0
            tasks_list.sort(key=lambda x: (x["total_seconds"], x["count"]), reverse=True)

            # Group by project
            proj_groups: Dict[str, Dict[str, Any]] = {}
            for e in day_entries:
                proj = e.project.strip() or "default"
                dur = e.calculate_duration()
                if proj not in proj_groups:
                    proj_groups[proj] = {"project": proj, "total_seconds": 0, "count": 0}
                proj_groups[proj]["total_seconds"] += dur
                proj_groups[proj]["count"] += 1

            proj_list = list(proj_groups.values())
            for p in proj_list:
                p["percentage"] = round((p["total_seconds"] / total_sec * 100), 1) if total_sec > 0 else 0.0
            proj_list.sort(key=lambda x: (x["total_seconds"], x["count"]), reverse=True)

            result.append({
                "date": d_str,
                "day_name": day_name,
                "day_abbr": day_abbr,
                "is_today": (d_str == today_str),
                "is_yesterday": (d_str == yesterday_str),
                "total_seconds": total_sec,
                "count": len(day_entries),
                "has_active": has_active,
                "tasks": tasks_list,
                "projects": proj_list,
                "entries": day_entries,
            })

        return result

    def get_weekly_stats(
        self,
        weeks_limit: int = 26,
        limit_entries: Optional[int] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        project: Optional[str] = None,
        include_current_week: bool = True,
        entries_override: Optional[List[TimeEntry]] = None,
    ) -> List[Dict[str, Any]]:
        """Return aggregated statistics grouped by ISO week (YYYY-Www), ordered newest first."""
        from datetime import timedelta

        entries = entries_override if entries_override is not None else self._stats_entries(
            limit_entries=limit_entries,
            since=since,
            until=until,
            project=project,
        )

        now_local = datetime.now().astimezone()
        today_date = now_local.date()
        cur_iso_year, cur_iso_week, _ = today_date.isocalendar()
        cur_week_str = f"{cur_iso_year}-W{cur_iso_week:02d}"

        last_week_dt = today_date - timedelta(days=7)
        last_iso_year, last_iso_week, _ = last_week_dt.isocalendar()
        last_week_str = f"{last_iso_year}-W{last_iso_week:02d}"

        # Group entries by ISO week
        grouped: Dict[str, List[TimeEntry]] = {}
        for entry in entries:
            try:
                s_dt = datetime.fromisoformat(entry.start_time)
                if s_dt.tzinfo is not None:
                    local_dt = s_dt.astimezone()
                else:
                    local_dt = s_dt
                e_date = local_dt.date()
            except Exception:
                try:
                    e_date = datetime.strptime(entry.start_time[:10], "%Y-%m-%d").date()
                except Exception:
                    e_date = today_date

            iso_y, iso_w, _ = e_date.isocalendar()
            week_key = f"{iso_y}-W{iso_w:02d}"
            grouped.setdefault(week_key, []).append(entry)

        # Include current week if needed
        if include_current_week and cur_week_str not in grouped:
            if self._includes_today(since, until, now_local):
                grouped[cur_week_str] = []

        # Sort weeks descending (newest first)
        sorted_weeks = sorted(grouped.keys(), reverse=True)
        if weeks_limit is not None and weeks_limit > 0:
            sorted_weeks = sorted_weeks[:weeks_limit]

        result: List[Dict[str, Any]] = []
        for w_str in sorted_weeks:
            week_entries = grouped[w_str]
            total_sec = sum(e.calculate_duration() for e in week_entries)
            has_active = any(e.is_active for e in week_entries)

            try:
                parts = w_str.split("-W")
                w_year = int(parts[0])
                w_num = int(parts[1])
                start_d = datetime.fromisocalendar(w_year, w_num, 1).date()
                end_d = datetime.fromisocalendar(w_year, w_num, 7).date()
                start_date_str = start_d.strftime("%Y-%m-%d")
                end_date_str = end_d.strftime("%Y-%m-%d")
                if start_d.year == end_d.year:
                    range_fmt = f"{start_d.strftime('%d.%m')} - {end_d.strftime('%d.%m.%Y')}"
                else:
                    range_fmt = f"{start_d.strftime('%d.%m.%Y')} - {end_d.strftime('%d.%m.%Y')}"
            except Exception:
                start_date_str = ""
                end_date_str = ""
                range_fmt = w_str

            # Task groups
            task_groups: Dict[str, Dict[str, Any]] = {}
            for e in week_entries:
                desc = e.description.strip() or "Untitled"
                dur = e.calculate_duration()
                if desc not in task_groups:
                    task_groups[desc] = {"description": desc, "total_seconds": 0, "count": 0}
                task_groups[desc]["total_seconds"] += dur
                task_groups[desc]["count"] += 1

            tasks_list = list(task_groups.values())
            for t in tasks_list:
                t["percentage"] = round((t["total_seconds"] / total_sec * 100), 1) if total_sec > 0 else 0.0
            tasks_list.sort(key=lambda x: (x["total_seconds"], x["count"]), reverse=True)

            # Project groups
            proj_groups: Dict[str, Dict[str, Any]] = {}
            for e in week_entries:
                proj = e.project.strip() or "default"
                dur = e.calculate_duration()
                if proj not in proj_groups:
                    proj_groups[proj] = {"project": proj, "total_seconds": 0, "count": 0}
                proj_groups[proj]["total_seconds"] += dur
                proj_groups[proj]["count"] += 1

            proj_list = list(proj_groups.values())
            for p in proj_list:
                p["percentage"] = round((p["total_seconds"] / total_sec * 100), 1) if total_sec > 0 else 0.0
            proj_list.sort(key=lambda x: (x["total_seconds"], x["count"]), reverse=True)

            # Daily breakdown within the week
            day_groups: Dict[str, Dict[str, Any]] = {}
            for e in week_entries:
                try:
                    s_dt = datetime.fromisoformat(e.start_time)
                    if s_dt.tzinfo is not None:
                        d_str = s_dt.astimezone().strftime("%Y-%m-%d")
                    else:
                        d_str = s_dt.strftime("%Y-%m-%d")
                except Exception:
                    d_str = e.start_time[:10] if e.start_time else ""
                if not d_str:
                    continue
                if d_str not in day_groups:
                    try:
                        d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
                        d_name = d_obj.strftime("%A")
                        d_abbr = d_obj.strftime("%a")
                    except Exception:
                        d_name = ""
                        d_abbr = ""
                    day_groups[d_str] = {
                        "date": d_str,
                        "day_name": d_name,
                        "day_abbr": d_abbr,
                        "total_seconds": 0,
                        "count": 0,
                    }
                day_groups[d_str]["total_seconds"] += e.calculate_duration()
                day_groups[d_str]["count"] += 1

            days_breakdown = sorted(day_groups.values(), key=lambda x: x["date"])
            for d_item in days_breakdown:
                d_item["percentage"] = round((d_item["total_seconds"] / total_sec * 100), 1) if total_sec > 0 else 0.0

            result.append({
                "week": w_str,
                "start_date": start_date_str,
                "end_date": end_date_str,
                "range_formatted": range_fmt,
                "is_current_week": (w_str == cur_week_str),
                "is_last_week": (w_str == last_week_str),
                "total_seconds": total_sec,
                "count": len(week_entries),
                "has_active": has_active,
                "active_days_count": len(day_groups),
                "tasks": tasks_list,
                "projects": proj_list,
                "days_breakdown": days_breakdown,
                "entries": week_entries,
            })

        return result

    def get_monthly_stats(
        self,
        months_limit: int = 12,
        limit_entries: Optional[int] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        project: Optional[str] = None,
        include_current_month: bool = True,
        entries_override: Optional[List[TimeEntry]] = None,
    ) -> List[Dict[str, Any]]:
        """Return aggregated statistics grouped by month (YYYY-MM), ordered newest first."""
        import calendar
        from datetime import timedelta, date

        entries = entries_override if entries_override is not None else self._stats_entries(
            limit_entries=limit_entries,
            since=since,
            until=until,
            project=project,
        )

        now_local = datetime.now().astimezone()
        today_date = now_local.date()
        cur_month_str = today_date.strftime("%Y-%m")

        last_month_dt = today_date.replace(day=1) - timedelta(days=1)
        last_month_str = last_month_dt.strftime("%Y-%m")

        # Group entries by month (YYYY-MM)
        grouped: Dict[str, List[TimeEntry]] = {}
        for entry in entries:
            try:
                s_dt = datetime.fromisoformat(entry.start_time)
                if s_dt.tzinfo is not None:
                    local_dt = s_dt.astimezone()
                else:
                    local_dt = s_dt
                m_key = local_dt.date().strftime("%Y-%m")
            except Exception:
                m_key = entry.start_time[:7] if entry.start_time else cur_month_str

            grouped.setdefault(m_key, []).append(entry)

        # Include current month if needed
        if include_current_month and cur_month_str not in grouped:
            if self._includes_today(since, until, now_local):
                grouped[cur_month_str] = []

        # Sort months descending (newest first)
        sorted_months = sorted(grouped.keys(), reverse=True)
        if months_limit is not None and months_limit > 0:
            sorted_months = sorted_months[:months_limit]

        result: List[Dict[str, Any]] = []
        for m_str in sorted_months:
            month_entries = grouped[m_str]
            total_sec = sum(e.calculate_duration() for e in month_entries)
            has_active = any(e.is_active for e in month_entries)

            try:
                parts = m_str.split("-")
                m_year = int(parts[0])
                m_num = int(parts[1])
                first_d = date(m_year, m_num, 1)
                last_day_num = calendar.monthrange(m_year, m_num)[1]
                last_d = date(m_year, m_num, last_day_num)
                month_name = first_d.strftime("%B %Y")
                month_abbr = first_d.strftime("%b %Y")
                start_date_str = first_d.strftime("%Y-%m-%d")
                end_date_str = last_d.strftime("%Y-%m-%d")
                range_fmt = f"01.{m_num:02d} - {last_day_num:02d}.{m_num:02d}.{m_year}"
            except Exception:
                month_name = m_str
                month_abbr = m_str
                start_date_str = ""
                end_date_str = ""
                range_fmt = m_str

            # Task groups
            task_groups: Dict[str, Dict[str, Any]] = {}
            distinct_days = set()
            for e in month_entries:
                desc = e.description.strip() or "Untitled"
                dur = e.calculate_duration()
                if desc not in task_groups:
                    task_groups[desc] = {"description": desc, "total_seconds": 0, "count": 0}
                task_groups[desc]["total_seconds"] += dur
                task_groups[desc]["count"] += 1

                try:
                    s_dt = datetime.fromisoformat(e.start_time)
                    if s_dt.tzinfo is not None:
                        distinct_days.add(s_dt.astimezone().strftime("%Y-%m-%d"))
                    else:
                        distinct_days.add(s_dt.strftime("%Y-%m-%d"))
                except Exception:
                    if e.start_time:
                        distinct_days.add(e.start_time[:10])

            tasks_list = list(task_groups.values())
            for t in tasks_list:
                t["percentage"] = round((t["total_seconds"] / total_sec * 100), 1) if total_sec > 0 else 0.0
            tasks_list.sort(key=lambda x: (x["total_seconds"], x["count"]), reverse=True)

            # Project groups
            proj_groups: Dict[str, Dict[str, Any]] = {}
            for e in month_entries:
                proj = e.project.strip() or "default"
                dur = e.calculate_duration()
                if proj not in proj_groups:
                    proj_groups[proj] = {"project": proj, "total_seconds": 0, "count": 0}
                proj_groups[proj]["total_seconds"] += dur
                proj_groups[proj]["count"] += 1

            proj_list = list(proj_groups.values())
            for p in proj_list:
                p["percentage"] = round((p["total_seconds"] / total_sec * 100), 1) if total_sec > 0 else 0.0
            proj_list.sort(key=lambda x: (x["total_seconds"], x["count"]), reverse=True)

            # Weekly breakdown within the month
            week_groups: Dict[str, Dict[str, Any]] = {}
            for e in month_entries:
                try:
                    s_dt = datetime.fromisoformat(e.start_time)
                    if s_dt.tzinfo is not None:
                        e_dt = s_dt.astimezone().date()
                    else:
                        e_dt = s_dt.date()
                except Exception:
                    try:
                        e_dt = datetime.strptime(e.start_time[:10], "%Y-%m-%d").date()
                    except Exception:
                        e_dt = today_date
                iso_y, iso_w, _ = e_dt.isocalendar()
                w_key = f"{iso_y}-W{iso_w:02d}"

                if w_key not in week_groups:
                    try:
                        w_start = datetime.fromisocalendar(iso_y, iso_w, 1).date()
                        w_end = datetime.fromisocalendar(iso_y, iso_w, 7).date()
                        w_range = f"{w_start.strftime('%d.%m')} - {w_end.strftime('%d.%m')}"
                    except Exception:
                        w_range = w_key
                    week_groups[w_key] = {
                        "week": w_key,
                        "range_formatted": w_range,
                        "total_seconds": 0,
                        "count": 0,
                    }
                week_groups[w_key]["total_seconds"] += e.calculate_duration()
                week_groups[w_key]["count"] += 1

            weeks_breakdown = sorted(week_groups.values(), key=lambda x: x["week"], reverse=True)
            for w_item in weeks_breakdown:
                w_item["percentage"] = round((w_item["total_seconds"] / total_sec * 100), 1) if total_sec > 0 else 0.0

            result.append({
                "month": m_str,
                "month_name": month_name,
                "month_abbr": month_abbr,
                "start_date": start_date_str,
                "end_date": end_date_str,
                "range_formatted": range_fmt,
                "is_current_month": (m_str == cur_month_str),
                "is_last_month": (m_str == last_month_str),
                "total_seconds": total_sec,
                "count": len(month_entries),
                "has_active": has_active,
                "active_days_count": len(distinct_days),
                "tasks": tasks_list,
                "projects": proj_list,
                "weeks_breakdown": weeks_breakdown,
                "entries": month_entries,
            })

        return result
