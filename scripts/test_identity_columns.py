#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


class IdentityColumnTests(unittest.TestCase):
    def parse_rows(self, frame):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "identity.xlsx"
            frame.to_excel(workbook, index=False)
            plan = {
                "sheetName": "Sheet1",
                "headerRows": [1],
                "dataStartRow": 2,
                "dataEndRow": None,
                "serverGrain": "server",
                "confidence": 1,
                "columnMappings": {},
                "notes": [],
            }
            return app.parse_workbook_from_plan(workbook, plan)

    def test_application_and_machine_names_map_separately(self):
        payload = self.parse_rows(
            pd.DataFrame(
                [
                    {
                        "Application Name": "Order Management",
                        "Machine Name": "ord-prod-01",
                        "Environment": "Prod",
                        "CPU": 8,
                        "RAM (GB)": 32,
                    }
                ]
            )
        )

        self.assertEqual(payload["rows"][0]["application_name"], "Order Management")
        self.assertEqual(payload["rows"][0]["machine_name"], "ord-prod-01")

    def test_machine_only_inventory_keeps_the_row(self):
        payload = self.parse_rows(
            pd.DataFrame(
                [
                    {
                        "Server Name": "db-prod-01",
                        "Environment": "Prod",
                        "CPU": 4,
                        "RAM (GB)": 16,
                    }
                ]
            )
        )

        self.assertEqual(payload["rows"][0]["application_name"], "")
        self.assertEqual(payload["rows"][0]["machine_name"], "db-prod-01")

    def test_machine_id_maps_to_machine_name(self):
        payload = self.parse_rows(
            pd.DataFrame(
                [
                    {
                        "Machine ID": "app-prod-01",
                        "Application": "Order Management",
                        "Environment": "Prod",
                        "CPU": 4,
                        "RAM (GB)": 16,
                    }
                ]
            )
        )

        self.assertEqual(payload["rows"][0]["application_name"], "Order Management")
        self.assertEqual(payload["rows"][0]["machine_name"], "app-prod-01")
        data_check = app.inventory_data_check(payload["fields"], payload["rows"])
        server_signal = next(
            signal
            for signal in data_check["signals"]
            if signal["key"] == "server"
        )
        self.assertTrue(server_signal["present"])
        self.assertEqual(server_signal["column"], "Machine ID")


if __name__ == "__main__":
    unittest.main()
