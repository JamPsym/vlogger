"""Export utilities for vlogger (JSON, JSONL, CSV).

Designed so that logs can be easily piped or imported into larger systems,
databases (PostgreSQL, ClickHouse), spreadsheets, or analytics pipelines.
"""

import csv
import io
import json
from typing import List, Optional
from pathlib import Path

from vlogger.models import TimeEntry
from vlogger.db import Database


def export_entries(
    db: Database,
    fmt: str = "json",
    since: Optional[str] = None,
    until: Optional[str] = None,
    project: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Export entries matching filters in the given format ('json', 'jsonl', 'csv')."""
    fmt_lower = fmt.lower().strip()
    if fmt_lower == "html":
        from vlogger.html_report import generate_html_report
        return generate_html_report(db, since=since, until=until, project=project)

    entries = db.list_entries(limit=limit, since=since, until=until, project=project)
    if fmt_lower == "json":
        data = [e.to_dict() for e in entries]
        return json.dumps(data, indent=2, ensure_ascii=False)
    elif fmt_lower == "jsonl":
        lines = [json.dumps(e.to_dict(), ensure_ascii=False) for e in entries]
        return "\n".join(lines) + ("\n" if lines else "")
    elif fmt_lower == "csv":
        output = io.StringIO()
        fieldnames = [
            "id",
            "description",
            "project",
            "tags",
            "start_time",
            "end_time",
            "duration_seconds",
            "duration_formatted",
            "created_at",
            "updated_at",
            "is_active",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for e in entries:
            d = e.to_dict()
            d["tags"] = ",".join(d["tags"])
            writer.writerow(d)
        return output.getvalue()
    else:
        raise ValueError(f"Unsupported export format: {fmt}. Choose 'json', 'jsonl', 'csv', or 'html'.")


def export_to_file(
    db: Database,
    file_path: Path,
    fmt: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    project: Optional[str] = None,
) -> int:
    """Export entries to a file path. Format inferred from extension if not provided."""
    target_path = Path(file_path).expanduser().resolve()
    if not fmt:
        ext = target_path.suffix.lstrip(".").lower()
        fmt = ext if ext in ("json", "jsonl", "csv", "html") else "json"

    content = export_entries(db, fmt=fmt, since=since, until=until, project=project)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    
    # Return count of exported lines / entries
    if fmt.lower() == "html":
        return len({e.id for e in db._stats_entries(since=since, until=until, project=project)})
    return len(db.list_entries(limit=None, since=since, until=until, project=project))
