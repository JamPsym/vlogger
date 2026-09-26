"""Detached automatic report sync worker."""

import fcntl
import sys
from pathlib import Path

from vlogger.core import VLoggerCore
from vlogger.db import Database


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    db = Database(Path(sys.argv[1]))
    target = Path(sys.argv[2])
    core = VLoggerCore(db)
    # Serialize uploads so a slow older sync cannot overwrite a newer report.
    with (db.db_path.parent / "sync.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ok, _ = core.sync_html_report(target, wait=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
