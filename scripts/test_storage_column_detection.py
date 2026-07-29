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


class CapacityUnitTests(unittest.TestCase):
    """A misread unit is silent and enormous - 1.5 TiB read as 1.5 GB is off by 1000x."""

    def test_units_in_the_cell(self):
        cases = {
            "900": 900, "384 GB": 384, "250GB": 250, "1,024 GB": 1024,
            "1 TB": 1024, "1TB": 1024, "2 tb": 2048, "0.5 TB": 512,
            "12.125 TB": 12416, "3 TBs": 3072, "10 terabytes": 10240,
            "1.5 TiB": 1536, "64 GiB": 64, "2048 MiB": 2,
            "500 MB": 500 / 1024, "2 PB": 2 * 1024 ** 2, "1 EB": 1024 ** 3,
        }
        for text, want in cases.items():
            with self.subTest(text):
                self.assertAlmostEqual(app.to_gb(text), want, places=4)

    def test_units_in_the_header(self):
        """RVTools-style exports leave the cells bare and put the unit in the header."""
        cases = {
            "Storage": 1, "Storage (GB)": 1, "Disk GiB": 1, "Total Storage": 1,
            "Storage (TB)": 1024, "Disk TB": 1024, "Storage in TB": 1024,
            "Memory (MB)": 1 / 1024, "Provisioned MiB": 1 / 1024,
            "Capacity (PB)": 1024 ** 2,
        }
        for header, want in cases.items():
            with self.subTest(header):
                self.assertAlmostEqual(app.header_unit_factor_to_gb(header), want, places=9)

    def test_a_unit_word_inside_another_word_is_not_a_unit(self):
        for text in ("Web Server", "Prebuilt", "Description", "Number of Disks"):
            with self.subTest(text):
                self.assertIsNone(app.capacity_unit_factor(text))


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
