#!/usr/bin/env python3

import json
import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


class MockHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(
            {"output_text": json.dumps(self.payload)}
        ).encode("utf-8")


class OpenAIAssistTests(unittest.TestCase):
    def setUp(self):
        self.responses = []
        self.requests = []
        self.original_environment = {
            key: os.environ.get(key)
            for key in (
                "OPENAI_API_KEY",
                "OPENAI_API_BASE",
                "OPENAI_API_ENABLED",
                "OPENAI_MODEL",
                "OPENAI_UPLOAD_MODEL",
                "OPENAI_UPLOAD_REASONING_EFFORT",
                "OPENAI_BILL_MODEL",
                "OPENAI_BILL_REASONING_EFFORT",
                "OPENAI_ARCHITECTURE_MODEL",
                "OPENAI_ARCHITECTURE_REASONING_EFFORT",
            )
        }
        os.environ.update(
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_API_BASE": "https://mock.openai.test/v1",
                "OPENAI_API_ENABLED": "true",
                "OPENAI_MODEL": "gpt-5-mini",
                "OPENAI_UPLOAD_MODEL": "gpt-5-mini",
                "OPENAI_UPLOAD_REASONING_EFFORT": "low",
                "OPENAI_BILL_MODEL": "gpt-5-mini",
                "OPENAI_BILL_REASONING_EFFORT": "low",
                "OPENAI_ARCHITECTURE_MODEL": "gpt-5-mini",
                "OPENAI_ARCHITECTURE_REASONING_EFFORT": "low",
            }
        )
        self.urlopen_patcher = mock.patch.object(
            app.urllib.request,
            "urlopen",
            side_effect=self.fake_urlopen,
        )
        self.urlopen_patcher.start()

    def tearDown(self):
        self.urlopen_patcher.stop()
        for key, value in self.original_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def fake_urlopen(self, request, timeout=None):
        self.requests.append(json.loads(request.data.decode("utf-8")))
        return MockHTTPResponse(self.responses.pop(0))

    def test_inventory_scrub_uses_strict_fixed_schema(self):
        mappings = [
            ("application_name", 1, "Application", "text"),
            ("machine_name", 2, "Machine ID", "text"),
            ("environment", 3, "Environment", "text"),
            (
                "application_details_number_of_cpu_cores_per_server",
                4,
                "vCPU",
                "vCPU",
            ),
            (
                "application_details_memory_per_server_gb",
                5,
                "RAM (MiB)",
                "MiB",
            ),
            (
                "application_details_local_storage_gb",
                6,
                "Storage (GB)",
                "GB",
            ),
        ]
        self.responses.append(
            {
                "sheetName": "Inventory",
                "headerRows": [1],
                "dataStartRow": 2,
                "dataEndRow": None,
                "serverGrain": "server",
                "confidence": 0.98,
                "columnMappings": [
                    {
                        "canonicalKey": key,
                        "sourceColumn": column,
                        "sourceHeader": header,
                        "jsonKey": "",
                        "sourceUnit": unit,
                        "confidence": 0.98,
                        "transform": "",
                    }
                    for key, column, header, unit in mappings
                ],
                "notes": ["Mapped the inventory into the fixed Review schema."],
            }
        )
        frame = pd.DataFrame(
            [
                {
                    "Application": f"Application {index}",
                    "Machine ID": f"server-{index}",
                    "Environment": "Prod" if index % 2 else "Non-Prod",
                    "vCPU": 8,
                    "RAM (MiB)": 8192,
                    "Storage (GB)": 500,
                }
                for index in range(1, 9)
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "inventory.xlsx"
            with pd.ExcelWriter(workbook) as writer:
                frame.to_excel(writer, sheet_name="Inventory", index=False)
            parsed = app.parse_workbook(workbook)

        self.assertEqual(parsed["metadata"]["parser"], "llm-assisted")
        self.assertTrue(parsed["metadata"]["aiAssisted"])
        self.assertEqual(parsed["metadata"]["reviewSchema"], app.FIXED_REVIEW_SCHEMA)
        self.assertEqual(
            parsed["rows"][0]["application_details_number_of_cpu_cores_per_server"],
            4,
        )
        self.assertEqual(
            parsed["rows"][0]["application_details_memory_per_server_gb"],
            8,
        )
        request = self.requests[0]
        self.assertEqual(request["model"], "gpt-5-mini")
        self.assertEqual(request["reasoning"]["effort"], "low")
        self.assertEqual(request["text"]["format"]["type"], "json_schema")
        self.assertTrue(request["text"]["format"]["strict"])

    def test_architecture_planner_is_constrained_and_low_reasoning(self):
        self.responses.append(
            {
                "summary": "Private hub-and-spoke landing zone for the priced workloads.",
                "pattern": "landing_zone_hub_spoke",
                "referenceBaseline": "Hub and spoke OCI",
                "referenceRationale": "It matches the landing-zone network posture.",
                "networkPosture": "private_by_default",
                "availabilityPosture": "single_region",
                "subnetScope": "regional",
                "databaseStrategy": "No database service is present in the priced BOM.",
                "ingressStrategy": "No public ingress was supplied.",
                "egressStrategy": "Use NAT and Service Gateway paths from private subnets.",
                "managementStrategy": "Use Bastion and shared observability controls.",
                "workloadGroupingRationale": "Keep production and non-production isolated.",
                "haDrRationale": "Use the availability-domain and DR choices selected by the user.",
                "servicePlacements": [
                    {
                        "service": "Compute",
                        "placement": "private_app_subnet",
                        "evidence": "priced",
                        "rationale": "The BOM contains compute workloads.",
                    }
                ],
                "trafficFlows": [
                    {
                        "source": "On-premises",
                        "target": "DRG",
                        "protocol": "FastConnect or IPSec",
                        "purpose": "Private migration and operations traffic.",
                    }
                ],
                "iconMappings": [
                    {
                        "service": "Compute",
                        "iconQuery": "virtual machine",
                        "evidence": "priced",
                        "fallbackPolicy": "alias_allowed",
                        "rationale": "The BOM contains OCI compute workloads.",
                    }
                ],
                "securityControls": ["Private subnets", "Hub inspection"],
                "assumptions": ["No public application exposure was supplied."],
                "warnings": [],
                "qaChecks": [
                    "Validate numeric fidelity.",
                    "Check connector and label overlap.",
                ],
                "architectureReview": [
                    "Compute remains in private subnets.",
                    "No DR claim is made.",
                ],
                "visualReview": [
                    "Use official OCI icons.",
                    "Keep connector lanes clear.",
                ],
            }
        )
        pricing = {
            "totals": {
                "monthly": 1000,
                "ocpus": 4,
                "memoryGb": 16,
                "blockStorageGb": 500,
            },
            "rows": [
                {
                    "rowId": "row-1",
                    "ociProduct": "Compute",
                    "specs": {"ocpus": 4, "memoryGb": 16, "blockStorageGb": 500},
                }
            ],
        }
        fields = [
            {"key": "application_name", "label": "Application Name"},
            {"key": "environment", "label": "Environment"},
        ]
        rows = [
            {
                "__id": "row-1",
                "application_name": "Order Management",
                "environment": "Prod",
            }
        ]
        plan, warning = app.call_llm_architecture_plan(
            pricing,
            rows,
            fields,
            {"primaryRegion": "us-ashburn-1", "enableDr": False},
            bom_name="Example",
            shape_label="E6 Ax",
        )

        self.assertIsNone(warning)
        self.assertEqual(plan["pattern"], "landing_zone_hub_spoke")
        request = self.requests[0]
        self.assertEqual(request["model"], "gpt-5-mini")
        self.assertEqual(request["reasoning"]["effort"], "low")
        self.assertEqual(
            request["text"]["format"]["name"],
            "oci_architecture_plan",
        )

    def test_cloud_bill_ai_only_receives_unresolved_patterns(self):
        self.responses.append(
            {
                "summary": "Mapped the unresolved queue usage.",
                "mappings": [
                    {
                        "patternId": "pattern-1",
                        "ociServiceCategory": "Integration",
                        "ociProduct": "OCI Queue",
                        "targetUsageUnit": "requests",
                        "quantityMultiplier": None,
                        "confidence": 0.91,
                        "reviewRequired": False,
                        "rationale": "The source line is an asynchronous queue service.",
                    }
                ],
                "warnings": [],
            }
        )
        parsed = {
            "metadata": {
                "detectedProvider": "AWS",
                "parser": "cloud-bill-adapter",
                "mappedCount": 1,
                "unmappedCount": 1,
            },
            "rows": [
                {
                    "__id": "known",
                    "source_provider": "AWS",
                    "source_service": "AmazonEC2",
                    "source_product": "m6i.large",
                    "usage_unit": "Hrs",
                    "oci_service_category": "Compute",
                    "oci_product": "OCI Compute",
                    "mapping_confidence": "95%",
                },
                {
                    "__id": "unknown",
                    "source_provider": "AWS",
                    "source_service": "AmazonSQS",
                    "source_product": "Requests",
                    "usage_unit": "Requests",
                    "oci_service_category": "",
                    "oci_product": "",
                    "mapping_confidence": "Needs review",
                },
            ],
        }

        result = app.call_llm_cloud_bill_mapping(parsed)

        self.assertEqual(result["rows"][0]["oci_product"], "OCI Compute")
        self.assertEqual(result["rows"][1]["oci_product"], "OCI Queue")
        self.assertEqual(result["metadata"]["llmBillMappedRows"], 1)
        request = self.requests[0]
        self.assertEqual(request["model"], "gpt-5-mini")
        self.assertEqual(request["reasoning"]["effort"], "low")
        self.assertEqual(
            request["text"]["format"]["name"],
            "oci_cloud_bill_mapping",
        )
        self.assertTrue(request["text"]["format"]["strict"])
        request_text = request["input"][1]["content"]
        self.assertIn("AmazonSQS", request_text)
        self.assertNotIn("AmazonEC2", request_text)

    def test_three_bounded_ai_features_are_active(self):
        self.assertEqual(
            set(app.OPENAI_ACTIVE_FEATURES),
            {"inventory_scrub", "cloud_bill_mapping", "architecture"},
        )
        self.assertNotIn(
            "call_llm_cloud_bill_mapping",
            inspect.getsource(app.parse_cloud_bill),
        )
        self.assertIn(
            "call_llm_cloud_bill_mapping",
            inspect.getsource(app.parse_workbook),
        )
        self.assertNotIn(
            "call_llm_mapping",
            inspect.getsource(app.IntakeHandler.handle_price),
        )
        table_edit_source = inspect.getsource(app.IntakeHandler.handle_table_edit)
        self.assertNotIn("call_llm_table_edit", table_edit_source)
        self.assertIn("410", table_edit_source)


if __name__ == "__main__":
    unittest.main()
