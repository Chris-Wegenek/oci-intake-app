"""Searchable OCI service catalog for the "Add OCI services" panel.

The results page lets a user look up OCI services (Networking, Storage, PaaS, ...), fill in
sizing, and add them to the BOM - the way Oracle's own Cost Estimator works. This module is
the catalog behind that search.

Two layers:
  1. CURATED services - the things a solutions engineer actually adds to a BOM, each with a
     verified rate and explicit sizing fields (GB, count, ports, OCPU, ...). Rates are the
     app's own price data (data/oci_price_list.json / oci_service_prices.json), NOT invented.
  2. RAW search fallback - full-text over all 629 price-list SKUs so nothing is unreachable;
     these add as a plain quantity x unit rate.

Every entry declares a `basis` so the monthly cost is computed one way everywhere:
    hour   -> rate * qty * HOURS_PER_MONTH      (per-OCPU-hour, per-port-hour, ...)
    month  -> rate * qty                        (per-GB-month, per-instance-month, ...)
    op     -> rate * qty                        (per-1M-calls etc.; qty is in the SKU's unit)
    once   -> rate * qty                        (one-off; shown but not multiplied by hours)
"""

import json
import math
import re
from pathlib import Path

HOURS_PER_MONTH = 730

# Autonomous AI Database (serverless) rates - customer-supplied OCI price-list values.
ADB_ECPU_RATE = 0.336       # per ECPU-hour (B95702 ATP / B95701 ADW; B95713/B95712 dedicated)
ADB_STORAGE_ATP = 0.1953    # ATP / AJD / APEX database storage per GB-month (B95706)
ADB_STORAGE_ADW = 0.0299    # ADW / Lakehouse database storage per GB-month (B95754)
ADB_BACKUP_RATE = 0.0299    # serverless Autonomous DB backup storage per GB-month (B95754)
# Dedicated (Exadata Cloud Infrastructure) - Hosted Environment per hour, X11M.
ADB_EXA_DB_SERVER = 6.3014      # Exadata Database Server per hour (B112666)
ADB_EXA_STORAGE_SERVER = 5.4795  # Exadata Storage Server per hour (B112667)
ADB_OBJ_BACKUP = 0.0255     # dedicated backup -> Object Storage per GB-month (B91628)
ADB_OBJ_BACKUP_FREE = 10    # first 10 GB of object-storage backup is free

# Oracle Integration Cloud (OIC) - per 5,000-messages/hour "message pack" per hour.
OIC_STD_RATE = 0.6452       # Standard edition, per message-pack-hour (B89639)
OIC_ENT_RATE = 1.2903       # Enterprise edition, per message-pack-hour (B109559)
OIC_MSG_PER_PACK_HR = 5000  # 1 pack = 5,000 messages/hour (payload <=50KB each)
# Pack sizing:
#   surge   -> ceil(peak daily volume / (24 hrs * 5,000))   [OCI estimator "surge" path]
#   monthly -> ceil(total messages per month / (hours * 5,000))   (e.g. 730*5,000 = 3.65M/pack)


# MySQL HeatWave Database Service - customer-supplied OCI price-list values.
MYSQL_ECPU_RATE = 0.0366     # MySQL Database ECPU per hour (B108030)
MYSQL_STORAGE_RATE = 0.04    # MySQL storage / backup / inter-region egress per GB-mo (B92426/B92483/B109169)
MYSQL_HW_RATE = 0.011        # HeatWave capacity per hour (B96626)
MYSQL_HW_STORAGE_RATE = 0.02  # HeatWave storage per GB-mo (B96625)

# OCI Database with PostgreSQL - customer-supplied OCI price-list values.
PG_MANAGED_OCPU_RATE = 0.098   # managed PostgreSQL OCPU per hour (B99060)
PG_STORAGE_RATE = 0.072        # database-optimized storage per GB-mo (B99062)
PG_COMPUTE_OCPU_RATE = 0.03    # underlying AMD E5 compute OCPU per hour (B97384)
PG_COMPUTE_MEM_RATE = 0.002    # underlying AMD E5 compute memory per GB-hr (B97385)
PG_COMPUTE_OCPU_RATE_INTEL = 0.04    # Intel X9 compute OCPU per hour
PG_COMPUTE_MEM_RATE_INTEL = 0.0015   # Intel X9 compute memory per GB-hr
PG_VPU_RATE = 0.0017           # block-volume performance units per GB-mo (B91962)

# Object Storage - tiered with free allowances.
OBJ_STORAGE_RATE = 0.0255          # Standard, per GB-month after free tier (B91628)
OBJ_STORAGE_FREE_GB = 10           # first 10 GB/month free
OBJ_IA_STORAGE_RATE = 0.0100       # Infrequent Access, per GB-month (B93000)
OBJ_IA_RETRIEVAL_RATE = 0.0100     # Infrequent Access, per GB retrieved (B93001)
OBJ_IA_RETRIEVAL_FREE_GB = 10      # first 10 GB retrieved/month free
ARCHIVE_STORAGE_RATE = 0.0026      # Archive, per GB-month after free tier (B91633)
OBJ_REQUEST_RATE = 0.0034          # per 10,000 requests after free tier (B91627)
OBJ_REQUEST_FREE_UNITS = 5         # first 50,000 requests (5 units of 10k) free

# Web Application Firewall - instance + request tiers with free allowances.
WAF_INSTANCE_RATE = 5.00       # per WAF instance per month after the first (B94579)
WAF_INSTANCE_FREE = 1          # first instance free
WAF_REQUEST_RATE = 0.60        # per 1,000,000 incoming requests after the free tier (B94277)
WAF_REQUEST_FREE = 10          # first 10,000,000 requests (10 units of 1M) free

# Key Management / Vault. Software key versions (B92092) are free; the paid options:
KMS_VAULT_RATE = 3.724     # Virtual Private Vault per hour (B90328)
KMS_EXTERNAL_RATE = 3.00   # External Key Management per key version-month (B98100)
KMS_HSM_RATE = 1.75        # Dedicated Key Management HSM partition per hour (B99597, min 3)

# OCI Full Stack Disaster Recovery, metered per member per hour, summed across the
# primary AND standby protection groups. Compute + Database member OCPUs bill at the OCPU
# rate; Database member ECPUs at the ECPU rate; OIC message packs at the 5K-msg rate.
FSDR_OCPU_RATE = 0.0128     # OCPU per hour (B95485)
FSDR_ECPU_RATE = 0.0032     # ECPU per hour (B110274)
FSDR_OIC_RATE = 0.192       # 5K messages per hour, per OIC message pack (B112110)

# Microsoft SQL Server license-included (OCI marketplace compute image), per OCPU-hour.
SQL_ENT_RATE = 1.47        # SQL Server Enterprise (B91372)
SQL_STD_RATE = 0.37        # SQL Server Standard (B91373)
# SQL Server Express is free ($0).

