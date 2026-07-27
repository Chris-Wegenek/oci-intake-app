#!/usr/bin/env python3
"""Focused FastConnect catalog, pricing, and export-line regression checks."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import oci_catalog


EXPECTED = {
    "1G": {"label": "1 Gbps", "sku": "B88325", "rate": 0.2125},
    "10G": {"label": "10 Gbps", "sku": "B88326", "rate": 1.275},
    "100G": {"label": "100 Gbps", "sku": "B93126", "rate": 10.75},
    "400G": {"label": "400 Gbps", "sku": "B107975", "rate": 20.00},
}


entry = next(item for item in oci_catalog.CURATED if item["id"] == "fastconnect")
speed_field = next(field for field in entry["fields"] if field["key"] == "speed")
assert [option["value"] for option in speed_field["options"]] == list(EXPECTED)
assert speed_field["default"] == "10G"

source = json.loads((ROOT / "data" / "oci_service_prices.json").read_text())
source_fastconnect = source["services"]["OCI FastConnect"]
assert source_fastconnect["speedRates"] == {
    key: expected["rate"] for key, expected in EXPECTED.items()
}
assert source_fastconnect["speedSkus"] == {
    key: expected["sku"] for key, expected in EXPECTED.items()
}

for speed, expected in EXPECTED.items():
    values = {"speed": speed, "ports": 2, "__hours": 730}
    monthly = round(expected["rate"] * 2 * 730, 2)
    assert oci_catalog.line_cost(entry, values) == monthly

    breakdown = oci_catalog.line_breakdown(entry, values)
    assert breakdown == [{
        "sku": expected["sku"],
        "desc": f"FastConnect {expected['label']} port",
        "qty": 2.0,
        "rate": expected["rate"],
        "hours": 730.0,
        "monthly": monthly,
    }]

    priced, total = oci_catalog.price_extras([{
        "catalogId": "fastconnect",
        "values": values,
    }])
    assert total == monthly
    assert priced[0]["name"] == f"FastConnect port ({expected['label']})"
    assert priced[0]["sku"] == expected["sku"]
    assert priced[0]["rate"] == expected["rate"]
    assert priced[0]["monthly"] == monthly
    assert priced[0]["skus"] == breakdown

custom_hours = {"speed": "100G", "ports": 1, "__hours": 365}
assert oci_catalog.line_cost(entry, custom_hours) == 3923.75

print("FastConnect port pricing regression checks passed.")
