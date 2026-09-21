"""Tests for export functionalities (JSON, JSONL, CSV)."""

import unittest
import tempfile
import json
import csv
from pathlib import Path
from datetime import datetime

from vlogger.db import Database
from vlogger.export import export_entries, export_to_file


class TestExport(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_export.db"
        self.db = Database(self.db_path)

        # Seed sample entries
        t1 = datetime(2026, 9, 21, 9, 0, 0)
        t2 = datetime(2026, 9, 21, 11, 0, 0)
        self.db.add_manual_entry(
            description="Feature A",
            duration_seconds=3600,
            start_dt=t1,
            project="backend",
            tags=["api", "auth"],
        )
        self.db.add_manual_entry(
            description="Feature B",
            duration_seconds=1800,
            start_dt=t2,
            project="frontend",
            tags=["ui"],
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_export_json(self):
        json_out = export_entries(self.db, fmt="json")
        data = json.loads(json_out)
        self.assertEqual(len(data), 2)
        self.assertIn("duration_formatted", data[0])
        self.assertIn("start_time", data[0])
        self.assertIn("end_time", data[0])
        self.assertIn("project", data[0])

    def test_export_jsonl(self):
        jsonl_out = export_entries(self.db, fmt="jsonl")
        lines = [line for line in jsonl_out.strip().split("\n") if line]
        self.assertEqual(len(lines), 2)
        item = json.loads(lines[0])
        self.assertIn("description", item)

    def test_export_csv(self):
        csv_out = export_entries(self.db, fmt="csv")
        reader = csv.DictReader(csv_out.splitlines())
        rows = list(reader)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["project"], "frontend")  # ordered DESC by start_time
        self.assertEqual(rows[1]["project"], "backend")
        self.assertEqual(rows[1]["duration_seconds"], "3600")

    def test_export_to_file(self):
        out_file = Path(self.temp_dir.name) / "exported_logs.csv"
        count = export_to_file(self.db, file_path=out_file)
        self.assertEqual(count, 2)
        self.assertTrue(out_file.exists())
        self.assertGreater(out_file.stat().st_size, 50)


if __name__ == "__main__":
    unittest.main()
