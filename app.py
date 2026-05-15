#!/usr/bin/env python3
import warnings

warnings.filterwarnings("ignore", message="'cgi' is deprecated.*", category=DeprecationWarning)

import cgi
import json
import math
import mimetypes
import os
import re
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
UPLOAD_DIR = Path(
    os.environ.get(
        "UPLOAD_DIR",
        "/tmp/oci-intake-uploads" if os.environ.get("VERCEL") else str(ROOT / "uploads"),
    ),
)
UPLOAD_DIR.mkdir(exist_ok=True)

PORT = int(os.environ.get("PORT", "8787"))
HOURS_PER_MONTH = 730

DEFAULT_SHAPE_KEY = "e6-standard-ax"

CANONICAL_INVENTORY_FIELDS = [
    {
        "key": "application_name",
        "label": "Application Name",
        "description": "Application, workload, server, VM, host, or inventory item name.",
        "aliases": [
            "application name",
            "app name",
            "name",
            "product",
            "workload",
            "server name",
            "hostname",
            "host name",
            "vm name",
            "asset name",
            "resource id",
            "resourceid",
            "instance id",
            "tags.name",
            "tags.appid",
        ],
    },
    {
        "key": "environment",
        "label": "Environment",
        "description": "Environment such as prod, dev, qa, test, uat, disaster recovery, or staging.",
        "aliases": ["environment", "env", "tier", "stage", "lifecycle"],
    },
    {
        "key": "application_details",
        "label": "Application Details",
        "description": "Application description, type, function, business role, or notes.",
        "aliases": [
            "application details",
            "application type",
            "description",
            "business function",
            "app details",
            "role",
            "purpose",
            "resource id",
            "resourceid",
            "private ip",
            "configuration privateipaddress",
        ],
    },
    {
        "key": "application_details_application_version",
        "label": "Application Details: Application Version",
        "description": "Application, product, or platform version.",
        "aliases": ["application version", "app version", "version", "release"],
    },
    {
        "key": "application_details_operating_system",
        "label": "Application Details: Operating System",
        "description": "Operating system name and version.",
        "aliases": ["operating system", "os", "os version", "platform", "tags.os"],
    },
    {
        "key": "application_details_number_of_servers",
        "label": "Application Details: Number of Servers",
        "description": "How many application servers, VMs, hosts, nodes, or instances this row represents.",
        "aliases": ["number of servers", "server count", "servers", "instances", "nodes", "vm count", "quantity", "qty"],
    },
    {
        "key": "application_details_number_of_cpu_cores_per_server",
        "label": "Application Details: Number of CPU Cores per Server",
        "description": "vCPU, CPU core, processor, or core count per server. 2 vCPU equals 1 OCPU.",
        "aliases": ["number of cpu cores per server", "cpu", "cpus", "vcpu", "vcpus", "cores", "cpu cores", "processors"],
    },
    {
        "key": "application_details_memory_per_server_gb",
        "label": "Application Details: Memory per server (GB)",
        "description": "RAM or memory per server in GB.",
        "aliases": ["memory per server", "memory", "ram", "memory gb", "ram gb", "mem"],
    },
    {
        "key": "application_details_chipset",
        "label": "Application Details: Chipset",
        "description": "CPU chipset, processor family, architecture, or platform family.",
        "aliases": ["chipset", "processor family", "cpu type", "architecture", "processor", "hardware family"],
    },
    {
        "key": "application_details_local_storage_gb",
        "label": "Application Details: Local Storage (GB)",
        "description": "Local VM disk, OS disk, data disk, or directly attached block storage in GB.",
        "aliases": ["local storage", "storage", "disk", "disk gb", "allocated storage", "block storage", "data disk", "os disk"],
    },
    {
        "key": "application_details_shared_storage_gb",
        "label": "Application Details: Shared Storage (GB)",
        "description": "Shared, NAS, NFS, SMB, ETL, or file storage in GB.",
        "aliases": ["shared storage", "nas", "nfs", "file storage", "shared disk", "smb"],
    },
    {
        "key": "database_details_number_of_database_servers",
        "label": "Database Details: Number of Database Servers",
        "description": "How many database servers, database nodes, or DB instances this row represents.",
        "aliases": ["number of database servers", "database servers", "db servers", "db nodes", "database instances"],
    },
    {
        "key": "database_details_number_of_cpu_cores_per_server",
        "label": "Database Details: Number of CPU Cores per Server",
        "description": "Database vCPU, CPU core, processor, or core count per DB server.",
        "aliases": ["database cpu", "db cpu", "database cores", "db cores", "database vcpu", "db vcpu"],
    },
    {
        "key": "database_details_memory_per_server_gb",
        "label": "Database Details: Memory per server (GB)",
        "description": "Database RAM or memory per DB server in GB.",
        "aliases": ["database memory", "db memory", "database ram", "db ram"],
    },
    {
        "key": "database_details_total_allocated_storage_gb",
        "label": "Database Details: Total Allocated Storage (GB)",
        "description": "Database storage, allocated DB storage, datafile size, or total database disk in GB.",
        "aliases": ["total allocated storage", "database storage", "db storage", "database size", "db size", "total storage"],
    },
]

CANONICAL_FIELD_BY_KEY = {field["key"]: field for field in CANONICAL_INVENTORY_FIELDS}
NUMERIC_FIELD_KEYS = {
    "application_details_number_of_servers",
    "application_details_number_of_cpu_cores_per_server",
    "application_details_memory_per_server_gb",
    "application_details_local_storage_gb",
    "application_details_shared_storage_gb",
    "database_details_number_of_database_servers",
    "database_details_number_of_cpu_cores_per_server",
    "database_details_memory_per_server_gb",
    "database_details_total_allocated_storage_gb",
}
SIZE_FIELD_KEYS = {
    "application_details_memory_per_server_gb",
    "application_details_local_storage_gb",
    "application_details_shared_storage_gb",
    "database_details_memory_per_server_gb",
    "database_details_total_allocated_storage_gb",
}

