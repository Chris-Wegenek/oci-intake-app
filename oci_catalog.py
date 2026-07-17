"""Searchable OCI service catalog for the "Add OCI services" panel.

The results page lets a user look up OCI services (Networking, Storage, PaaS, ...), fill in
sizing, and add them to the BOM — the way Oracle's own Cost Estimator works. This module is
the catalog behind that search.

Two layers:
  1. CURATED services — the things a solutions engineer actually adds to a BOM, each with a
     verified rate and explicit sizing fields (GB, count, ports, OCPU, ...). Rates are the
     app's own price data (data/oci_price_list.json / oci_service_prices.json), NOT invented.
  2. RAW search fallback — full-text over all 629 price-list SKUs so nothing is unreachable;
     these add as a plain quantity x unit rate.

Every entry declares a `basis` so the monthly cost is computed one way everywhere:
    hour   -> rate * qty * HOURS_PER_MONTH      (per-OCPU-hour, per-port-hour, ...)
    month  -> rate * qty                        (per-GB-month, per-instance-month, ...)
    op     -> rate * qty                        (per-1M-calls etc.; qty is in the SKU's unit)
    once   -> rate * qty                        (one-off; shown but not multiplied by hours)
"""

import json
import re
from pathlib import Path

HOURS_PER_MONTH = 730
DATA = Path(__file__).resolve().parent / "data"


def _price_list():
    items = json.loads((DATA / "oci_price_list.json").read_text()).get("items", [])
    return {it["sku"]: it for it in items if it.get("sku")}


def _service_prices():
    return json.loads((DATA / "oci_service_prices.json").read_text()).get("services", {})


_PRICES = _price_list()
_SVC = _service_prices()


def _rate(sku, fallback=None):
    """PAYG rate for a SKU straight from the app's price list.

    Careful: the raw price list's `payg` is sometimes a *bundle factor* (e.g. a Load
    Balancer row lists 13 for "13 Mbps", API Gateway lists 1,000,000 for "per 1M calls"),
    not a dollar rate. For anything with a verified per-unit rate, use `_svc_rate` instead.
    """
    it = _PRICES.get(sku)
    if it and isinstance(it.get("payg"), (int, float)):
        return float(it["payg"])
    return fallback


def _svc_rate(name, key="rate", fallback=None):
    """Verified per-unit rate from oci_service_prices.json (the clean, hand-checked file)."""
    svc = _SVC.get(name) or {}
    v = svc.get(key)
    return float(v) if isinstance(v, (int, float)) else fallback


def _sf(key, label, unit, default=0, step=1, min_=0):
    """One sizing field the user fills in."""
    return {"key": key, "label": label, "unit": unit, "default": default,
            "step": step, "min": min_}


# --- curated, fillable services -------------------------------------------------------------
# group order mirrors data/service_comp_list.json so the chips read like Oracle's console.
GROUPS = ["Compute", "Storage", "Networking", "Database", "Security",
          "Observability", "AI & Machine Learning", "Licensing", "Other Services"]

# Names/keywords that mark a line as 3rd-party licensing (never OCI-discounted).
_THIRD_PARTY_TERMS = ("windows", "sql server", "license", "licence", "byol")


