"""Regression checks for OCI Object Storage tier pricing and SKU breakdowns."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
import oci_catalog


def entry(catalog_id):
    return next(item for item in oci_catalog.CURATED if item["id"] == catalog_id)


def sku_map(lines):
    return {line["sku"]: line for line in lines}


def main():
    storage = oci_catalog.search("", "Storage")
    tiers = {item["id"]: item for item in storage}

    assert len(storage) == 5
    assert {"object", "object_ia", "archive"} <= set(tiers)
    assert tiers["object"]["sku"] == "B91628"
    assert tiers["object_ia"]["sku"] == "B93000"
    assert tiers["archive"]["sku"] == "B91633"

    standard_values = {"gb": 1000, "requests": 0}
    ia_values = {"gb": 1000, "retrievalGb": 100, "requests": 15}
    archive_values = {"gb": 1000, "requests": 15}

    assert oci_catalog.line_cost(entry("object"), standard_values) == 25.24
    assert oci_catalog.line_cost(entry("object_ia"), ia_values) == 10.83
    assert oci_catalog.line_cost(entry("archive"), archive_values) == 2.61

    ia_lines = sku_map(oci_catalog.line_breakdown(entry("object_ia"), ia_values))
    assert set(ia_lines) == {"B93000", "B93001", "B91627"}
    assert ia_lines["B93000"]["monthly"] == 9.9
    assert ia_lines["B93001"]["monthly"] == 0.9
    assert ia_lines["B91627"]["monthly"] == 0.03

    archive_lines = sku_map(oci_catalog.line_breakdown(entry("archive"), archive_values))
    assert set(archive_lines) == {"B91633", "B91627"}
    assert archive_lines["B91633"]["monthly"] == 2.57
    assert archive_lines["B91627"]["monthly"] == 0.03

    priced, total = oci_catalog.price_extras([
        {"catalogId": "object_ia", "values": ia_values},
        {"catalogId": "archive", "values": archive_values},
    ])
    assert total == 13.44
    assert [item["sku"] for item in priced] == ["B93000", "B91633"]
    assert {line["sku"] for item in priced for line in item["skus"]} == {
        "B93000", "B93001", "B91627", "B91633",
    }

    fields = [
        {"key": "source_service", "label": "Service"},
        {"key": "source_product", "label": "Product"},
        {"key": "usage_unit", "label": "Unit"},
    ]
    ia_capacity, _ = app.classify_full_service_item({
        "source_service": "Amazon S3",
        "source_product": "Standard-IA TimedStorage",
        "usage_unit": "GB",
    }, fields)
    ia_retrieval, _ = app.classify_full_service_item({
        "source_service": "Amazon S3",
        "source_product": "Standard-IA Data Retrieval",
        "usage_unit": "GB",
    }, fields)
    archive, _ = app.classify_full_service_item({
        "source_service": "Amazon S3",
        "source_product": "Glacier Deep Archive TimedStorage",
        "usage_unit": "GB",
    }, fields)
    assert ia_capacity["sku"] == "B93000"
    assert ia_retrieval["sku"] == "B93001"
    assert archive["sku"] == "B91633"

    assert app.map_service_comparison("aws", "Amazon S3", "Standard-IA")["product"] == (
        "OCI Infrequent Access Storage"
    )
    assert app.map_service_comparison("azure", "Blob Cool LRS")["product"] == (
        "OCI Infrequent Access Storage"
    )

    print("Object Storage tier pricing regression checks passed.")


if __name__ == "__main__":
    main()