SHAPE_DEFINITIONS = [
    {
        "key": "e4-standard",
        "label": "E4 Standard",
        "shortLabel": "E4",
        "family": "AMD flexible shape",
        "computeRate": 0.0250,
        "memoryRate": 0.0015,
        "summary": "Lower memory rate with a mid-tier OCPU rate for steady general workloads.",
        "accent": "#2f5d28",
    },
    {
        "key": "e5-standard",
        "label": "E5 Standard",
        "shortLabel": "E5",
        "family": "AMD flexible shape",
        "computeRate": 0.0300,
        "memoryRate": 0.0020,
        "summary": "Current generation AMD shape with identical E6 Standard compute and memory rates.",
        "accent": "#365f1c",
    },
    {
        "key": DEFAULT_SHAPE_KEY,
        "label": "E6 Standard Ax",
        "shortLabel": "E6 Ax",
        "family": "AMD Ax flexible shape",
        "computeRate": 0.0138,
        "memoryRate": 0.0108,
        "summary": "Lower OCPU rate and higher memory rate; useful when compute-heavy rows dominate.",
        "accent": "#164f68",
    },
]

SHAPE_LOOKUP = {shape["key"]: shape for shape in SHAPE_DEFINITIONS}

STORAGE_RATE_ITEMS = [
    {
        "sku": "B91961",
        "description": "Block Volume Storage (GB-mo)",
        "unit": "GB-month",
        "rate": 0.0255,
        "notes": "VM OS / data disks",
    },
    {
        "sku": "B89057",
        "description": "File Storage (GB-mo)",
        "unit": "GB-month",
        "rate": 0.3000,
        "notes": "NAS / ETL shared file storage",
    },
]


def load_local_env():
    env_path = ROOT / ".env.local"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()


def clean_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def make_key(label, seen):
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "column"
    key = base
    idx = 2
    while key in seen:
        key = f"{base}_{idx}"
        idx += 1
    seen.add(key)
    return key


def clean_cell(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float):
        return int(value) if value.is_integer() else round(value, 4)
    return clean_text(value)