def _curated():
    """Curated, fillable services. Rates come from oci_service_prices.json (verified
    per-unit) where available, else the price list by SKU. Free tiers are declared so the
    cost math matches the app's own free-pool handling."""
    C = []

    def add(id, group, name, sku, rate, unit, basis, fields, note="", free=None,
            third_party=False):
        C.append({"id": id, "group": group, "name": name, "sku": sku,
                  "rate": rate, "unit": unit, "basis": basis, "fields": fields,
                  "note": note, "free": free or {}, "source": "curated",
                  # 3rd-party licensing (Windows, SQL Server, ...) is NOT eligible for the
                  # OCI discount; native OCI services are.
                  "thirdParty": third_party})

    # ---- Storage ----
    add("block", "Storage", "Block Volume (Balanced)", "B91961",
        _svc_rate("OCI Block Volumes", fallback=0.0255), "GB / month", "month",
        [_sf("gb", "Capacity", "GB", 1024, 128),
         _sf("vpus", "Performance (VPUs/GB)", "VPU", 10, 10)],
        "Balanced = 10 VPUs/GB. Storage + performance units both priced.")
    add("object", "Storage", "Object Storage — Standard", "B86080",
        _svc_rate("OCI Object Storage", fallback=0.0255), "GB / month", "month",
        [_sf("gb", "Capacity", "GB", 1024, 128)])
    add("file", "Storage", "File Storage (NFS)", "B89057",
        _svc_rate("OCI File Storage", fallback=0.30), "GB / month", "month",
        [_sf("gb", "Capacity", "GB", 1024, 128)])
    add("archive", "Storage", "Archive Storage", "B89145",
        _svc_rate("OCI Archive Storage", fallback=0.003), "GB / month", "month",
        [_sf("gb", "Capacity", "GB", 10240, 1024)])

    # ---- Networking ----
    add("lb", "Networking", "Flexible Load Balancer", "B93031",
        _svc_rate("OCI Load Balancer", fallback=0.0113), "LB / hour", "hour",
        [_sf("count", "Load balancers", "LB", 1, 1, 1)],
        "Per load-balancer-hour; bandwidth/LCU usage is included free on OCI.")
    add("egress", "Networking", "Outbound Data Transfer", "B87062",
        _svc_rate("OCI Outbound Data Transfer", fallback=0.0085), "GB / month", "month",
        [_sf("gb", "Egress", "GB", 0, 1024)],
        "First 10 TB/region/month is free.", free={"gb": 10240})
    add("fastconnect", "Networking", "FastConnect port (10 Gbps)", "B?-FASTCONNECT",
        _svc_rate("OCI FastConnect", "speedRates", fallback={}).get("10G", 1.275)
        if isinstance(_svc_rate("OCI FastConnect", "speedRates", fallback={}), dict) else 1.275,
        "port / hour", "hour", [_sf("ports", "Ports", "port", 1, 1, 1)],
        "Per provisioned port-hour; FastConnect traffic is not metered.")
    add("dns", "Networking", "DNS (metered queries)", "B88516",
        _svc_rate("OCI DNS", fallback=0.85), "per 1M queries", "op",
        [_sf("millions", "Queries per month", "million", 1, 1)],
        "Hosted zones and intra-VCN queries are free.")

    # ---- Database (PaaS) ----
    # Autonomous DB rates are the customer-supplied OCI price-list values (these SKUs aren't
    # in oci_price_list.json). ECPU is billed per ECPU-hour; storage per GB-month.
    add("adb_atp", "Database", "Autonomous Transaction Processing — ECPU", "B95702", 0.336,
        "ECPU / hour", "hour", [_sf("ecpu", "ECPUs", "ECPU", 2, 1, 1)],
        "Autonomous AI Transaction Processing serverless compute; storage billed separately.")
    add("adb_lakehouse", "Database", "Autonomous AI Lakehouse — ECPU", "B95701", 0.336,
        "ECPU / hour", "hour", [_sf("ecpu", "ECPUs", "ECPU", 2, 1, 1)],
        "Autonomous AI Lakehouse serverless compute; storage billed separately.")
    add("adb_store_tp", "Database", "Autonomous DB storage (Transaction Processing)", "B95706",
        0.1953, "GB / month", "month", [_sf("gb", "Storage", "GB", 1024, 128)])
    add("adb_store", "Database", "Autonomous DB storage", "B95754", 0.0299,
        "GB / month", "month", [_sf("gb", "Storage", "GB", 1024, 128)])
    add("mysql", "Database", "MySQL Database — storage", "B92483", _rate("B92483", 0.04),
        "GB / month", "month", [_sf("gb", "Storage", "GB", 100, 50)])
    add("pg", "Database", "PostgreSQL — OCPU", "B99060", _rate("B99060", 0.098),
        "OCPU / hour", "hour", [_sf("ocpu", "OCPUs", "OCPU", 2, 1, 1)])
    add("dbbackup", "Database", "Database Backup (to Object Storage)", "B90230",
        _svc_rate("OCI Database Backup", fallback=0.0051), "GB / month", "month",
        [_sf("gb", "Backup capacity", "GB", 500, 100)])
    add("recovery", "Database", "Autonomous Recovery Service", "B95240", 0.0306,
        "GB / month", "month", [_sf("gb", "Protected capacity", "GB", 100, 50)],
        "Oracle Database Autonomous Recovery Service — virtualized GB per month.")

    # ---- Security ----
    add("waf", "Security", "Web Application Firewall", "B94277",
        _svc_rate("OCI Web Application Firewall", fallback=0.60), "per 1M requests", "op",
        [_sf("millions", "Requests per month", "million", 10, 1)],
        "First instance + first 10M requests/month are free; then $0.60 per 1M.",
        free={"millions": 10})
    add("kms", "Security", "Vault — HSM key versions", "B92092", _rate("B92092", 1.75),
        "key version / hour", "hour", [_sf("keys", "Protected key versions", "key", 1, 1, 1)])

    # ---- Observability / Other ----
    add("logging", "Observability", "Logging (ingest)", "B92707",
        _svc_rate("OCI Logging", fallback=0.05), "GB / month", "month",
        [_sf("gb", "Log data", "GB", 0, 10)],
        "First 10 GB/month is free.", free={"gb": 10})
    add("desktops", "Other Services", "Secure Desktops", "B95518",
        _svc_rate("OCI Secure Desktops", fallback=20.0), "desktop / month", "month",
        [_sf("count", "Desktops", "desktop", 10, 1, 1)])

    # ---- 3rd-party licensing (NOT discounted) ----
    add("winlic", "Licensing", "Windows Server license", "B88318", _rate("B88318", 0.092),
        "OCPU / hour", "hour", [_sf("ocpu", "Licensed OCPUs", "OCPU", 2, 1, 1)],
        "3rd-party Microsoft licensing — excluded from the OCI discount.", third_party=True)
    add("sqllic", "Licensing", "SQL Server (Enterprise) license", "B88319",
        _rate("B88319", 0.5137), "OCPU / hour", "hour",
        [_sf("ocpu", "Licensed OCPUs", "OCPU", 2, 1, 1)],
        "3rd-party Microsoft licensing — excluded from the OCI discount.", third_party=True)

    return [c for c in C if isinstance(c["rate"], (int, float))]