# Secure Desktops - desktop fee + underlying E6 compute + block volumes (boot + optional).
DESKTOP_UNIT_RATE = 20.00      # Secure Desktop per month (B95518)
DESKTOP_OCPU_RATE = 0.03       # E6 Standard compute OCPU per hour (B111129)
DESKTOP_MEM_RATE = 0.002       # E6 Standard compute memory per GB-hr (B111130)
DESKTOP_BLOCK_RATE = 0.0255    # Block Volume storage per GB-mo (B91961)
DESKTOP_VPU_RATE = 0.0017      # Block Volume performance units per GB-mo (B91962)
# Windows-BYOL-on-DVH mode: desktops run on Dedicated VM Host(s) (DVH.Standard.E4.128).
DESKTOP_E4_OCPU_RATE = 0.025   # E4 compute OCPU per hour (B93113)
DESKTOP_E4_MEM_RATE = 0.0015   # E4 compute memory per GB-hr (B93114)
DVH_HOST_OCPU = 128            # DVH.Standard.E4.128 total OCPUs (billed)
DVH_HOST_MEM = 2048            # DVH.Standard.E4.128 total memory GB (billed)
DVH_AVAIL_OCPU = 124           # OCPUs available for desktops per host (128 - 4 reserved)


def oic_packs(values, hours):
    """Approximate message packs from the sizing inputs (surge peak daily volume wins,
    else total monthly messages, else the directly-entered pack count)."""
    import math
    peak = float((values.get("peakday") if values else 0) or 0)
    monthly = float((values.get("monthlymsgs") if values else 0) or 0)
    if peak > 0:
        return math.ceil(peak / (24 * OIC_MSG_PER_PACK_HR))
    if monthly > 0:
        return math.ceil(monthly / (float(hours or HOURS_PER_MONTH) * OIC_MSG_PER_PACK_HR))
    return float((values.get("packs") if values else 0) or 0)
DATA = Path(__file__).resolve().parent / "data"


def _price_list():
    items = json.loads((DATA / "oci_price_list.json").read_text()).get("items", [])
    return {it["sku"]: it for it in items if it.get("sku")}


def _service_prices():
    return json.loads((DATA / "oci_service_prices.json").read_text()).get("services", {})


_PRICES = _price_list()
_SVC = _service_prices()

_FASTCONNECT = _SVC.get("OCI FastConnect") or {}
_FASTCONNECT_SOURCE_RATES = _FASTCONNECT.get("speedRates") or {}
_FASTCONNECT_SOURCE_SKUS = _FASTCONNECT.get("speedSkus") or {}
FASTCONNECT_SPEED_RATES = {
    "1G": float(_FASTCONNECT_SOURCE_RATES.get("1G", 0.2125)),
    "10G": float(_FASTCONNECT_SOURCE_RATES.get("10G", 1.275)),
    "100G": float(_FASTCONNECT_SOURCE_RATES.get("100G", 10.75)),
    "400G": float(_FASTCONNECT_SOURCE_RATES.get("400G", 20.00)),
}
FASTCONNECT_SPEED_SKUS = {
    "1G": str(_FASTCONNECT_SOURCE_SKUS.get("1G") or "B88325"),
    "10G": str(_FASTCONNECT_SOURCE_SKUS.get("10G") or "B88326"),
    "100G": str(_FASTCONNECT_SOURCE_SKUS.get("100G") or "B93126"),
    "400G": str(_FASTCONNECT_SOURCE_SKUS.get("400G") or "B107975"),
}
FASTCONNECT_SPEED_LABELS = {
    "1G": "1 Gbps",
    "10G": "10 Gbps",
    "100G": "100 Gbps",
    "400G": "400 Gbps",
}


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


def _sf(key, label, unit, default=0, step=1, min_=0, show_when=None, hide_when=None):
    """One numeric sizing field the user fills in. `show_when` = (field_key, value) shows the
    field only when another (select) field has that value; `hide_when` hides it when so."""
    f = {"key": key, "label": label, "unit": unit, "default": default,
         "step": step, "min": min_}
    if show_when:
        f["showWhen"] = {"field": show_when[0], "value": show_when[1]}
    if hide_when:
        f["hideWhen"] = {"field": hide_when[0], "value": hide_when[1]}
    return f


def _sel(key, label, options, default):
    """A dropdown field. `options` is a list of (value, label) pairs; the selected value
    is a string used by the entry's cost function (not multiplied)."""
    return {"key": key, "label": label, "unit": "", "default": default,
            "options": [{"value": v, "label": l} for v, l in options]}


# --- curated, fillable services -------------------------------------------------------------
# group order mirrors data/service_comp_list.json so the chips read like Oracle's console.
GROUPS = ["Compute", "Storage", "Networking", "Database", "Integration", "Security",
          "Observability", "AI & Machine Learning", "Licensing", "Other Services"]

# Every curated service has an explicit, bundled OCI icon contract. "fallback" means the
# selected icon is the closest honest visual available in the bundled Oracle library.
ARCHITECTURE_ICON_BY_ID = {
    "block": ("Storage - Block Storage", "direct"),
    "object": ("Storage - Object Storage", "direct"),
    "object_ia": ("Storage - Object Storage", "direct"),
    "file": ("Storage - File Storage", "direct"),
    "archive": ("Storage - Object Storage", "direct"),
    "lb": ("Networking - Flexible Load Balancer", "direct"),
    "egress": ("Networking - Service Gateway", "fallback"),
    "fastconnect": ("Networking - Dynamic Routing Gateway DRG", "fallback"),
    "dns": ("Networking - DNS", "direct"),
    "adb": ("Database - Autonomous DB", "direct"),
    "mysql": ("Database - MySQL", "direct"),
    "pg": ("Database - Database System", "fallback"),
    "dbbackup": ("Storage - Object Storage", "fallback"),
    "recovery": ("Storage - Object Storage", "fallback"),
    "oic": ("Developer Services - Integrations", "direct"),
    "waf": ("Identity and Security - WAF", "direct"),
    "kms": ("Identity and Security - Vault", "direct"),
    "fsdr": ("Governance and Administration - Cloud Advisor", "fallback"),
    "logging": ("Observability and Management - Logging", "direct"),
    "desktops": ("Compute - Virtual Machine VM", "fallback"),
    "winlic": ("Compute - Virtual Machine VM", "fallback"),
    "sqllic": ("Database - Database System", "fallback"),
}

ARCHITECTURE_GROUP_ICONS = {
    "Compute": "Compute - Virtual Machine VM",
    "Storage": "Storage - Object Storage",
    "Networking": "Networking - Service Gateway",
    "Database": "Database - Database System",
    "Integration": "Developer Services - Integrations",
    "Security": "Identity and Security - Vault",
    "Observability": "Observability and Management - Monitoring",
    "Obs. & Management": "Observability and Management - Monitoring",
    "AI & Machine Learning": "Analytics and AI",
    "Licensing": "Compute - Virtual Machine VM",
    "Other Services": "Compute - Functions",
}

