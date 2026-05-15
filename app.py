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

RATE_CARD = [
    {
        "sku": "B97384",
        "description": "OCPU-hr rate (Compute)",
        "unit": "OCPU-hour",
        "rate": 0.0138,
        "notes": "OCPU-hours x 730 hrs/mo",
    },
    {
        "sku": "B97385",
        "description": "Memory GB-hr rate",
        "unit": "GB-hour",
        "rate": 0.0108,
        "notes": "GB-hours x 730 hrs/mo",
    },
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


def parse_workbook(path):
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
        "rateCard": RATE_CARD,
        "metadata": {
            "headerRow": header_row + 1,
            "groupRow": group_row + 1,
            "dataStartRow": data_start + 1,
            "rowCount": len(rows),
            "columnCount": len(fields),
        },
    }


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


def rate(sku):
    for item in RATE_CARD:
        if item["sku"] == sku:
            return item
    raise KeyError(sku)


def money(value):
    return round(float(value), 2)


def calculate_pricing(fields, rows):
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
            rc = rate("B97384")
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
            rc = rate("B97385")
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
            rc = rate("B91961")
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
            rc = rate("B89057")
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
        "rateCard": RATE_CARD,
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
        "rateCard": RATE_CARD,
        "localMappingRules": [
            {"sku": "B97384", "rule": "2 vCPU = 1 OCPU; OCPU-hours = OCPU x 730."},
            {"sku": "B97385", "rule": "Memory GB-hours = memory GB x 730."},
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


def call_llm_mapping(pricing):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "OPENAI_API_KEY is not set; used deterministic SKU mapping."

    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    prompt = compact_llm_summary(pricing)
    body = {
        "model": model,
        "max_output_tokens": 1200,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are an Oracle Cloud Infrastructure pricing mapper. "
                    "Validate whether the SKU mapping rules are appropriate for an uploaded infrastructure inventory. "
                    "Return compact JSON only with keys globalAssumptions, mappingRules, and reviewNotes. "
                    "Do not recalculate every row; validate the rules and call out mapping risks."
                ),
            },
            {"role": "user", "content": json.dumps(prompt)},
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
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = extract_response_text(payload)
        return parse_jsonish(text), None
    except urllib.error.HTTPError as exc:
        return None, f"LLM call did not complete; used deterministic SKU mapping. Detail: {describe_http_error(exc)}"
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        return None, f"LLM call did not complete; used deterministic SKU mapping. Detail: {exc}"


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
            self.send_json(200, {"ok": True, "rateCard": RATE_CARD})
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
            if not fields or not rows:
                self.send_error_json(400, "Pricing requires fields and rows.")
                return
            pricing = calculate_pricing(fields, rows)
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