CURATED = _curated()


# --- monthly cost -----------------------------------------------------------------------------
def line_cost(entry, values, hours=HOURS_PER_MONTH):
    """Monthly USD for a filled-in catalog entry. Deterministic; mirrors the app's math,
    including free tiers (egress 10 TB, WAF 10M requests, Logging 10 GB).

    `hours` is the app's hours-per-month setting — anything billed per hour (ECPU, OCPU,
    load-balancer-hour, port-hour) multiplies by it, so the catalog follows the same hours
    the compute rows use rather than a static 730.
    """
    rate = float(entry.get("rate") or 0)
    basis = entry.get("basis", "month")
    free = entry.get("free") or {}
    hours = float(hours or HOURS_PER_MONTH)
    v = {f["key"]: float(values.get(f["key"], f.get("default", 0)) or 0) for f in entry["fields"]}

    # Block volume: capacity + performance units, two SKUs.
    if entry["id"] == "block":
        gb, vpus = v.get("gb", 0), v.get("vpus", 10)
        store = gb * _svc_rate("OCI Block Volumes", fallback=0.0255)
        perf = gb * vpus * (_SVC.get("OCI Block Volumes", {}).get("perfUnitsRate") or 0.0017)
        return round(store + perf, 2)

    # Billed quantity = the single sizing field (all remaining curated entries are single-field),
    # minus any free allowance on that field.
    fkey = entry["fields"][0]["key"] if entry["fields"] else None
    qty = v.get(fkey, 0) if fkey else 0
    if fkey in free:
        qty = max(0.0, qty - free[fkey])

    if basis == "hour":
        return round(rate * qty * hours, 2)
    return round(rate * qty, 2)          # month / op


# --- search -----------------------------------------------------------------------------------
def _norm(s):
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).strip()