# Ordered from most specific to broadest. This gives raw price-list SKUs the same
# deterministic product-to-icon contract as curated services instead of reducing every
# uncommon service to its broad catalog group.
ARCHITECTURE_NAME_ICONS = [
    ("autonomous data warehouse", "Database - Autonomous Data Warehouse ADW", "direct"),
    ("autonomous transaction processing", "Database - Autonomous Transaction Processing ATP", "direct"),
    ("autonomous recovery", "Storage - Object Storage", "fallback"),
    ("database backup", "Storage - Object Storage", "fallback"),
    ("autonomous", "Database - Autonomous DB", "direct"),
    ("container engine for kubernetes", "Developer Services - Container Engine for Kubernetes", "direct"),
    ("kubernetes engine", "Developer Services - Container Engine for Kubernetes", "direct"),
    ("container registry", "Developer Services - Container Registry", "direct"),
    ("api gateway", "Developer Services - API Gateway", "direct"),
    ("object storage", "Storage - Object Storage", "direct"),
    ("block volume", "Storage - Block Storage", "direct"),
    ("block storage", "Storage - Block Storage", "direct"),
    ("file storage", "Storage - File Storage", "direct"),
    ("load balancer", "Networking - Flexible Load Balancer", "direct"),
    ("fastconnect", "Networking - Dynamic Routing Gateway DRG", "fallback"),
    ("data transfer", "Networking - Service Gateway", "fallback"),
    ("service gateway", "Networking - Service Gateway", "direct"),
    ("web application firewall", "Identity and Security - WAF", "direct"),
    ("key management", "Identity and Security - Vault", "direct"),
    ("secure desktop", "Compute - Virtual Machine VM", "fallback"),
    ("windows server", "Compute - Virtual Machine VM", "fallback"),
    ("sql server", "Database - Database System", "fallback"),
    ("integration cloud", "Developer Services - Integrations", "direct"),
    ("application integration", "Developer Services - Integrations", "direct"),
    ("generative ai", "Analytics and AI", "fallback"),
    ("goldengate", "Database - GoldenGate", "direct"),
    ("postgres", "Database - Database System", "fallback"),
    ("mysql", "Database - MySQL", "direct"),
    ("heatwave", "Database - MySQL", "direct"),
    ("exadata", "Database - Exadata", "direct"),
    ("nosql", "Database - NoSQL", "direct"),
    ("function", "Compute - Functions", "direct"),
    ("logging", "Observability and Management - Logging", "direct"),
    ("monitoring", "Observability and Management - Monitoring", "direct"),
    ("vault", "Identity and Security - Vault", "direct"),
    ("waf", "Identity and Security - WAF", "direct"),
    ("dns", "Networking - DNS", "direct"),
]


def architecture_mapping(name="", group=""):
    """Return the bundled OCI icon title and the honesty level of the match."""
    normalized_name = _norm(name)
    for keyword, icon_title, resolution in ARCHITECTURE_NAME_ICONS:
        if keyword in normalized_name:
            return icon_title, resolution
    return (
        ARCHITECTURE_GROUP_ICONS.get(
            group,
            ARCHITECTURE_GROUP_ICONS["Other Services"],
        ),
        "category-fallback",
    )


def architecture_group(name="", group=""):
    """Place raw SKUs in the diagram zone implied by their resolved OCI icon."""
    icon_title, _resolution = architecture_mapping(name, group)
    prefix_groups = {
        "Storage -": "Storage",
        "Networking -": "Networking",
        "Database -": "Database",
        "Developer Services -": "Integration",
        "Identity and Security -": "Security",
        "Observability and Management -": "Observability",
        "Analytics and AI": "AI & Machine Learning",
    }
    for prefix, mapped_group in prefix_groups.items():
        if icon_title.startswith(prefix):
            return mapped_group
    return group or "Other Services"

# Names/keywords that mark a line as 3rd-party licensing (never OCI-discounted).
_THIRD_PARTY_TERMS = ("windows", "sql server", "license", "licence", "byol")


