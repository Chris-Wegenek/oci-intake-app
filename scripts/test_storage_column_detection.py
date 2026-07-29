#!/usr/bin/env python3
"""Which column an inventory's storage capacity is read from.

Inventories name this column every possible way. Two failure modes matter and pull in opposite
directions: too strict and a plainly-named "Storage" column prices at zero GB (a real customer
sheet with "384 GB" / "1 TB" in the cells did exactly that); too loose and a text column like
"Storage Type" or an identifier like "SMBios UUID" gets billed as capacity.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app

NEEDLES = [["local storage"], ["total storage"], ["allocated storage"], ["storage", "gb"],
           ["disk", "gb"], ["disk", "size"], ["disk", "capacity"], ["provisioned", "storage"],
           ["provisioned", "disk"], ["storage"], ["disk"]]


def fields(*headers):
    return [{"key": h.lower().replace(" ", "_").replace("(", "").replace(")", ""),
             "label": h, "sourceHeader": h, "group": None} for h in headers]


class StorageColumnDetectionTests(unittest.TestCase):
    def test_picks_the_capacity_column_and_only_the_capacity_column(self):
        cases = [
            # a bare header with the unit in the cells, not the header
            ("Server Name", "CPUs", "RAM", "Storage"),
            ("Server Name", "Disk"),
            # a kind/tier column must never be mistaken for an amount...
            ("Server Name", "Storage Type"),
            ("Server Name", "Storage Tier"),
            ("Server Name", "Disk Type"),
            # ...and must not shadow the real column when both are present, in either order
            ("Server Name", "Storage Type", "Storage"),
            ("Server Name", "Storage", "Storage Type"),
            # a more specific header still wins over the bare fallback
            ("Server Name", "Storage", "Total Storage (GB)"),
            # identifiers are not capacity
            ("Server Name", "SMBios UUID"),
            ("Server Name", "CPUs", "RAM"),
        ]
        expected = ["storage", "disk", None, None, None, "storage", "storage",
                    "total_storage_gb", None, None]
        for headers, want in zip(cases, expected):
            with self.subTest(headers):
                self.assertEqual(app.find_storage_key_any(fields(*headers), NEEDLES), want)

    def test_ram_is_never_read_as_storage(self):
        """RAM is measured in GB too, so a capacity needle must stay anchored to a storage word."""
        for headers in (("Server Name", "Memory (GB)"), ("Server Name", "RAM Capacity (GB)"),
                        ("Server Name", "RAM")):
            with self.subTest(headers):
                self.assertIsNone(app.find_storage_key_any(fields(*headers), NEEDLES))


class OperatingSystemOverrideTests(unittest.TestCase):
    def test_review_override_beats_detection(self):
        """Detection reads any cell for 'windows'/'linux'; the reviewer's choice must win."""
        row = {"server": "APP01", "os": "windows", "notes": "windows shop"}
        self.assertEqual(app.row_operating_system(row), "windows")
        row["__os"] = "linux"
        self.assertEqual(app.row_operating_system(row), "linux")
        row["__os"] = "windows"
        self.assertEqual(app.row_operating_system(row), "windows")

    def test_a_junk_override_falls_back_to_detection(self):
        row = {"server": "APP01", "os": "linux", "__os": "  "}
        self.assertEqual(app.row_operating_system(row), "linux")

    def test_a_stray_mention_is_what_the_override_exists_to_correct(self):
        row = {"server": "DB01", "os": "linux", "comments": "migrating off Windows in Q3"}
        self.assertEqual(app.row_operating_system(row), "windows")   # detection is fooled
        row["__os"] = "linux"
        self.assertEqual(app.row_operating_system(row), "linux")     # the reviewer fixes it


if __name__ == "__main__":
    unittest.main(verbosity=2)