def _raw_matches(q, limit=25):
    """Full-text fallback over the whole price list for anything not curated."""
    qn = _norm(q)
    if not qn:
        return []
    terms = qn.split()
    out = []
    for sku, it in _PRICES.items():
        rate = it.get("payg")
        if not isinstance(rate, (int, float)) or rate <= 0:
            continue
        hay = _norm(f"{it.get('desc','')} {it.get('metric','')} {sku}")
        if all(t in hay for t in terms):
            metric = (it.get("metric") or "").strip()
            ml = metric.lower()
            # Rates quoted per OCPU/ECPU/GPU/vCPU-hour bill hourly; the rest per month.
            basis = "hour" if ("per hour" in ml or "ecpu" in ml or "ocpu" in ml
                               or "gpu per" in ml or "core per hour" in ml) else "month"
            unit = re.sub(r"\s+", " ", metric)[:40] or "unit"
            third = any(t in hay for t in _THIRD_PARTY_TERMS)
            out.append({
                "id": f"raw:{sku}", "group": "Licensing" if third else "Other Services",
                "name": re.sub(r"\s+", " ", it.get("desc", sku))[:70],
                "sku": sku, "rate": float(rate), "unit": unit, "basis": basis,
                "fields": [_sf("qty", "Quantity", unit, 1, 1)],
                "note": "Raw price-list SKU.", "source": "raw", "thirdParty": third,
            })
    out.sort(key=lambda e: len(e["name"]))
    return out[:limit]


def search(query="", group=""):
    """Return catalog entries matching a text query and/or a category group."""
    q, g = _norm(query), (group or "").strip()
    results = []
    for e in CURATED:
        if g and e["group"] != g:
            continue
        if q:
            hay = _norm(f"{e['name']} {e['group']} {e['sku']} {e['note']}")
            if not all(t in hay for t in q.split()):
                continue
        results.append(e)
    # Only reach into the raw list on an explicit text search, so browsing a category stays clean.
    if q and not g:
        seen = {e["sku"] for e in results}
        results += [r for r in _raw_matches(query) if r["sku"] not in seen]
    return results


def _entry_by_id(cid):
    for e in CURATED:
        if e["id"] == cid:
            return e
    return None


def price_extras(extra_services, hours=HOURS_PER_MONTH):
    """Re-price the services the user added, authoritatively, from the catalog — never
    trusting the client's number. `hours` is the app's hours-per-month setting so per-hour
    services follow it. Returns a clean list the exporter can consume:
        [{name, group, sku, unit, monthly, sizing}]  plus a total.
    """
    hours = float(hours or HOURS_PER_MONTH)
    out, total = [], 0.0
    for s in (extra_services or []):
        cid = s.get("catalogId") or s.get("id")
        entry = _entry_by_id(cid)
        values = s.get("values") or {}
        if entry:
            monthly = line_cost(entry, values, hours)
            name, group, sku, unit = entry["name"], entry["group"], entry["sku"], entry["unit"]
            fields = entry["fields"]
            third = bool(entry.get("thirdParty"))
        else:
            # A raw price-list SKU (raw:<sku>): basis carried on the client record.
            rate = float(s.get("rate") or 0)
            qty = float((values.get("qty") if values else 0) or 0)
            monthly = round(rate * qty * (hours if s.get("basis") == "hour" else 1), 2)
            name = s.get("name", cid or "Service")
            group = s.get("group", "Other Services")
            sku = s.get("sku", "")
            unit = s.get("unit", "unit")
            fields = s.get("fields") or []
            third = bool(s.get("thirdParty")) or group == "Licensing"
        sizing = " · ".join(
            f"{values.get(f['key'], f.get('default', 0))} {f.get('unit', '')}".strip()
            for f in fields
        )
        out.append({"name": name, "group": group, "sku": sku, "unit": unit,
                    "monthly": round(monthly, 2), "sizing": sizing, "thirdParty": third})
        total += monthly
    return out, round(total, 2)


# Which Pricing Overview line each catalog group rolls into (all sit inside SUM(B13:B20)).
GROUP_TO_OVERVIEW_ROW = {
    "Storage": 16, "Database": 16, "Observability": 16,
    "AI & Machine Learning": 16, "Other Services": 16, "Compute": 16,
    "Networking": 18,
    "Security": 19,
    "Licensing": 21,        # Pricing Overview row 21 = "3rd Party Licensing"
}


def groups_with_counts():
    counts = {}
    for e in CURATED:
        counts[e["group"]] = counts.get(e["group"], 0) + 1
    return [{"group": g, "count": counts.get(g, 0)} for g in GROUPS if counts.get(g)]