def _curated():
    """Curated, fillable services. Rates come from oci_service_prices.json (verified
    per-unit) where available, else the price list by SKU. Free tiers are declared so the
    cost math matches the app's own free-pool handling."""
    C = []

    def add(id, group, name, sku, rate, unit, basis, fields, note="", free=None,
            third_party=False):
        architecture_icon, architecture_resolution = ARCHITECTURE_ICON_BY_ID[id]
        C.append({"id": id, "group": group, "name": name, "sku": sku,
                  "rate": rate, "unit": unit, "basis": basis, "fields": fields,
                  "note": note, "free": free or {}, "source": "curated",
                  "architectureIcon": architecture_icon,
                  "architectureResolution": architecture_resolution,
                  # 3rd-party licensing (Windows, SQL Server, ...) is NOT eligible for the
                  # OCI discount; native OCI services are.
                  "thirdParty": third_party})

    # ---- Storage ----
    add("block", "Storage", "Block Volume (Balanced)", "B91961",
        _svc_rate("OCI Block Volumes", fallback=0.0255), "GB / month", "month",
        [_sf("gb", "Capacity", "GB", 1024, 128),
         _sf("vpus", "Performance (VPUs/GB)", "VPU", 10, 10)],
        "Balanced = 10 VPUs/GB. Storage + performance units both priced.")
    add("object", "Storage", "Object Storage - Standard", "B91628", OBJ_STORAGE_RATE,
        "GB + requests", "month",
        [_sf("gb", "Storage Capacity", "GB", 1000, 1, 0),
         _sf("requests", "Requests (10k units)", "10k req", 0, 1, 0)],
        "Storage $0.0255/GB-mo (first 10 GB free) + requests $0.0034 per 10,000 (first 50,000 "
        "free). Requests are entered in units of 10,000. SKUs B91628/B91627.")
    add("object_ia", "Storage", "Object Storage - Infrequent Access", "B93000",
        OBJ_IA_STORAGE_RATE, "GB + retrieval + requests", "month",
        [_sf("gb", "Storage Capacity", "GB", 1000, 1, 0),
         _sf("retrievalGb", "Data Retrieved / month", "GB", 0, 1, 0),
         _sf("requests", "Requests (10k units)", "10k req", 0, 1, 0)],
        "Storage $0.0100/GB-mo (first 10 GB free) + retrieval $0.0100/GB (first 10 GB free) "
        "+ requests $0.0034 per 10,000 (first 50,000 free). SKUs B93000/B93001/B91627.")
    add("file", "Storage", "File Storage (NFS)", "B89057",
        _svc_rate("OCI File Storage", fallback=0.30), "GB / month", "month",
        [_sf("gb", "Capacity", "GB", 1024, 128)])
    add("archive", "Storage", "Object Storage - Archive", "B91633",
        ARCHIVE_STORAGE_RATE, "GB + requests", "month",
        [_sf("gb", "Storage Capacity", "GB", 1000, 1, 0),
         _sf("requests", "Requests (10k units)", "10k req", 0, 1, 0)],
        "Storage $0.0026/GB-mo (first 10 GB free) + requests $0.0034 per 10,000 "
        "(first 50,000 free). SKUs B91633/B91627.")

    # ---- Networking ----
    add("lb", "Networking", "Flexible Load Balancer", "B93031",
        _svc_rate("OCI Load Balancer", fallback=0.0113), "LB / hour", "hour",
        [_sf("count", "Load balancers", "LB", 1, 1, 1)],
        "Per load-balancer-hour; bandwidth/LCU usage is included free on OCI.")
    add("egress", "Networking", "Outbound Data Transfer", "B87062",
        _svc_rate("OCI Outbound Data Transfer", fallback=0.0085), "GB / month", "month",
        [_sf("gb", "Egress", "GB", 0, 1024)],
        "First 10 TB/region/month is free.", free={"gb": 10240})
    add("fastconnect", "Networking", "FastConnect port", FASTCONNECT_SPEED_SKUS["10G"],
        FASTCONNECT_SPEED_RATES["10G"], "port / hour", "hour",
        [_sel("speed", "Port speed",
              [(key, FASTCONNECT_SPEED_LABELS[key])
               for key in ("1G", "10G", "100G", "400G")], "10G"),
         _sf("ports", "Ports", "port", 1, 1, 1)],
        "Choose a 1, 10, 100, or 400 Gbps provisioned port. Private virtual-circuit "
        "traffic has no separate inbound or outbound transfer charge.")
    C[-1]["speedRates"] = FASTCONNECT_SPEED_RATES
    C[-1]["speedSkus"] = FASTCONNECT_SPEED_SKUS
    C[-1]["speedLabels"] = FASTCONNECT_SPEED_LABELS
    add("dns", "Networking", "DNS (metered queries)", "B88516",
        _svc_rate("OCI DNS", fallback=0.85), "per 1M queries", "op",
        [_sf("millions", "Queries per month", "million", 1, 1)],
        "Hosted zones and intra-VCN queries are free.")

    # ---- Database (PaaS) ----
    # Autonomous DB rates are the customer-supplied OCI price-list values (these SKUs aren't
    # in oci_price_list.json). ECPU is billed per ECPU-hour; storage per GB-month.
    # Comprehensive Autonomous AI Database (Single Database, serverless), mirroring the OCI
    # cost estimator: ECPU compute + database storage (rate depends on workload) + backup
    # storage, all on one card. Priced by the "adb" branch in line_cost.
    add("adb", "Database", "Autonomous AI Database", "B95702", ADB_ECPU_RATE,
        "ECPU-hr + storage", "hour",
        [_sel("deployment", "Deployment Type",
              [("serverless", "Serverless"), ("dedicated", "Dedicated (Exadata)")], "serverless"),
         _sel("workload", "Workload Type",
              [("atp", "Transaction Processing (ATP)"),
               ("adw", "Lakehouse / Data Warehouse (ADW)"),
               ("ajd", "JSON (AJD)"),
               ("apex", "APEX")], "atp"),
         _sf("ecpu", "ECPUs", "ECPU", 2, 1, 2),
         _sf("dbgb", "Database Storage", "GB", 20, 1, 1, show_when=("deployment", "serverless")),
         _sf("dbservers", "Exadata DB Servers (X11M)", "server", 2, 1, 1,
             show_when=("deployment", "dedicated")),
         _sf("storageservers", "Exadata Storage Servers (X11M)", "server", 3, 1, 1,
             show_when=("deployment", "dedicated")),
         _sf("bakgb", "Backup Storage", "GB", 60, 1, 0)],
        "Serverless: ECPU $0.336/hr + DB storage (ATP $0.1953, ADW $0.0299/GB-mo) + backup "
        "$0.0299/GB-mo. Dedicated: ECPU + Exadata DB $6.3014/hr + Exadata storage $5.4795/hr "
        "+ Object Storage backup $0.0255/GB (10 GB free). SKUs B95702/B95701/B112666/B112667.")
    add("mysql", "Database", "MySQL HeatWave Database", "B108030", MYSQL_ECPU_RATE,
        "ECPU-hr + storage", "hour",
        [_sel("ecpu", "Total ECPU",
              [(2, "2"), (4, "4"), (8, "8"), (16, "16"), (32, "32"), (48, "48"),
               (64, "64"), (96, "96"), (128, "128"), (256, "256"), (512, "512")], 8),
         _sf("storage", "MySQL Storage", "GB", 1000, 1, 0),
         _sf("backup", "Additional Backup Storage", "GB", 0, 1, 0),
         _sf("egress", "Inter-OCI Region Egress", "GB", 0, 100, 0),
         _sel("ha", "High Availability", [("no", "No"), ("yes", "Yes (3 instances)")], "no"),
         _sel("heatwave", "HeatWave Cluster", [("no", "No"), ("yes", "Yes")], "no"),
         _sf("hwcapacity", "HeatWave Capacity Units", "unit", 128, 1, 0,
             show_when=("heatwave", "yes")),
         _sf("hwstorage", "HeatWave Storage", "GB", 1000, 1, 0,
             show_when=("heatwave", "yes"))],
        "ECPU $0.0366/hr; storage/backup/inter-region egress $0.04/GB-mo. HA triples ECPU + "
        "storage. HeatWave adds $0.011/capacity-hr + $0.02/GB-mo storage. Total ECPU is a "
        "fixed shape (2/4/8/16/32/48/64/96/...); memory is derived at 8 GB per ECPU. "
        "SKUs B108030/B92426/B92483/B109169/B96626/B96625.")
    add("pg", "Database", "Database with PostgreSQL", "B99060", PG_MANAGED_OCPU_RATE,
        "OCPU-hr + storage", "hour",
        [_sel("processor", "Processor", [("amd", "AMD (E5)"), ("intel", "Intel (X9)")], "amd"),
         _sf("ocpu", "OCPU per node", "OCPU", 10, 1, 1),
         _sf("nodes", "Nodes per cluster", "node", 3, 1, 1),
         _sf("memory", "Memory per node", "GB", 100, 1, 16),
         _sf("storage", "DB-Optimized Storage", "GB", 1000, 1, 0),
         _sf("vpu", "Storage VPU", "VPU", 30, 5, 0)],
        "Managed PostgreSQL OCPU $0.098/hr (x nodes) + DB-optimized storage $0.072/GB-mo + "
        "underlying compute (AMD $0.03 OCPU/$0.002 mem, Intel $0.04/$0.0015, x nodes) + block "
        "performance $0.0017/(GB*VPU). Sizing limits: AMD 1-64 OCPU, 16-1024 GB; Intel 2-32 "
        "OCPU, 32-512 GB (max 64 GB/OCPU). SKUs B99060/B99062/B97384/B97385/B91962.")
    add("dbbackup", "Database", "Database Backup (to Object Storage)", "B90230",
        _svc_rate("OCI Database Backup", fallback=0.0051), "GB / month", "month",
        [_sf("gb", "Backup capacity", "GB", 500, 100)])
    add("recovery", "Database", "Autonomous Recovery Service", "B95240", 0.0306,
        "GB / month", "month", [_sf("gb", "Protected capacity", "GB", 100, 50)],
        "Oracle Database Autonomous Recovery Service - virtualized GB per month.")

    # ---- Integration ----
    add("oic", "Integration", "Application Integration (OIC)", "B89639", OIC_STD_RATE,
        "message pack-hr", "hour",
        [_sel("edition", "License Edition",
              [("standard", "Standard"), ("enterprise", "Enterprise")], "standard"),
         _sf("peakday", "Peak daily volume (surge)", "msg/day", 0, 1000, 0),
         _sf("monthlymsgs", "Total messages / month", "msg/mo", 0, 100000, 0),
         _sf("packs", "Message Packs (used if volumes = 0)", "pack", 1, 1, 0)],
        "Priced per message pack-hour: Standard $0.6452, Enterprise $1.2903. 1 pack = 5,000 "
        "msg/hr (payload <=50KB). Packs auto-size from peak daily volume /(24*5,000), else "
        "total monthly messages /(hours*5,000), else the entered pack count. SKU B89639.")

    # ---- Security ----
    add("waf", "Security", "Web Application Firewall", "B94579", WAF_INSTANCE_RATE,
        "instance + requests", "month",
        [_sf("instances", "WAF Instances", "instance", 1, 1, 0),
         _sf("requests", "Incoming Requests (1M units)", "1M req", 0, 1, 0)],
        "Instances $5.00/mo (first instance free) + incoming requests $0.60 per 1,000,000 "
        "(first 10,000,000 free). Requests are entered in units of 1,000,000. SKUs B94579/B94277.")
    add("kms", "Security", "Key Management (Vault)", "B90328", KMS_VAULT_RATE,
        "vault-hr + keys", "hour",
        [_sf("vaults", "Private Vaults", "vault", 0, 1, 0),
         _sf("keyversions", "Software Key Versions (free)", "key", 0, 1, 0),
         _sf("external", "External Key Management", "key", 0, 1, 0),
         _sf("hsm", "Dedicated HSM Partitions (min 3)", "partition", 0, 1, 0)],
        "Virtual Private Vault $3.724/hr (B90328) + External Key Management $3.00/key-mo "
        "(B98100) + Dedicated HSM partitions $1.75/hr (B99597, min 3). Software key versions "
        "are free (B92092).")

    # ---- Disaster Recovery ----
    add("fsdr", "Other Services", "Full Stack Disaster Recovery", "B95485", FSDR_OCPU_RATE,
        "member-hours (both regions)", "hour",
        [_sf("p_compute", "Primary: Compute Member OCPUs", "OCPU", 0, 1, 0),
         _sf("p_db_ocpu", "Primary: Database Member OCPUs", "OCPU", 0, 1, 0),
         _sf("p_db_ecpu", "Primary: Database Member ECPUs", "ECPU", 0, 1, 0),
         _sf("p_oic", "Primary: OIC Message Packs", "pack", 0, 1, 0),
         _sf("s_compute", "Standby: Compute Member OCPUs", "OCPU", 0, 1, 0),
         _sf("s_db_ocpu", "Standby: Database Member OCPUs", "OCPU", 0, 1, 0),
         _sf("s_db_ecpu", "Standby: Database Member ECPUs", "ECPU", 0, 1, 0),
         _sf("s_oic", "Standby: OIC Message Packs", "pack", 0, 1, 0)],
        "OCI Full Stack DR, metered per member-hour across BOTH protection groups: "
        "Compute + DB member OCPUs at $0.0128/OCPU-hr (B95485), DB member ECPUs at "
        "$0.0032/ECPU-hr (B110274), OIC message packs at $0.192/pack-hr (B112110).")

    # ---- Observability / Other ----
    add("logging", "Observability", "Logging (ingest)", "B92707",
        _svc_rate("OCI Logging", fallback=0.05), "GB / month", "month",
        [_sf("gb", "Log data", "GB", 0, 10)],
        "First 10 GB/month is free.", free={"gb": 10})
    add("desktops", "Other Services", "Secure Desktops", "B95518", DESKTOP_UNIT_RATE,
        "desktop + compute + storage", "month",
        [_sf("desktops", "Secure Desktops Per Pool", "desktop", 20, 1, 1),
         _sel("os", "Desktop OS", [("linux", "Oracle Linux"),
              ("win_dvh", "Windows BYOL on DVH"), ("win_vm", "Windows BYOL on VM")], "linux"),
         _sf("ocpu", "Desktop OCPU", "OCPU", 2, 1, 1),
         _sf("memory", "Desktop Memory", "GB", 8, 1, 1),
         _sf("bootgb", "Boot Volume", "GB", 100, 1, 0),
         _sf("bootvpu", "Boot VPU", "VPU", 10, 5, 0),
         _sf("optgb", "Optional Block Storage / Desktop", "GB", 0, 1, 0),
         _sf("optvpu", "Optional Block VPU", "VPU", 10, 5, 0)],
        "Per desktop ($20/mo, B95518) x pool + underlying E6 compute ($0.03 OCPU/$0.002 mem, "
        "B111129/B111130) + boot & optional block volumes ($0.0255/GB + $0.0017/(GB*VPU), "
        "B91961/B91962). Windows options are BYOL (no added license). All x desktops.")

    # ---- 3rd-party licensing (NOT discounted) ----
    add("winlic", "Licensing", "Windows Server license", "B88318", _rate("B88318", 0.092),
        "OCPU / hour", "hour", [_sf("ocpu", "Licensed OCPUs", "OCPU", 2, 1, 1)],
        "3rd-party Microsoft licensing - excluded from the OCI discount.", third_party=True)
    add("sqllic", "Licensing", "SQL Server License", "B91372", SQL_ENT_RATE,
        "OCPU / hour", "hour",
        [_sel("edition", "Edition",
              [("enterprise", "Enterprise"), ("standard", "Standard"),
               ("express", "Express (free)")], "enterprise"),
         _sf("ocpu", "Licensed OCPUs", "OCPU", 1, 1, 1)],
        "License-included Microsoft SQL Server (OCI marketplace image): Enterprise $1.47/OCPU-hr "
        "(B91372), Standard $0.37/OCPU-hr (B91373), Express $0. 3rd-party licensing - excluded "
        "from the OCI discount.", third_party=True)

    return [c for c in C if isinstance(c["rate"], (int, float))]


