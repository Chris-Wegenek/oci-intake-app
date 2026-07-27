#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


class MixedInventoryUnitTests(unittest.TestCase):
    def parse_frame(self, frame):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "mixed-units.xlsx"
            frame.to_excel(workbook, index=False)
            return app.parse_workbook_rule_based(workbook)

    def test_mixed_virtual_memory_and_storage_units_are_normalized(self):
        rows = []
        for index in range(8):
            rows.append(
                {
                    "Machine ID": f"legacy-vm-{index}",
                    "Application": "Legacy",
                    "Environment": "Prod",
                    "Virtual/ Physical": "Virtual",
                    "Model": "VMware Virtual Platform",
                    "MemoryGB(RAM)": 8192 + (index % 2) * 8192,
                    "CPU Cores": 8,
                    "Total Storage (GB)": 500 + index,
                }
            )
            rows.append(
                {
                    "Machine ID": f"vxrail-vm-{index}",
                    "Application": "VxRail",
                    "Environment": "Prod",
                    "Virtual/ Physical": "Virtual",
                    "Model": "Vxrail",
                    "MemoryGB(RAM)": 16 + index,
                    "CPU Cores": 8,
                    "Total Storage (GB)": 102400 + index * 1024,
                }
            )
        rows.append(
            {
                "Machine ID": "physical-db",
                "Application": "Database",
                "Environment": "Prod",
                "Virtual/ Physical": "Physical",
                "Model": "PowerEdge",
                "MemoryGB(RAM)": 4096,
                "CPU Cores": 32,
                "Total Storage (GB)": 100000,
            }
        )

        parsed = self.parse_frame(pd.DataFrame(rows))
        by_name = {row["machine_id"]: row for row in parsed["rows"]}

        self.assertEqual(by_name["legacy-vm-0"]["memorygb_ram"], 8)
        self.assertEqual(by_name["legacy-vm-0"]["total_storage_gb"], 500)
        self.assertEqual(by_name["vxrail-vm-0"]["memorygb_ram"], 16)
        self.assertEqual(by_name["vxrail-vm-0"]["total_storage_gb"], 100)
        self.assertEqual(by_name["physical-db"]["memorygb_ram"], 4096)
        self.assertEqual(by_name["physical-db"]["total_storage_gb"], 100000)

        normalizations = parsed["metadata"]["unitNormalizations"]
        self.assertEqual(
            {(item["kind"], item["rowCount"]) for item in normalizations},
            {("memory", 8), ("storage", 8)},
        )


if __name__ == "__main__":
    unittest.main()