def to_number(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    text = str(value).replace(",", "").strip()
    if not text or text == "-":
        return default
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else default


def to_gb(value, default=0.0):
    number = to_number(value, default)
    text = normalize(value)
    if not text:
        return default
    if re.search(r"\btb\b|terabyte", text):
        return number * 1024
    if re.search(r"\bmb\b|megabyte", text):
        return number / 1024
    if re.search(r"\bkb\b|kilobyte", text):
        return number / (1024 * 1024)
    return number


def compact_number(value):
    if value == "":
        return ""
    number = float(value)
    if number.is_integer():
        return int(number)
    return round(number, 4)


def normalize_inventory_value(key, value):
    if clean_text(value) == "":
        return ""
    if key in SIZE_FIELD_KEYS:
        return compact_number(to_gb(value))
    if key in NUMERIC_FIELD_KEYS:
        return compact_number(to_number(value))
    return clean_cell(value)


def parse_json_cell(value):
    text = clean_text(value)
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def add_json_pair(pairs, key, value):
    key_text = clean_text(key)
    value_text = clean_cell(value)
    if key_text and value_text != "":
        pairs[key_text] = value_text


def flatten_json_tags(value):
    parsed = parse_json_cell(value)
    if parsed is None:
        return {}

    pairs = {}

    def visit(node, prefix=""):
        if isinstance(node, dict):
            tag_key = node.get("key") or node.get("Key") or node.get("tagKey")
            tag_value = node.get("value") or node.get("Value") or node.get("tagValue")
            tag_text = node.get("tag") or node.get("Tag")
            if tag_key is not None and tag_value is not None:
                add_json_pair(pairs, tag_key, tag_value)
            if tag_text and "=" in clean_text(tag_text):
                left, right = clean_text(tag_text).split("=", 1)
                add_json_pair(pairs, left, tag_value if tag_value is not None else right)

            for key, child in node.items():
                child_key = clean_text(key)
                path = f"{prefix}.{child_key}" if prefix else child_key
                if isinstance(child, (dict, list)):
                    visit(child, path)
                elif child_key not in {"key", "Key", "value", "Value", "tag", "Tag"}:
                    add_json_pair(pairs, path, child)
        elif isinstance(node, list):
            for child in node:
                visit(child, prefix)

    visit(parsed)
    return pairs


def json_key_match_score(candidate, target):
    candidate_norm = normalize(candidate)
    target_norm = normalize(target)
    if not candidate_norm or not target_norm:
        return 0
    if candidate_norm == target_norm:
        return 100
    if candidate_norm.endswith(f" {target_norm}") or candidate_norm.endswith(target_norm):
        return 80
    if target_norm in candidate_norm:
        return 60
    if candidate_norm in target_norm and len(candidate_norm) >= 3:
        return 40
    return 0


def value_from_json_cell(value, json_key):
    target = clean_text(json_key)
    if not target:
        return ""
    pairs = flatten_json_tags(value)
    if not pairs:
        return ""
    best_key = ""
    best_score = 0
    for key in pairs:
        score = json_key_match_score(key, target)
        if score > best_score:
            best_key = key
            best_score = score
    return pairs.get(best_key, "") if best_score >= 40 else ""


def summarize_json_cell(value, max_items=8):
    pairs = flatten_json_tags(value)
    if not pairs:
        return None
    return {
        "keys": list(pairs.keys())[:max_items],
        "preview": {key: pairs[key] for key in list(pairs.keys())[:max_items]},
    }


def json_column_header(raw, col_idx):
    parts = []
    for row_idx in range(min(8, len(raw.index))):
        value = raw.iat[row_idx, col_idx]
        text = clean_text(value)
        if text and parse_json_cell(value) is None and text not in parts:
            parts.append(text)
    return " ".join(parts[:3])


def canonical_fields_payload():
    return [
        {
            "key": field["key"],
            "label": field["label"],
            "sourceColumn": None,
            "important": True,
        }
        for field in CANONICAL_INVENTORY_FIELDS
    ]


def canonical_field_prompt():
    return [
        {
            "key": field["key"],
            "label": field["label"],
            "description": field["description"],
            "aliases": field["aliases"],
        }
        for field in CANONICAL_INVENTORY_FIELDS
    ]


def resolve_shape(shape_key=None):
    return SHAPE_LOOKUP.get(shape_key or DEFAULT_SHAPE_KEY, SHAPE_LOOKUP[DEFAULT_SHAPE_KEY])


def build_rate_card(shape_key=None):
    shape = resolve_shape(shape_key)
    return [
        {
            "sku": "B97384",
            "description": "OCPU-hr rate (Compute)",
            "unit": "OCPU-hour",
            "rate": shape["computeRate"],
            "notes": f"{shape['label']} OCPU-hours x 730 hrs/mo",
        },
        {
            "sku": "B97385",
            "description": "Memory GB-hr rate",
            "unit": "GB-hour",
            "rate": shape["memoryRate"],
            "notes": f"{shape['label']} GB-hours x 730 hrs/mo",
        },
        *[item.copy() for item in STORAGE_RATE_ITEMS],
    ]


def shape_payload(shape_key=None):
    shape = resolve_shape(shape_key)
    return {
        "key": shape["key"],
        "label": shape["label"],
        "shortLabel": shape["shortLabel"],
        "family": shape["family"],
        "summary": shape["summary"],
        "accent": shape["accent"],
        "computeRate": shape["computeRate"],
        "memoryRate": shape["memoryRate"],
        "hoursPerMonth": HOURS_PER_MONTH,
        "rateCard": build_rate_card(shape["key"]),
    }


def all_shape_payloads():
    return [shape_payload(shape["key"]) for shape in SHAPE_DEFINITIONS]


def pick_sheet(excel_file):
    names = excel_file.sheet_names
    for name in names:
        if normalize(name) == "current app db infra details":
            return name
    return names[1] if len(names) > 1 else names[0]


def detect_header_rows(raw):
    sample_rows = min(10, len(raw.index))
    counts = []
    for idx in range(sample_rows):
        non_blank = sum(1 for value in raw.iloc[idx].tolist() if clean_text(value))
        counts.append((non_blank, idx))
    header_row = max(counts)[1] if counts else 0
    group_row = max(0, header_row - 1)
    return group_row, header_row, header_row + 1


def is_important(label):
    text = normalize(label)
    terms = [
        "application name",
        "environment",
        "application type",
        "number of servers",
        "number of database servers",
        "number of cpu cores per server",
        "memory per server gb",
        "local storage gb",
        "shared storage gb",
        "database type",
        "database size gb",
        "total allocated storage gb",
        "total storage gb",
        "storage iops",
    ]
    return any(term in text for term in terms)


def build_fields(raw, group_row, header_row):
    sections = {"application details", "database details", "oci details"}
    fields = []
    seen = set()
    current_section = ""

    for col_idx in range(len(raw.columns)):
        top = clean_text(raw.iat[group_row, col_idx]) if group_row < len(raw.index) else ""
        sub = clean_text(raw.iat[header_row, col_idx]) if header_row < len(raw.index) else ""
        top_norm = normalize(top)

        if top_norm in sections:
            current_section = top
            label = f"{current_section}: {sub}" if sub else current_section
        elif sub:
            label = f"{current_section}: {sub}" if current_section else sub
        elif top:
            label = top
        else:
            label = f"Column {col_idx + 1}"

        label = clean_text(label)
        fields.append(
            {
                "key": make_key(label, seen),
                "label": label,
                "sourceColumn": col_idx + 1,
                "important": is_important(label),
            }
        )

    return fields


def parse_workbook_rule_based(path):
    excel_file = pd.ExcelFile(path)
    sheet = pick_sheet(excel_file)
    raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
    group_row, header_row, data_start = detect_header_rows(raw)
    fields = build_fields(raw, group_row, header_row)

    rows = []
    for raw_idx in range(data_start, len(raw.index)):
        values = raw.iloc[raw_idx].tolist()
        if not any(clean_text(value) for value in values):
            continue
        row = {"__id": f"row-{raw_idx + 1}", "__sourceRow": raw_idx + 1, "__approved": True}
        for col_idx, field in enumerate(fields):
            row[field["key"]] = clean_cell(values[col_idx]) if col_idx < len(values) else ""
        rows.append(row)

    return {
        "fileName": Path(path).name,
        "sheetName": sheet,
        "sheets": excel_file.sheet_names,
        "fields": fields,
        "rows": rows,
        "rateCard": build_rate_card(DEFAULT_SHAPE_KEY),
        "rateCards": all_shape_payloads(),
        "selectedShape": shape_payload(DEFAULT_SHAPE_KEY),
        "metadata": {
            "headerRow": header_row + 1,
            "groupRow": group_row + 1,
            "dataStartRow": data_start + 1,
            "rowCount": len(rows),
            "columnCount": len(fields),
            "parser": "rule-based",
        },
    }


def workbook_digest(path):
    excel_file = pd.ExcelFile(path)
    sheets = []
    for sheet in excel_file.sheet_names:
        raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
        max_rows = min(45, len(raw.index))
        max_cols = min(35, len(raw.columns))
        sample_rows = []
        row_density = []
        json_columns = {}

        for row_idx in range(min(100, len(raw.index))):
            values = raw.iloc[row_idx].tolist()
            non_blank = [clean_text(value) for value in values if clean_text(value)]
            if non_blank:
                row_density.append(
                    {
                        "row": row_idx + 1,
                        "nonBlank": len(non_blank),
                        "preview": non_blank[:12],
                    }
                )

        for row_idx in range(max_rows):
            cells = []
            for col_idx in range(max_cols):
                value = clean_text(raw.iat[row_idx, col_idx])
                if value:
                    cell = {"column": col_idx + 1, "value": value[:140]}
                    json_summary = summarize_json_cell(value)
                    if json_summary:
                        cell["jsonKeys"] = json_summary["keys"]
                        cell["jsonPreview"] = json_summary["preview"]
                        column_info = json_columns.setdefault(
                            col_idx + 1,
                            {
                                "column": col_idx + 1,
                                "sampleRows": [],
                                "keys": {},
                            },
                        )
                        column_info["sampleRows"].append(
                            {
                                "row": row_idx + 1,
                                "preview": json_summary["preview"],
                            }
                        )
                        for key, item in json_summary["preview"].items():
                            column_info["keys"].setdefault(key, clean_text(item)[:80])
                    cells.append(cell)
            if cells:
                sample_rows.append({"row": row_idx + 1, "cells": cells[:24]})

        json_column_summaries = []
        for col_idx, info in json_columns.items():
            json_column_summaries.append(
                {
                    "column": col_idx,
                    "header": json_column_header(raw, col_idx - 1),
                    "keys": list(info["keys"].keys())[:30],
                    "sampleValues": dict(list(info["keys"].items())[:12]),
                    "sampleRows": info["sampleRows"][:3],
                }
            )

        sheets.append(
            {
                "name": sheet,
                "rowCount": int(len(raw.index)),
                "columnCount": int(len(raw.columns)),
                "sampleRows": sample_rows,
                "jsonColumns": json_column_summaries,
                "likelyHeaderRows": sorted(row_density, key=lambda item: item["nonBlank"], reverse=True)[:8],
            }
        )

    return {"sheets": sheets}


def header_label(raw, header_rows, col_idx):
    parts = []
    for row_number in header_rows:
        row_idx = int(row_number) - 1
        if 0 <= row_idx < len(raw.index):
            part = clean_text(raw.iat[row_idx, col_idx])
            if part and part not in parts:
                parts.append(part)
    return " ".join(parts)


def alias_score(label, field):
    label_norm = normalize(label)
    if not label_norm:
        return 0
    aliases = [field["label"], *field["aliases"]]
    score = 0
    for alias in aliases:
        alias_norm = normalize(alias)
        if not alias_norm:
            continue
        if label_norm == alias_norm:
            score = max(score, 100 + len(alias_norm))
        elif alias_norm in label_norm:
            score = max(score, 60 + len(alias_norm))
        elif label_norm in alias_norm and len(label_norm) >= 4:
            score = max(score, 30 + len(label_norm))

    is_database = any(term in label_norm for term in ["database", "db ", " db", "sql", "oracle db"])
    field_is_database = field["key"].startswith("database_details")
    if is_database and field_is_database:
        score += 14
    elif is_database and not field_is_database:
        score -= 12

    is_shared = any(term in label_norm for term in ["shared", "nas", "nfs", "file"])
    if is_shared and field["key"] == "application_details_shared_storage_gb":
        score += 16
    elif is_shared and field["key"] == "application_details_local_storage_gb":
        score -= 10

    return score


def infer_column_mappings(raw, header_rows):
    mappings = {}
    for col_idx in range(len(raw.columns)):
        label = header_label(raw, header_rows, col_idx)
        best = None
        best_score = 0
        for field in CANONICAL_INVENTORY_FIELDS:
            score = alias_score(label, field)
            if score > best_score:
                best = field
                best_score = score
        if best and best_score >= 45 and best["key"] not in mappings:
            mappings[best["key"]] = {
                "canonicalKey": best["key"],
                "sourceColumn": col_idx + 1,
                "sourceHeader": label,
                "confidence": min(0.98, best_score / 130),
            }
    return mappings


JSON_TAG_FIELD_ALIASES = {
    "application_name": ["Name", "name", "appName", "application", "applicationName", "appId", "appID"],
    "environment": ["environment", "env", "stage", "lifecycle"],
    "application_details": ["role", "description", "appId", "costCenter", "owner"],
    "application_details_application_version": ["applicationVersion", "appVersion", "version", "release"],
    "application_details_operating_system": ["os", "operatingSystem", "operating_system", "platform"],
}


def infer_json_mappings(raw, header_rows, data_start_row):
    mappings = {}
    start_idx = max(0, data_start_row - 1)
    end_idx = min(len(raw.index), start_idx + 30)
    for col_idx in range(len(raw.columns)):
        label = header_label(raw, header_rows, col_idx)
        column_pairs = {}
        for row_idx in range(start_idx, end_idx):
            for key, value in flatten_json_tags(raw.iat[row_idx, col_idx]).items():
                column_pairs.setdefault(key, clean_text(value))
        if not column_pairs:
            continue

        for canonical_key, aliases in JSON_TAG_FIELD_ALIASES.items():
            if canonical_key in mappings:
                continue
            best_key = ""
            best_score = 0
            for candidate in column_pairs:
                for alias in aliases:
                    score = json_key_match_score(candidate, alias)
                    if score > best_score:
                        best_key = candidate
                        best_score = score
            if best_score >= 60:
                mappings[canonical_key] = {
                    "canonicalKey": canonical_key,
                    "sourceColumn": col_idx + 1,
                    "sourceHeader": label,
                    "jsonKey": best_key,
                    "confidence": min(0.95, best_score / 100),
                    "transform": f"Read '{best_key}' from JSON/tag data.",
                }
    return mappings


def validated_column_mappings(raw, header_rows, mappings):
    validated = {}
    for key, mapping in mappings.items():
        field = CANONICAL_FIELD_BY_KEY.get(key)
        if not field:
            continue
        source_column = int(to_number(mapping.get("sourceColumn"), 0))
        if source_column <= 0:
            continue
        actual_header = header_label(raw, header_rows, source_column - 1) or clean_text(mapping.get("sourceHeader"))
        has_json_source = clean_text(mapping.get("jsonKey") or mapping.get("jsonPath"))
        if has_json_source:
            json_aliases = [field["label"], *field["aliases"], *JSON_TAG_FIELD_ALIASES.get(key, [])]
            if max((json_key_match_score(has_json_source, alias) for alias in json_aliases), default=0) < 40:
                continue
        if actual_header and not has_json_source and alias_score(actual_header, field) < 35:
            continue
        validated[key] = {
            **mapping,
            "sourceHeader": actual_header,
            "sourceColumn": source_column,
        }
    return validated


def normalize_workbook_plan(plan, excel_file):
    if not isinstance(plan, dict):
        return None
    sheet_name = clean_text(plan.get("sheetName"))
    if sheet_name not in excel_file.sheet_names:
        normalized_target = normalize(sheet_name)
        matches = [name for name in excel_file.sheet_names if normalize(name) == normalized_target]
        sheet_name = matches[0] if matches else ""
    if not sheet_name:
        return None

    header_rows = plan.get("headerRows") or plan.get("headerRow") or []
    if isinstance(header_rows, (str, int, float)):
        header_rows = [header_rows]
    header_rows = [int(to_number(item)) for item in header_rows if to_number(item)]
    header_rows = sorted({row for row in header_rows if row > 0})

    data_start = int(to_number(plan.get("dataStartRow"), 0))
    if data_start <= 0 and header_rows:
        data_start = max(header_rows) + 1
    if data_start <= 0:
        data_start = 2

    data_end = int(to_number(plan.get("dataEndRow"), 0))
    raw_mappings = plan.get("columnMappings", [])
    if isinstance(raw_mappings, dict):
        raw_mappings = [
            {"canonicalKey": key, **value} if isinstance(value, dict) else {"canonicalKey": key, "sourceColumn": value}
            for key, value in raw_mappings.items()
        ]

    mappings = {}
    for item in raw_mappings:
        if not isinstance(item, dict):
            continue
        key = clean_text(item.get("canonicalKey") or item.get("key"))
        source_column = int(to_number(item.get("sourceColumn"), 0))
        if key in CANONICAL_FIELD_BY_KEY and source_column > 0:
            mappings[key] = {
                "canonicalKey": key,
                "sourceColumn": source_column,
                "sourceHeader": clean_text(item.get("sourceHeader")),
                "jsonKey": clean_text(item.get("jsonKey") or item.get("tagKey")),
                "jsonPath": clean_text(item.get("jsonPath")),
                "confidence": to_number(item.get("confidence"), 0),
                "transform": clean_text(item.get("transform")),
            }

    return {
        "sheetName": sheet_name,
        "headerRows": header_rows,
        "dataStartRow": data_start,
        "dataEndRow": data_end or None,
        "serverGrain": normalize(plan.get("serverGrain")) or "unknown",
        "confidence": to_number(plan.get("confidence"), 0),
        "columnMappings": mappings,
        "notes": plan.get("notes", []),
    }


def should_keep_inventory_row(row):
    identity = clean_text(row.get("application_name")) or clean_text(row.get("environment"))
    resources = [
        to_number(row.get("application_details_number_of_servers")),
        to_number(row.get("application_details_number_of_cpu_cores_per_server")),
        to_number(row.get("application_details_memory_per_server_gb")),
        to_number(row.get("application_details_local_storage_gb")),
        to_number(row.get("database_details_number_of_database_servers")),
        to_number(row.get("database_details_number_of_cpu_cores_per_server")),
        to_number(row.get("database_details_memory_per_server_gb")),
        to_number(row.get("database_details_total_allocated_storage_gb")),
    ]
    populated_fields = sum(
        1
        for field in CANONICAL_INVENTORY_FIELDS
        if clean_text(row.get(field["key"])) not in {"", "0", "0.0"}
    )
    return bool(identity and (any(value for value in resources) or populated_fields >= 2))


def parse_workbook_from_plan(path, plan):
    excel_file = pd.ExcelFile(path)
    raw = pd.read_excel(path, sheet_name=plan["sheetName"], header=None, dtype=object)
    header_rows = plan["headerRows"] or [max(1, plan["dataStartRow"] - 1)]
    mappings = validated_column_mappings(raw, header_rows, dict(plan["columnMappings"]))
    inferred_json = infer_json_mappings(raw, header_rows, plan["dataStartRow"])
    for key, mapping in inferred_json.items():
        mappings.setdefault(key, mapping)
    inferred = infer_column_mappings(raw, header_rows)
    for key, mapping in inferred.items():
        mappings.setdefault(key, mapping)

    fields = canonical_fields_payload()
    for field in fields:
        mapping = mappings.get(field["key"])
        if mapping:
            field["sourceColumn"] = mapping["sourceColumn"]
            field["sourceHeader"] = mapping.get("sourceHeader") or header_label(raw, header_rows, mapping["sourceColumn"] - 1)
            if mapping.get("jsonKey"):
                field["sourceJsonKey"] = mapping["jsonKey"]

    rows = []
    row_end = plan.get("dataEndRow") or len(raw.index)
    row_end = min(row_end, len(raw.index))
    data_start_idx = max(0, plan["dataStartRow"] - 1)

    for raw_idx in range(data_start_idx, row_end):
        values = raw.iloc[raw_idx].tolist()
        if not any(clean_text(value) for value in values):
            continue

        row = {"__id": f"row-{raw_idx + 1}", "__sourceRow": raw_idx + 1, "__approved": True}
        for field in fields:
            mapping = mappings.get(field["key"])
            value = ""
            if mapping:
                col_idx = mapping["sourceColumn"] - 1
                if 0 <= col_idx < len(values):
                    value = values[col_idx]
                    if mapping.get("jsonKey") or mapping.get("jsonPath"):
                        value = value_from_json_cell(value, mapping.get("jsonKey") or mapping.get("jsonPath"))
            row[field["key"]] = normalize_inventory_value(field["key"], value)

        if plan["serverGrain"] in {"server", "vm", "host", "asset", "inventory row"}:
            if not row.get("application_details_number_of_servers") and clean_text(row.get("application_name")):
                row["application_details_number_of_servers"] = 1

        if should_keep_inventory_row(row):
            rows.append(row)

    if not rows:
        raise ValueError("The LLM workbook plan did not produce inventory rows.")

    return {
        "fileName": Path(path).name,
        "sheetName": plan["sheetName"],
        "sheets": excel_file.sheet_names,
        "fields": fields,
        "rows": rows,
        "rateCard": build_rate_card(DEFAULT_SHAPE_KEY),
        "rateCards": all_shape_payloads(),
        "selectedShape": shape_payload(DEFAULT_SHAPE_KEY),
        "metadata": {
            "headerRows": header_rows,
            "dataStartRow": plan["dataStartRow"],
            "dataEndRow": row_end,
            "rowCount": len(rows),
            "columnCount": len(fields),
            "parser": "llm-assisted",
            "confidence": plan.get("confidence", 0),
            "serverGrain": plan.get("serverGrain", "unknown"),
            "extractionNotes": plan.get("notes", []),
        },
    }


def parse_workbook(path):
    llm_warning = None
    try:
        plan, llm_warning = call_llm_workbook_plan(path)
        if plan:
            return parse_workbook_from_plan(path, plan)
    except Exception as exc:
        llm_warning = f"LLM workbook interpretation did not complete; used rule-based spreadsheet parsing. Detail: {exc}"

    parsed = parse_workbook_rule_based(path)
    if llm_warning:
        parsed["llmWarning"] = llm_warning
    return parsed


def find_key(fields, contains, section=None):
    needles = [normalize(item) for item in contains]
    section_norm = normalize(section) if section else ""
    for field in fields:
        label_norm = normalize(field["label"])
        if section_norm and not label_norm.startswith(section_norm):
            continue
        if all(needle in label_norm for needle in needles):
            return field["key"]
    return None


def value_for(row, key, default=0.0):
    return to_number(row.get(key), default) if key else default


def text_for(row, fields, contains, section=None):
    key = find_key(fields, contains, section)
    return clean_text(row.get(key, "")) if key else ""


def rate(sku, rate_card):
    for item in rate_card:
        if item["sku"] == sku:
            return item
    raise KeyError(sku)


def money(value):
    return round(float(value), 2)


def calculate_pricing(fields, rows, shape_key=DEFAULT_SHAPE_KEY):
    selected_shape = shape_payload(shape_key)
    rate_card = selected_shape["rateCard"]
    keys = {
        "app_servers": find_key(fields, ["number of servers"], "Application Details"),
        "app_cpu": find_key(fields, ["number of cpu cores per server"], "Application Details"),
        "app_memory": find_key(fields, ["memory per server"], "Application Details"),
        "app_local_storage": find_key(fields, ["local storage"], "Application Details"),
        "app_shared_storage": find_key(fields, ["shared storage"], "Application Details"),
        "db_servers": find_key(fields, ["number of database servers"], "Database Details"),
        "db_cpu": find_key(fields, ["number of cpu cores per server"], "Database Details"),
        "db_memory": find_key(fields, ["memory per server"], "Database Details"),
        "db_total_allocated": find_key(fields, ["total allocated storage"], "Database Details"),
        "db_total_storage": find_key(fields, ["total storage"], "Database Details"),
        "db_size": find_key(fields, ["database size"], "Database Details"),
    }

    priced_rows = []
    totals = {
        "ocpus": 0.0,
        "memoryGb": 0.0,
        "blockStorageGb": 0.0,
        "fileStorageGb": 0.0,
        "monthly": 0.0,
        "annual": 0.0,
    }

    for row in rows:
        if row.get("__approved") is False:
            continue

        app_servers = value_for(row, keys["app_servers"])
        db_servers = value_for(row, keys["db_servers"])
        app_cpu = value_for(row, keys["app_cpu"])
        db_cpu = value_for(row, keys["db_cpu"])
        app_memory = value_for(row, keys["app_memory"])
        db_memory = value_for(row, keys["db_memory"])
        app_local_storage = value_for(row, keys["app_local_storage"])
        app_shared_storage = value_for(row, keys["app_shared_storage"])

        storage_key = keys["db_total_allocated"] or keys["db_total_storage"] or keys["db_size"]
        db_storage = value_for(row, storage_key)

        app_ocpus = (app_servers * app_cpu) / 2 if app_servers and app_cpu else 0.0
        db_ocpus = (db_servers * db_cpu) / 2 if db_servers and db_cpu else 0.0
        ocpus = app_ocpus + db_ocpus
        memory_gb = (app_servers * app_memory) + (db_servers * db_memory)
        block_storage_gb = (app_servers * app_local_storage) + db_storage
        file_storage_gb = app_servers * app_shared_storage

        line_items = []
        if ocpus:
            rc = rate("B97384", rate_card)
            qty = ocpus * HOURS_PER_MONTH
            line_items.append(
                {
                    "sku": rc["sku"],
                    "description": rc["description"],
                    "quantity": round(qty, 4),
                    "unit": rc["unit"],
                    "rate": rc["rate"],
                    "monthly": money(qty * rc["rate"]),
                    "mapping": "2 vCPU equals 1 OCPU; OCPUs are multiplied by 730 monthly hours.",
                }
            )
        if memory_gb:
            rc = rate("B97385", rate_card)
            qty = memory_gb * HOURS_PER_MONTH
            line_items.append(
                {
                    "sku": rc["sku"],
                    "description": rc["description"],
                    "quantity": round(qty, 4),
                    "unit": rc["unit"],
                    "rate": rc["rate"],
                    "monthly": money(qty * rc["rate"]),
                    "mapping": "Application and database memory are billed as GB-hours.",
                }
            )
        if block_storage_gb:
            rc = rate("B91961", rate_card)
            line_items.append(
                {
                    "sku": rc["sku"],
                    "description": rc["description"],
                    "quantity": round(block_storage_gb, 4),
                    "unit": rc["unit"],
                    "rate": rc["rate"],
                    "monthly": money(block_storage_gb * rc["rate"]),
                    "mapping": "Local VM storage and database allocated storage map to block volume GB-months.",
                }
            )
        if file_storage_gb:
            rc = rate("B89057", rate_card)
            line_items.append(
                {
                    "sku": rc["sku"],
                    "description": rc["description"],
                    "quantity": round(file_storage_gb, 4),
                    "unit": rc["unit"],
                    "rate": rc["rate"],
                    "monthly": money(file_storage_gb * rc["rate"]),
                    "mapping": "Shared storage maps to file storage GB-months.",
                }
            )

        monthly = money(sum(item["monthly"] for item in line_items))
        annual = money(monthly * 12)
        name = text_for(row, fields, ["application name"]) or text_for(row, fields, ["database name"]) or row["__id"]
        environment = text_for(row, fields, ["environment"])

        priced = {
            "rowId": row["__id"],
            "sourceRow": row.get("__sourceRow"),
            "name": name,
            "environment": environment,
            "specs": {
                "applicationServers": app_servers,
                "databaseServers": db_servers,
                "vcpus": round((app_servers * app_cpu) + (db_servers * db_cpu), 4),
                "ocpus": round(ocpus, 4),
                "memoryGb": round(memory_gb, 4),
                "blockStorageGb": round(block_storage_gb, 4),
                "fileStorageGb": round(file_storage_gb, 4),
            },
            "lineItems": line_items,
            "monthly": monthly,
            "annual": annual,
            "assumptions": [
                "2 vCPU = 1 OCPU.",
                "OCPU and memory prices are converted to monthly estimates using 730 hours.",
                "Local VM storage plus database allocated storage are treated as block volume storage.",
                "Application shared storage is treated as file storage.",
            ],
        }
        priced_rows.append(priced)

        for key in ["ocpus", "memoryGb", "blockStorageGb", "fileStorageGb"]:
            totals[key] += priced["specs"][key]
        totals["monthly"] += monthly
        totals["annual"] += annual

    for key in totals:
        totals[key] = money(totals[key]) if key in {"monthly", "annual"} else round(totals[key], 4)

    return {
        "engine": "local-rule-engine",
        "hoursPerMonth": HOURS_PER_MONTH,
        "selectedShape": selected_shape,
        "rateCard": rate_card,
        "rateCards": all_shape_payloads(),
        "totals": totals,
        "rows": priced_rows,
        "fieldMap": keys,
    }


def extract_response_text(payload):
    if "output_text" in payload:
        return payload["output_text"]
    chunks = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                chunks.append(content.get("text", ""))
    return "\n".join(chunks)


def parse_jsonish(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


def compact_llm_summary(pricing):
    sample_rows = []
    for row in pricing["rows"][:12]:
        sample_rows.append(
            {
                "rowId": row["rowId"],
                "name": row["name"],
                "environment": row["environment"],
                "specs": row["specs"],
                "mappedSkus": [item["sku"] for item in row["lineItems"]],
                "monthly": row["monthly"],
            }
        )
    return {
        "rowCount": len(pricing["rows"]),
        "totals": pricing["totals"],
        "sampleRows": sample_rows,
        "selectedShape": pricing.get("selectedShape", shape_payload(DEFAULT_SHAPE_KEY)),
        "rateCard": pricing.get("rateCard", build_rate_card(DEFAULT_SHAPE_KEY)),
        "localMappingRules": [
            {
                "sku": "B97384",
                "rule": "2 vCPU = 1 OCPU; OCPU-hours = OCPU x 730 using the selected flex shape rate.",
            },
            {
                "sku": "B97385",
                "rule": "Memory GB-hours = memory GB x 730 using the selected flex shape rate.",
            },
            {"sku": "B91961", "rule": "VM local storage and database allocated storage use block volume GB-month."},
            {"sku": "B89057", "rule": "Shared/NAS storage uses file storage GB-month."},
        ],
    }


def describe_http_error(exc):
    payload = exc.read().decode("utf-8", errors="replace")
    try:
        error = json.loads(payload).get("error", {})
        parts = [str(exc)]
        if error.get("type"):
            parts.append(f"type={error.get('type')}")
        if error.get("code"):
            parts.append(f"code={error.get('code')}")
        if error.get("message"):
            parts.append(error.get("message"))
        return " | ".join(parts)
    except json.JSONDecodeError:
        return f"{exc} | {payload[:300]}"


def call_openai_json(system_content, user_payload, max_output_tokens=1600, timeout=45):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "OPENAI_API_KEY is not set."

    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    body = {
        "model": model,
        "max_output_tokens": max_output_tokens,
        "input": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = extract_response_text(payload)
        return parse_jsonish(text), None
    except urllib.error.HTTPError as exc:
        return None, describe_http_error(exc)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        return None, str(exc)


def call_llm_workbook_plan(path):
    digest = workbook_digest(path)
    system = (
        "You interpret Excel infrastructure inventory workbooks for an Oracle Cloud Infrastructure intake app. "
        "Given workbook sheet samples, identify the sheet and row range that contain servers, applications, VMs, "
        "hosts, databases, or other infrastructure inventory. Return compact JSON only. "
        "Use 1-based row and column numbers. Do not invent missing columns. "
        "Map source columns to the provided canonical fields when the source appears equivalent, even if headings use "
        "terms like hostname, VM, instance, vCPU, RAM, disk, storage, OS, platform, environment, or application. "
        "Some workbooks, especially AWS billing or inventory exports, store tags as JSON strings in a cell. "
        "When a JSON/tag column contains useful keys, map it with jsonKey. For example, map tag key 'Name' or 'appId' "
        "to application_name, 'environment' to environment, and 'os' to application_details_operating_system. "
        "For application_details, prefer resource-specific values such as tag key 'appId', 'role', 'owner', resourceId, "
        "or private IP; avoid accountId or region unless nothing resource-specific exists. "
        "Do not map the full JSON blob as plain text unless no useful key exists. "
        "If each row is one server/VM/host, set serverGrain to 'server'. If each row is an application/workload "
        "that may represent many servers, set serverGrain to 'application'. "
        "Return this shape: {sheetName, headerRows, dataStartRow, dataEndRow, serverGrain, confidence, "
        "columnMappings:[{canonicalKey, sourceColumn, sourceHeader, jsonKey, confidence, transform}], notes:[string]}. "
        "For transform, briefly say unit conversions needed, such as TB to GB."
    )
    payload = {
        "canonicalFields": canonical_field_prompt(),
        "workbook": digest,
    }
    plan, warning = call_openai_json(system, payload, max_output_tokens=2800, timeout=45)
    if warning:
        return None, f"LLM workbook interpretation did not complete; used rule-based spreadsheet parsing. Detail: {warning}"
    excel_file = pd.ExcelFile(path)
    normalized = normalize_workbook_plan(plan, excel_file)
    if not normalized:
        return None, "LLM workbook interpretation did not identify a usable inventory table; used rule-based spreadsheet parsing."
    return normalized, None


def call_llm_mapping(pricing):
    prompt = compact_llm_summary(pricing)
    system = (
        "You are an Oracle Cloud Infrastructure pricing mapper. "
        "Validate whether the SKU mapping rules and selected OCI flexible compute shape are appropriate "
        "for an uploaded infrastructure inventory. "
        "Return compact JSON only with keys globalAssumptions, mappingRules, and reviewNotes. "
        "Do not recalculate every row; validate the rules and call out mapping risks."
    )
    payload, warning = call_openai_json(system, prompt, max_output_tokens=1200, timeout=45)
    if warning:
        if warning == "OPENAI_API_KEY is not set.":
            return None, "OPENAI_API_KEY is not set; used deterministic SKU mapping."
        return None, f"LLM call did not complete; used deterministic SKU mapping. Detail: {warning}"
    return payload, None


def enrich_with_llm(pricing, llm_payload):
    if not llm_payload:
        return pricing
    mapping_by_row = {item.get("rowId"): item for item in llm_payload.get("mappings", [])}
    for row in pricing["rows"]:
        match = mapping_by_row.get(row["rowId"])
        if not match:
            continue
        row["llmMappedSkus"] = match.get("mappedSkus", [])
        row["llmAssumptions"] = match.get("assumptions", [])
    pricing["engine"] = "llm-assisted"
    pricing["globalAssumptions"] = llm_payload.get("globalAssumptions", [])
    pricing["mappingRules"] = llm_payload.get("mappingRules", [])
    pricing["reviewNotes"] = llm_payload.get("reviewNotes", [])
    return pricing


class IntakeHandler(BaseHTTPRequestHandler):
    server_version = "OCIIntake/1.0"

    def send_json(self, status, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_error_json(self, status, message):
        self.send_json(status, {"error": message})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/health":
            self.send_json(
                200,
                {
                    "ok": True,
                    "rateCard": build_rate_card(DEFAULT_SHAPE_KEY),
                    "rateCards": all_shape_payloads(),
                    "selectedShape": shape_payload(DEFAULT_SHAPE_KEY),
                },
            )
            return
        if path == "/":
            self.serve_file(STATIC_DIR / "index.html")
            return
        if path.startswith("/static/"):
            target = (STATIC_DIR / path.removeprefix("/static/")).resolve()
            if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
                self.send_error_json(403, "Invalid static path.")
                return
            self.serve_file(target)
            return
        self.send_error_json(404, "Not found.")

    def serve_file(self, path):
        if not path.exists() or not path.is_file():
            self.send_error_json(404, "File not found.")
            return
        content = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/upload":
            self.handle_upload()
            return
        if parsed.path == "/api/price":
            self.handle_price()
            return
        self.send_error_json(404, "Not found.")

    def handle_upload(self):
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            self.send_error_json(400, "Upload must be multipart/form-data.")
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        if "file" not in form:
            self.send_error_json(400, "Missing file field.")
            return

        file_item = form["file"]
        filename = clean_text(getattr(file_item, "filename", "")) or "upload.xlsx"
        if not filename.lower().endswith((".xlsx", ".xls")):
            self.send_error_json(400, "Please upload an Excel workbook.")
            return

        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)
        saved_path = UPLOAD_DIR / f"{int(time.time())}_{safe_name}"
        saved_path.write_bytes(file_item.file.read())

        try:
            parsed = parse_workbook(saved_path)
            parsed["uploadedPath"] = str(saved_path)
            self.send_json(200, parsed)
        except Exception as exc:
            self.send_error_json(500, f"Could not parse workbook: {exc}")

    def handle_price(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            fields = payload.get("fields", [])
            rows = payload.get("rows", [])
            shape_key = payload.get("shape") or DEFAULT_SHAPE_KEY
            if shape_key not in SHAPE_LOOKUP:
                self.send_error_json(400, f"Unsupported OCI flex shape: {shape_key}")
                return
            if not fields or not rows:
                self.send_error_json(400, "Pricing requires fields and rows.")
                return
            pricing = calculate_pricing(fields, rows, shape_key)
            llm_payload, llm_warning = call_llm_mapping(pricing)
            pricing = enrich_with_llm(pricing, llm_payload)
            if llm_warning:
                pricing["llmWarning"] = llm_warning
            self.send_json(200, pricing)
        except Exception as exc:
            self.send_error_json(500, f"Could not price inventory: {exc}")

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), IntakeHandler)
    print(f"OCI Intake app running at http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
