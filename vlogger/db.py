"""SQLite Database layer with WAL mode and robust schema for vlogger."""

import os
import sqlite3
from pathlib import Path
from datetime import datetime
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
            conn.commit()

    def get_active_entry(self) -> Optional[TimeEntry]:
        """Return the currently running active timer, if any."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM entries WHERE end_time IS NULL ORDER BY start_time DESC LIMIT 1"
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
        """Start a new timer entry. If one is already active, stop it first."""
        active = self.get_active_entry()
        if active:
            self.stop_timer(end_dt=start_dt)

        now_str = (start_dt or datetime.now().astimezone()).isoformat()
        proj = project or self.get_setting("default_project", "default")
        tags_str = ",".join(tags) if tags else ""

        with self.get_connection() as conn:
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
            return self.get_entry(entry_id)

    def stop_timer(self, end_dt: Optional[datetime] = None) -> Optional[TimeEntry]:
        """Stop the currently active timer."""
        active = self.get_active_entry()
        if not active:
            return None

        stop_time = end_dt or datetime.now().astimezone()
        stop_time_str = stop_time.isoformat()
        
        # Calculate duration
        start_time = datetime.fromisoformat(active.start_time)
        duration = max(0, int((stop_time - start_time).total_seconds()))

        with self.get_connection() as conn:
            conn.execute(
                """
                UPDATE entries
                SET end_time = ?, duration_seconds = ?, updated_at = ?
                WHERE id = ?
                """,
                (stop_time_str, duration, stop_time_str, active.id),
            )
            conn.commit()
        return self.get_entry(active.id)

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

    def list_entries(
        self,
        limit: int = 50,
        offset: int = 0,
        since: Optional[str] = None,
        until: Optional[str] = None,
        project: Optional[str] = None,
    ) -> List[TimeEntry]:
        query = "SELECT * FROM entries WHERE 1=1"
        params: List[Any] = []

        if since:
            query += " AND start_time >= ?"
            params.append(since)
        if until:
            query += " AND start_time <= ?"
            params.append(until)
        if project:
            query += " AND project = ?"
            params.append(project)

        query += " ORDER BY start_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            return [self._row_to_entry(row) for row in cur.fetchall()]

    def get_stats_for_today(self) -> Dict[str, Any]:
        """Compute total seconds and entry count for today."""
        today_prefix = datetime.now().astimezone().strftime("%Y-%m-%d")
        entries = self.list_entries(limit=500, since=f"{today_prefix}T00:00:00")
        total_sec = sum(e.calculate_duration() for e in entries)
        return {
            "total_seconds": total_sec,
            "count": len(entries),
            "date": today_prefix,
        }

    def get_last_description(self) -> Optional[str]:
        """Return the description of the most recent entry."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT description FROM entries
                WHERE trim(description) != ''
                ORDER BY start_time DESC LIMIT 1
            """)
            row = cur.fetchone()
            return row["description"] if row else None

    def get_recent_descriptions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return unique descriptions ordered by most recent use, with usage count."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT description, MAX(start_time) as last_used, COUNT(*) as count
                FROM entries
                WHERE trim(description) != ''
                GROUP BY description
                ORDER BY MAX(start_time) DESC
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