CURATED = _curated()


# --- monthly cost -----------------------------------------------------------------------------
def line_cost(entry, values, hours=HOURS_PER_MONTH):
    """Monthly USD for a filled-in catalog entry. Deterministic; mirrors the app's math,
    including free tiers (egress 10 TB, WAF 10M requests, Logging 10 GB).

    `hours` is the app's hours-per-month setting - anything billed per hour (ECPU, OCPU,
    load-balancer-hour, port-hour) multiplies by it, so the catalog follows the same hours
    the compute rows use rather than a static 730.
    """
    rate = float(entry.get("rate") or 0)
    basis = entry.get("basis", "month")
    free = entry.get("free") or {}
    # Per-hour add-ins default to 730 hours/month, editable per SKU via a "__hours" value.
    hours = float((values.get("__hours") if values else 0) or 0) or float(hours or HOURS_PER_MONTH)
    # Numeric sizing fields. A dropdown with numeric option values (e.g. MySQL Total ECPU)
    # parses to a number; a text dropdown (processor, workload) stays a string and is read
    # directly from `values` by the per-entry math below.
    v = {}
    for f in entry["fields"]:
        try:
            v[f["key"]] = float(values.get(f["key"], f.get("default", 0)) or 0)
        except (TypeError, ValueError):
            pass

    # Autonomous AI Database: ECPU compute + storage + backup. Serverless prices DB storage
    # per workload and backup at $0.0299/GB; Dedicated adds Exadata infra and backs up to
    # Object Storage ($0.0255/GB, first 10 GB free).
    if entry["id"] == "adb":
        deployment = str(values.get("deployment") or "serverless").lower()
        workload = str(values.get("workload") or "atp").lower()
        ecpu_cost = v.get("ecpu", 0) * ADB_ECPU_RATE * hours
        bakgb = v.get("bakgb", 0)
        if deployment == "dedicated":
            infra = (v.get("dbservers", 0) * ADB_EXA_DB_SERVER
                     + v.get("storageservers", 0) * ADB_EXA_STORAGE_SERVER) * hours
            backup = max(0.0, bakgb - ADB_OBJ_BACKUP_FREE) * ADB_OBJ_BACKUP
            return round(ecpu_cost + infra + backup, 2)
        store_rate = ADB_STORAGE_ADW if workload == "adw" else ADB_STORAGE_ATP
        return round(ecpu_cost + v.get("dbgb", 0) * store_rate + bakgb * ADB_BACKUP_RATE, 2)

    # Secure Desktops: per-desktop fee ($20) + compute + boot volume + optional block per
    # desktop. Two compute models depending on the desktop OS:
    #   VM (Oracle Linux / Windows-BYOL-on-VM): E6 compute + boot PER DESKTOP.
    #   DVH (Windows-BYOL-on-DVH): E4.128 Dedicated Host(s) + boot PER HOST; host count =
    #       ceil(desktops * OCPU / 124 available OCPUs).
    if entry["id"] == "desktops":
        n = v.get("desktops", 0)
        cost = n * DESKTOP_UNIT_RATE
        cost += (v.get("optgb", 0) * DESKTOP_BLOCK_RATE
                 + v.get("optgb", 0) * v.get("optvpu", 0) * DESKTOP_VPU_RATE) * n
        if str(values.get("os") or "linux").lower() == "win_dvh":
            hosts = max(1, math.ceil(n * v.get("ocpu", 0) / DVH_AVAIL_OCPU)) if v.get("ocpu", 0) else 1
            cost += hosts * DVH_HOST_OCPU * hours * DESKTOP_E4_OCPU_RATE
            cost += hosts * DVH_HOST_MEM * hours * DESKTOP_E4_MEM_RATE
            cost += (v.get("bootgb", 0) * DESKTOP_BLOCK_RATE
                     + v.get("bootgb", 0) * v.get("bootvpu", 0) * DESKTOP_VPU_RATE) * hosts
        else:
            cost += v.get("ocpu", 0) * n * hours * DESKTOP_OCPU_RATE
            cost += v.get("memory", 0) * n * hours * DESKTOP_MEM_RATE
            cost += (v.get("bootgb", 0) * DESKTOP_BLOCK_RATE
                     + v.get("bootgb", 0) * v.get("bootvpu", 0) * DESKTOP_VPU_RATE) * n
        return round(cost, 2)

    # SQL Server license (license-included): per-edition OCPU-hour rate (Express is free).
    if entry["id"] == "sqllic":
        edition = str(values.get("edition") or "enterprise").lower()
        rate = {"enterprise": SQL_ENT_RATE, "standard": SQL_STD_RATE}.get(edition, 0.0)
        return round(v.get("ocpu", 0) * rate * hours, 2)

    # Key Management: private vaults + external key mgmt + dedicated HSM partitions.
    # Software key versions are free.
    if entry["id"] == "kms":
        return round(v.get("vaults", 0) * hours * KMS_VAULT_RATE
                     + v.get("external", 0) * KMS_EXTERNAL_RATE
                     + v.get("hsm", 0) * hours * KMS_HSM_RATE, 2)

    # Web Application Firewall: instances (first free) + requests per 1M (first 10M free).
    if entry["id"] == "waf":
        return round(max(0.0, v.get("instances", 0) - WAF_INSTANCE_FREE) * WAF_INSTANCE_RATE
                     + max(0.0, v.get("requests", 0) - WAF_REQUEST_FREE) * WAF_REQUEST_RATE, 2)

    # Object Storage: GB storage (first 10 GB free) + requests per 10k (first 50k free).
    if entry["id"] == "object":
        return round(max(0.0, v.get("gb", 0) - OBJ_STORAGE_FREE_GB) * OBJ_STORAGE_RATE
                     + max(0.0, v.get("requests", 0) - OBJ_REQUEST_FREE_UNITS) * OBJ_REQUEST_RATE, 2)
    if entry["id"] == "object_ia":
        return round(max(0.0, v.get("gb", 0) - OBJ_STORAGE_FREE_GB) * OBJ_IA_STORAGE_RATE
                     + max(0.0, v.get("retrievalGb", 0) - OBJ_IA_RETRIEVAL_FREE_GB)
                     * OBJ_IA_RETRIEVAL_RATE
                     + max(0.0, v.get("requests", 0) - OBJ_REQUEST_FREE_UNITS)
                     * OBJ_REQUEST_RATE, 2)
    if entry["id"] == "archive":
        return round(max(0.0, v.get("gb", 0) - OBJ_STORAGE_FREE_GB) * ARCHIVE_STORAGE_RATE
                     + max(0.0, v.get("requests", 0) - OBJ_REQUEST_FREE_UNITS)
                     * OBJ_REQUEST_RATE, 2)

    # OCI Database with PostgreSQL: managed OCPU + DB-optimized storage + underlying compute
    # (per-processor OCPU/memory, x nodes) + block-volume performance units.
    if entry["id"] == "pg":
        ocpu = v.get("ocpu", 0)
        nodes = v.get("nodes", 1) or 1
        storage = v.get("storage", 0)
        if str(values.get("processor") or "amd").lower() == "intel":
            c_ocpu, c_mem = PG_COMPUTE_OCPU_RATE_INTEL, PG_COMPUTE_MEM_RATE_INTEL
        else:
            c_ocpu, c_mem = PG_COMPUTE_OCPU_RATE, PG_COMPUTE_MEM_RATE
        cost = (ocpu * nodes * hours * PG_MANAGED_OCPU_RATE     # managed PostgreSQL OCPU
                + storage * PG_STORAGE_RATE                     # DB-optimized storage
                + ocpu * nodes * hours * c_ocpu                 # underlying compute OCPU
                + v.get("memory", 0) * nodes * hours * c_mem    # underlying compute memory
                + storage * v.get("vpu", 0) * PG_VPU_RATE)      # block performance units
        return round(cost, 2)

    # MySQL HeatWave: ECPU + storage + backup + egress; HA triples ECPU + storage;
    # optional HeatWave cluster adds capacity + storage.
    if entry["id"] == "mysql":
        mult = 3 if str(values.get("ha") or "no").lower() == "yes" else 1
        cost = (v.get("ecpu", 0) * MYSQL_ECPU_RATE * hours * mult
                + v.get("storage", 0) * MYSQL_STORAGE_RATE * mult
                + v.get("backup", 0) * MYSQL_STORAGE_RATE
                + v.get("egress", 0) * MYSQL_STORAGE_RATE)
        if str(values.get("heatwave") or "no").lower() == "yes":
            cost += (v.get("hwcapacity", 0) * MYSQL_HW_RATE * hours
                     + v.get("hwstorage", 0) * MYSQL_HW_STORAGE_RATE)
        return round(cost, 2)

    # Oracle Integration Cloud: message packs (auto-sized) x hours x per-edition rate.
    if entry["id"] == "oic":
        edition = str(values.get("edition") or "standard").lower()
        rate = OIC_ENT_RATE if edition == "enterprise" else OIC_STD_RATE
        return round(oic_packs(values, hours) * rate * hours, 2)

    # Full Stack DR: OCPU + ECPU + OIC-pack members, summed across both protection groups.
    if entry["id"] == "fsdr":
        ocpu = v.get("p_compute", 0) + v.get("p_db_ocpu", 0) + v.get("s_compute", 0) + v.get("s_db_ocpu", 0)
        ecpu = v.get("p_db_ecpu", 0) + v.get("s_db_ecpu", 0)
        oic = v.get("p_oic", 0) + v.get("s_oic", 0)
        return round((ocpu * FSDR_OCPU_RATE + ecpu * FSDR_ECPU_RATE + oic * FSDR_OIC_RATE) * hours, 2)

    if entry["id"] == "fastconnect":
        speed = str(values.get("speed") or "10G").upper()
        speed_rate = FASTCONNECT_SPEED_RATES.get(speed, FASTCONNECT_SPEED_RATES["10G"])
        return round(v.get("ports", 0) * speed_rate * hours, 2)

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


def line_breakdown(entry, values, hours=HOURS_PER_MONTH):
    """Per-SKU line items for a filled-in catalog entry - the full paper trail (like the OCI
    estimator's 'Pricing Details'). Each item: {sku, desc, qty, rate, hours, monthly}. The
    sum of the items equals line_cost(entry, values, hours)."""
    hours = float((values.get("__hours") if values else 0) or 0) or float(hours or HOURS_PER_MONTH)
    v = {}
    for f in entry.get("fields", []):
        try:
            v[f["key"]] = float(values.get(f["key"], f.get("default", 0)) or 0)
        except (TypeError, ValueError):
            pass
    cid = entry["id"]
    out = []

    def li(sku, desc, qty, rate, hourly=False, monthly=None):
        m = monthly if monthly is not None else round(qty * rate * (hours if hourly else 1), 2)
        out.append({"sku": sku, "desc": desc, "qty": round(qty, 4), "rate": rate,
                    "hours": hours if hourly else "", "monthly": round(m, 2)})

    if cid == "mysql":
        mult = 3 if str(values.get("ha") or "no").lower() == "yes" else 1
        li("B108030", "MySQL Database - ECPU", v.get("ecpu", 0) * mult, MYSQL_ECPU_RATE, True)
        li("B92426", "MySQL Database - Storage", v.get("storage", 0) * mult, MYSQL_STORAGE_RATE)
        li("B92483", "MySQL Database - Backup Storage", v.get("backup", 0), MYSQL_STORAGE_RATE)
        li("B109169", "MySQL - Outbound Data Transfer (Inter-OCI)", v.get("egress", 0), MYSQL_STORAGE_RATE)
        if str(values.get("heatwave") or "no").lower() == "yes":
            li("B96626", "OCI HeatWave", v.get("hwcapacity", 0), MYSQL_HW_RATE, True)
            li("B96625", "OCI HeatWave - Storage", v.get("hwstorage", 0), MYSQL_HW_STORAGE_RATE)
    elif cid == "pg":
        ocpu, nodes = v.get("ocpu", 0), (v.get("nodes", 1) or 1)
        storage = v.get("storage", 0)
        intel = str(values.get("processor") or "amd").lower() == "intel"
        c_ocpu, c_mem = (PG_COMPUTE_OCPU_RATE_INTEL, PG_COMPUTE_MEM_RATE_INTEL) if intel else (PG_COMPUTE_OCPU_RATE, PG_COMPUTE_MEM_RATE)
        li("B99060", "Database with PostgreSQL - OCPU", ocpu * nodes, PG_MANAGED_OCPU_RATE, True)
        li("B99062", "Database Optimized Storage", storage, PG_STORAGE_RATE)
        li("B97384", "Compute - Standard - OCPU", ocpu * nodes, c_ocpu, True)
        li("B97385", "Compute - Standard - Memory", v.get("memory", 0) * nodes, c_mem, True)
        li("B91962", "Block Volume - Performance Units", storage * v.get("vpu", 0), PG_VPU_RATE)
    elif cid == "adb":
        workload = str(values.get("workload") or "atp").lower()
        packs_ecpu = v.get("ecpu", 0)
        if str(values.get("deployment") or "serverless").lower() == "dedicated":
            li("B95712" if workload == "adw" else "B95713", "Autonomous DB - Dedicated ECPU", packs_ecpu, ADB_ECPU_RATE, True)
            li("B112666", "Exadata Cloud Infrastructure - Database Server", v.get("dbservers", 0), ADB_EXA_DB_SERVER, True)
            li("B112667", "Exadata Cloud Infrastructure - Storage Server", v.get("storageservers", 0), ADB_EXA_STORAGE_SERVER, True)
            li("B91628", "Object Storage - Backup", max(0.0, v.get("bakgb", 0) - ADB_OBJ_BACKUP_FREE), ADB_OBJ_BACKUP)
        else:
            li("B95701" if workload == "adw" else "B95702", "Autonomous DB - ECPU", packs_ecpu, ADB_ECPU_RATE, True)
            li("B95754" if workload == "adw" else "B95706", "Autonomous DB - Storage", v.get("dbgb", 0), ADB_STORAGE_ADW if workload == "adw" else ADB_STORAGE_ATP)
            li("B95754", "Autonomous DB - Backup Storage", v.get("bakgb", 0), ADB_BACKUP_RATE)
    elif cid == "oic":
        edition = str(values.get("edition") or "standard").lower()
        rate = OIC_ENT_RATE if edition == "enterprise" else OIC_STD_RATE
        li("B89639", "Oracle Integration Cloud - " + ("Enterprise" if edition == "enterprise" else "Standard"), oic_packs(values, hours), rate, True)
    elif cid == "fsdr":
        ocpu = v.get("p_compute", 0) + v.get("p_db_ocpu", 0) + v.get("s_compute", 0) + v.get("s_db_ocpu", 0)
        ecpu = v.get("p_db_ecpu", 0) + v.get("s_db_ecpu", 0)
        oic = v.get("p_oic", 0) + v.get("s_oic", 0)
        li("B95485", "Full Stack DR - Compute + DB Member OCPUs", ocpu, FSDR_OCPU_RATE, True)
        li("B110274", "Full Stack DR - Database Member ECPUs", ecpu, FSDR_ECPU_RATE, True)
        li("B112110", "Full Stack DR - OIC Message Packs", oic, FSDR_OIC_RATE, True)
    elif cid == "fastconnect":
        speed = str(values.get("speed") or "10G").upper()
        speed = speed if speed in FASTCONNECT_SPEED_RATES else "10G"
        li(FASTCONNECT_SPEED_SKUS[speed],
           f"FastConnect {FASTCONNECT_SPEED_LABELS[speed]} port",
           v.get("ports", 0), FASTCONNECT_SPEED_RATES[speed], True)
    elif cid == "object":
        li("B91628", "Object Storage - Storage", max(0.0, v.get("gb", 0) - OBJ_STORAGE_FREE_GB), OBJ_STORAGE_RATE)
        li("B91627", "Object Storage - Requests", max(0.0, v.get("requests", 0) - OBJ_REQUEST_FREE_UNITS), OBJ_REQUEST_RATE)
    elif cid == "object_ia":
        li("B93000", "Object Storage - Infrequent Access Storage",
           max(0.0, v.get("gb", 0) - OBJ_STORAGE_FREE_GB), OBJ_IA_STORAGE_RATE)
        li("B93001", "Object Storage - Infrequent Access Retrieval",
           max(0.0, v.get("retrievalGb", 0) - OBJ_IA_RETRIEVAL_FREE_GB),
           OBJ_IA_RETRIEVAL_RATE)
        li("B91627", "Object Storage - Requests",
           max(0.0, v.get("requests", 0) - OBJ_REQUEST_FREE_UNITS), OBJ_REQUEST_RATE)
    elif cid == "archive":
        li("B91633", "Object Storage - Archive Storage",
           max(0.0, v.get("gb", 0) - OBJ_STORAGE_FREE_GB), ARCHIVE_STORAGE_RATE)
        li("B91627", "Object Storage - Requests",
           max(0.0, v.get("requests", 0) - OBJ_REQUEST_FREE_UNITS), OBJ_REQUEST_RATE)
    elif cid == "waf":
        li("B94579", "Web Application Firewall - Instance", max(0.0, v.get("instances", 0) - WAF_INSTANCE_FREE), WAF_INSTANCE_RATE)
        li("B94277", "Web Application Firewall - Requests", max(0.0, v.get("requests", 0) - WAF_REQUEST_FREE), WAF_REQUEST_RATE)
    elif cid == "kms":
        li("B90328", "Key Management - Private Vault", v.get("vaults", 0), KMS_VAULT_RATE, True)
        li("B92092", "Key Management - Key Versions (free)", v.get("keyversions", 0), 0.0)
        li("B98100", "External Key Management", v.get("external", 0), KMS_EXTERNAL_RATE)
        li("B99597", "Dedicated Key Management - HSM Partition", v.get("hsm", 0), KMS_HSM_RATE, True)
    elif cid == "desktops":
        n = v.get("desktops", 0)
        li("B95518", "Secure Desktop", n, DESKTOP_UNIT_RATE)
        if str(values.get("os") or "linux").lower() == "win_dvh":
            hosts = max(1, math.ceil(n * v.get("ocpu", 0) / DVH_AVAIL_OCPU)) if v.get("ocpu", 0) else 1
            li("B93113", "Compute E4 (DVH) - OCPU", DVH_HOST_OCPU * hosts, DESKTOP_E4_OCPU_RATE, True)
            li("B93114", "Compute E4 (DVH) - Memory", DVH_HOST_MEM * hosts, DESKTOP_E4_MEM_RATE, True)
            li("B91961", "Boot Volume - Storage", v.get("bootgb", 0) * hosts, DESKTOP_BLOCK_RATE)
            li("B91962", "Boot Volume - Performance Units", v.get("bootgb", 0) * v.get("bootvpu", 0) * hosts, DESKTOP_VPU_RATE)
        else:
            li("B111129", "Compute E6 - OCPU", v.get("ocpu", 0) * n, DESKTOP_OCPU_RATE, True)
            li("B111130", "Compute E6 - Memory", v.get("memory", 0) * n, DESKTOP_MEM_RATE, True)
            li("B91961", "Boot Volume - Storage", v.get("bootgb", 0) * n, DESKTOP_BLOCK_RATE)
            li("B91962", "Boot Volume - Performance Units", v.get("bootgb", 0) * v.get("bootvpu", 0) * n, DESKTOP_VPU_RATE)
        if v.get("optgb", 0):
            li("B91961", "Optional Block Storage - Storage", v.get("optgb", 0) * n, DESKTOP_BLOCK_RATE)
            li("B91962", "Optional Block Storage - Performance Units", v.get("optgb", 0) * v.get("optvpu", 0) * n, DESKTOP_VPU_RATE)
    elif cid == "sqllic":
        edition = str(values.get("edition") or "enterprise").lower()
        sku = {"enterprise": "B91372", "standard": "B91373", "express": "SQL-EXPRESS"}.get(edition, "B91372")
        rate = {"enterprise": SQL_ENT_RATE, "standard": SQL_STD_RATE}.get(edition, 0.0)
        li(sku, "Microsoft SQL " + edition.title() + " (license-included)", v.get("ocpu", 0), rate, True)
    elif cid == "block":
        li("B91961", "Block Volume - Storage", v.get("gb", 0), _svc_rate("OCI Block Volumes", fallback=0.0255))
        li("B91962", "Block Volume - Performance Units", v.get("gb", 0) * v.get("vpus", 10),
           _SVC.get("OCI Block Volumes", {}).get("perfUnitsRate") or 0.0017)
    else:
        # Single-SKU entry: one line at its own rate.
        fkey = next((f["key"] for f in entry.get("fields", []) if not f.get("options")), None)
        qty = v.get(fkey, 0) if fkey else 0
        free = (entry.get("free") or {}).get(fkey, 0) if fkey else 0
        li(entry["sku"], entry["name"], max(0.0, qty - free), float(entry.get("rate") or 0),
           entry.get("basis") == "hour")
    return [it for it in out if it["monthly"] or it["rate"] == 0]


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
    """Re-price the services the user added, authoritatively, from the catalog - never
    trusting the client's number. `hours` is the app's hours-per-month setting so per-hour
    services follow it. Returns a clean list the exporter can consume:
        [{name, group, sku, unit, monthly, sizing}]  plus a total.
    """
    # Add-ins default to 730 hours/month regardless of the app-wide hours setting; each SKU
    # can override its own hours via a "__hours" value on the client record.
    default_hours = float(HOURS_PER_MONTH)
    out, total = [], 0.0
    for s in (extra_services or []):
        cid = s.get("catalogId") or s.get("id")
        entry = _entry_by_id(cid)
        values = s.get("values") or {}
        svc_hours = float((values.get("__hours") if values else 0) or 0) or default_hours
        if entry:
            monthly = line_cost(entry, values, default_hours)
            name, group, sku, unit = entry["name"], entry["group"], entry["sku"], entry["unit"]
            fields = entry["fields"]
            third = bool(entry.get("thirdParty"))
            rate = float(entry.get("rate") or 0)
            basis = entry.get("basis", "month")
            architecture_icon = entry["architectureIcon"]
            architecture_resolution = entry["architectureResolution"]
            architecture_service_group = group
            if cid == "fastconnect":
                speed = str(values.get("speed") or "10G").upper()
                speed = speed if speed in FASTCONNECT_SPEED_RATES else "10G"
                name = f"FastConnect port ({FASTCONNECT_SPEED_LABELS[speed]})"
                sku = FASTCONNECT_SPEED_SKUS[speed]
                rate = FASTCONNECT_SPEED_RATES[speed]
        else:
            # A raw price-list SKU (raw:<sku>): basis carried on the client record.
            rate = float(s.get("rate") or 0)
            basis = s.get("basis", "month")
            qraw = float((values.get("qty") if values else 0) or 0)
            monthly = round(rate * qraw * (svc_hours if basis == "hour" else 1), 2)
            name = s.get("name", cid or "Service")
            group = s.get("group", "Other Services")
            sku = s.get("sku", "")
            unit = s.get("unit", "unit")
            fields = s.get("fields") or []
            third = bool(s.get("thirdParty")) or group == "Licensing"
            architecture_icon, architecture_resolution = architecture_mapping(name, group)
            architecture_service_group = architecture_group(name, group)
        # Primary billed quantity for display. OIC shows the auto-sized message packs.
        if cid == "oic":
            qty = oic_packs(values, svc_hours)
        else:
            num_fields = [f for f in fields if not f.get("options")]
            fkey = num_fields[0]["key"] if num_fields else None
            qty = (float(values.get(fkey, num_fields[0].get("default", 0)) or 0)
                   if fkey else 0)
        hours_used = svc_hours if basis == "hour" else ""
        # Keep the editable hours out of the sizing string (it has its own column).
        sizing = " · ".join(
            f"{values.get(f['key'], f.get('default', 0))} {f.get('unit', '')}".strip()
            for f in fields if f.get("key") != "__hours"
        )
        # Full per-SKU paper trail (estimator "Pricing Details"). Curated entries expand
        # into all their constituent SKUs; a raw price-list SKU stays a single line.
        if entry:
            skus = line_breakdown(entry, values, svc_hours)
        else:
            skus = [{"sku": sku, "desc": name, "qty": round(qty, 4), "rate": rate,
                     "hours": hours_used, "monthly": round(monthly, 2)}]
        if sku and not any(line.get("sku") == sku for line in skus):
            skus.insert(
                0,
                {"sku": sku, "desc": name, "qty": round(qty, 4), "rate": rate,
                 "hours": hours_used, "monthly": 0.0},
            )
        if not skus:
            skus = [{"sku": sku or "N/A", "desc": name, "qty": round(qty, 4),
                     "rate": rate, "hours": hours_used, "monthly": round(monthly, 2)}]
        out.append({"name": name, "group": group, "sku": sku, "unit": unit,
                    "monthly": round(monthly, 2), "sizing": sizing, "thirdParty": third,
                    "rate": rate, "qty": round(qty, 4), "basis": basis, "hours": hours_used,
                    "skus": skus, "architectureIcon": architecture_icon,
                    "architectureResolution": architecture_resolution,
                    "architectureGroup": architecture_service_group})
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
