"""OCI target-architecture diagram, generated from the app's priced BOM.

Builds a diagram spec from whatever the BOM actually knows (workload segments, OCPU/
RAM/storage, licensing) and renders it with the bundled OCI stencil library into an
editable .drawio plus a PNG. The PNG is embedded into the Full BOM's Pricing Overview
sheet; the .drawio is the editable source of truth.

Layout follows diagram/layout-conventions.md: tenancy -> governance band -> region ->
hub VCN + one spoke VCN per workload segment -> subnets, with the DRG as the anchor.

This is deterministic Python — no model call. Requires `pillow` for the PNG preview.
"""

import json
import re
import sys
import tempfile
from pathlib import Path

DIAGRAM_DIR = Path(__file__).resolve().parent / "diagram"
# The vendored skills expect the scripts/ + assets/ sibling layout — export_png resolves
# the stencil library relative to its own file, so don't flatten these folders.
SCRIPTS_DIR = DIAGRAM_DIR / "scripts"
LIB_PATH = DIAGRAM_DIR / "assets" / "OCI Library.xml"
ICONS_PATH = DIAGRAM_DIR / "assets" / "icons_data.json"

# Segment spokes at most this many ways; beyond that the diagram stops being readable.
MAX_SPOKES = 3


def _clean(v):
    return "" if v is None else str(v).replace("\xa0", " ").strip()


def _norm(v):
    return re.sub(r"[^a-z0-9]+", " ", _clean(v).lower()).strip()


def _even_share(total, n, idx):
    """Split `total` into `n` as-even-as-possible integer parts; part `idx` gets one of the
    leftover units when it doesn't divide evenly (e.g. 149 over 3 -> 50, 50, 49)."""
    total = int(round(float(total or 0)))
    n = max(1, int(n))
    base, rem = divmod(total, n)
    return base + (1 if idx < rem else 0)


def _segment_key(raw_row, keys):
    """Prefer a real Tier/Environment column; fall back to OS family; else one segment."""
    for role in ("tier", "env", "os_family", "app"):
        k = keys.get(role)
        if k:
            v = _clean(raw_row.get(k))
            if v:
                return v
    return "Workloads"


def segment_source(rows, keys):
    """Which inventory column actually drove the segmentation (for the diagram's notes)."""
    for role in ("tier", "env", "os_family", "app"):
        k = keys.get(role)
        if k and any(_clean(r.get(k)) for r in (rows or [])):
            return role
    return ""


def collect_segments(pricing, rows, keys):
    """Group the priced servers into spoke segments with real totals."""
    raw_by_id = {}
    for r in (rows or []):
        rid = r.get("__id") or r.get("rowId")
        if rid:
            raw_by_id[str(rid)] = r

    segs = {}
    for p in (pricing or {}).get("rows", []):
        specs = p.get("specs") or {}
        if not (specs.get("ocpus") or specs.get("memoryGb") or specs.get("blockStorageGb")):
            continue
        raw = raw_by_id.get(str(p.get("rowId"))) or {}
        name = _segment_key(raw, keys) or "Workloads"
        s = segs.setdefault(name, {"name": name, "vms": 0, "winvms": 0, "ocpu": 0.0,
                                   "ram": 0.0, "block": 0.0, "win": 0.0})
        s["vms"] += 1
        _win = float(p.get("windowsLicenseMonthly") or 0)
        if _win > 0:
            s["winvms"] += 1                        # this server carries Windows OS licensing
        s["ocpu"] += float(specs.get("ocpus") or 0)
        s["ram"] += float(specs.get("memoryGb") or 0)
        s["block"] += float(specs.get("blockStorageGb") or 0)
        s["win"] += _win

    out = sorted(segs.values(), key=lambda s: -s["vms"])
    if len(out) > MAX_SPOKES:                       # fold the tail into one "Other" spoke
        head, tail = out[:MAX_SPOKES - 1], out[MAX_SPOKES - 1:]
        merged = {"name": "Other workloads", "vms": 0, "winvms": 0, "ocpu": 0.0,
                  "ram": 0.0, "block": 0.0, "win": 0.0}
        for t in tail:
            for k in ("vms", "winvms", "ocpu", "ram", "block", "win"):
                merged[k] += t[k]
        out = head + [merged]
    return out


# Mapped OCI service group -> stencil + short label for the diagram's services band.
# Compute is the VM boxes already, so it's excluded here.
_SERVICE_STENCILS = {
    "Storage": ("Storage - Object Storage", "Object / File\nStorage"),
    "Database": ("Database", "Database"),
    "Networking": ("Networking - Flexible Load Balancer", "Networking /\nLoad Balancer"),
    "Security": ("Identity and Security - Vault", "Security /\nKMS"),
    "Obs. & Management": ("Observability and Management - Monitoring", "Observability"),
    "AI & Machine Learning": ("Analytics and AI", "AI /\nMachine Learning"),
    "DevOps": ("Developer Services - Container Engine for Kubernetes", "DevOps /\nContainers"),
    "Other Services": ("Compute - Functions", "PaaS /\nFunctions"),
    "Marketplace": ("Marketplace", "Marketplace"),
    "Support": ("Governance and Administration - Cloud Advisor", "Support /\nGovernance"),
    "End User Computing": ("Compute - Instance Pools", "End User\nComputing"),
    "Analytics": ("Analytics and AI - Big Data", "Analytics"),
    "Containers": ("Developer Services - Container Registry", "Containers"),
}


def _cloud_group_of():
    try:
        import bom_export
        return bom_export._cloud_product_group
    except Exception:
        return None


def _row_group(r, group_of):
    """Product group for a priced bill row OR a synthetic add-in row (which carries its
    group directly in __addinGroup, bypassing the cloud-bill mapper)."""
    g = r.get("__addinGroup")
    if g:
        return g
    cat = _clean(r.get("ociServiceCategory"))
    return group_of(cat, r.get("sourceService")) if group_of else (cat or "")


# Add-in group -> diagram category vocabulary.
_ADDIN_GRP = {"Observability": "Obs. & Management", "Integration": "Other Services"}


def _addins_as_rows(extra_priced):
    """Priced 'Add OCI services' items -> synthetic diagram rows, so the diagram reflects
    EVERYTHING the app priced (bill + add-ins), not just the bill. The group comes straight
    from the add-in; a SQL Server license add-in is treated as a database, and Windows
    licensing is skipped (it's already drawn as the Windows OS icon)."""
    rows = []
    for s in (extra_priced or []):
        g = s.get("group") or "Other Services"
        name = s.get("name") or ""
        if g == "Licensing":
            if "sql" in name.lower():
                g = "Database"
            else:
                continue
        g = _ADDIN_GRP.get(g, g)
        mo = float(s.get("monthly") or 0)
        rows.append({"ociServiceCategory": g, "ociProduct": name, "__addinGroup": g,
                     "sourceService": "Add-in OCI service", "monthly": mo,
                     "lineItems": [{"monthly": mo}]})
    return rows


def collect_services(pricing, max_items=12):
    """Which OCI service groups the priced BOM actually contains (bill + add-ins), biggest
    $ first, mapped to a stencil. Compute is excluded (it's the VM boxes). Only real,
    present services — nothing invented. Returns [(stencil, label, monthly), ...]."""
    group_of = _cloud_group_of()
    totals = {}
    for r in (pricing or {}).get("rows", []):
        if (r.get("costAction") or "") == "remove":
            continue
        grp = _row_group(r, group_of)
        if not grp or grp == "Compute" or grp not in _SERVICE_STENCILS:
            continue
        totals[grp] = totals.get(grp, 0.0) + float(r.get("monthly") or 0)
    out = []
    for grp, mo in sorted(totals.items(), key=lambda kv: -kv[1]):
        if mo <= 0:
            continue
        stencil, label = _SERVICE_STENCILS[grp]
        out.append((stencil, label, mo))
    return out[:max_items]


# OCI database product -> (stencil, short label). Order matters: most specific first.
_DB_TYPE_STENCILS = [
    ("autonomous data warehouse", "Database - Autonomous Data Warehouse ADW", "Autonomous DW"),
    ("autonomous transaction",    "Database - Autonomous Transaction Processing ATP", "Autonomous TP"),
    ("autonomous",                "Database - ADB", "Autonomous DB"),
    ("exadata",                   "Database - Exadata", "Exadata"),
    ("exadb",                     "Database - Exadata", "Exadata"),
    ("goldengate",                "Database - GoldenGate", "GoldenGate"),
    ("nosql",                     "Database - NoSQL", "NoSQL"),
    ("mysql",                     "Database - MySQL", "MySQL / HeatWave"),
    ("postgres",                  "Database - Database System", "PostgreSQL"),
    ("sql server",                "Database - Database System", "SQL Server (on VM)"),
    ("base database",            "Database - Database System", "Base Database"),
    ("base db",                   "Database - Database System", "Base Database"),
]


def _db_dr_mechanism(label):
    """The correct DR / replication mechanism for a database type. Data Guard is
    Oracle-only — SQL Server on a VM uses OCI Full Stack DR, and the managed non-Oracle
    databases replicate cross-region their own way."""
    l = (label or "").lower()
    if "autonomous" in l:
        return "Autonomous Data Guard"
    if "goldengate" in l:
        return "GoldenGate replication"
    if "sql server" in l:
        return "OCI Full Stack DR"
    if "mysql" in l:
        return "MySQL cross-region replica"
    if "postgres" in l:
        return "PostgreSQL cross-region replica"
    if "nosql" in l:
        return "NoSQL cross-region replica"
    return "Data Guard"          # Oracle Base Database / Exadata


def collect_databases(pricing, max_items=5):
    """Split the priced Database spend by product TYPE -> [(stencil, label, monthly), ...]
    biggest $ first, so the diagram can show each managed-database type where it lives
    (Autonomous, Base DB, MySQL, Exadata, GoldenGate, SQL Server ...). Only present,
    priced databases; nothing invented."""
    group_of = _cloud_group_of()
    totals = {}
    for r in (pricing or {}).get("rows", []):
        if (r.get("costAction") or "") == "remove":
            continue
        if _row_group(r, group_of) != "Database":
            continue
        prod = _norm(r.get("ociProduct"))
        mo = sum(li.get("monthly", 0) for li in (r.get("lineItems") or [])) or float(r.get("monthly") or 0)
        stencil, label = "Database", "Database"
        for kw, st, lb in _DB_TYPE_STENCILS:
            if kw in prod:
                stencil, label = st, lb
                break
        key = (stencil, label)
        totals[key] = totals.get(key, 0.0) + mo
    out = [(st, lb, mo) for (st, lb), mo in sorted(totals.items(), key=lambda kv: -kv[1]) if mo > 0]
    return out[:max_items]


def service_group_totals(pricing):
    """Full {product-group: monthly$} map (no cap, includes Compute) so the diagram can
    decide which real services to place inside the architecture (databases in the data
    tier, KMS/monitoring in shared services, etc.). Only present, priced services."""
    group_of = _cloud_group_of()
    totals = {}
    for r in (pricing or {}).get("rows", []):
        if (r.get("costAction") or "") == "remove":
            continue
        grp = _row_group(r, group_of)
        if not grp:
            continue
        totals[grp] = totals.get(grp, 0.0) + float(r.get("monthly") or 0)
    return {g: m for g, m in totals.items() if m > 0}


# ---- layout grid (px) -------------------------------------------------------
REGION_X = 372
GW_X = 392          # gateway icon column, just inside the region's left edge
HUB_X = 486
HUB_W = 540
SPOKE_W = 760
GAP = 48
VCN_Y, VCN_H = 350, 880          # 350 .. 1230
DR_Y, DR_H = 1400, 700           # 1400 .. 2020


def build_spec(pricing, segments, bom_name="", shape_label="", segment_source="",
               sites=None, include_dr=True, diagram_options=None):
    """Full landing-zone architecture: internet + on-prem edge, hub VCN with DMZ /
    inspection / shared-services subnets, one spoke VCN per workload segment with app and
    data subnets, object-storage backup, and (optionally) a DR region.

    Everything numeric — VM counts, OCPU, RAM, storage, licensing, segment names, site
    counts — comes from the priced BOM and the uploaded inventory. Nothing is invented.
    Landing-zone components that carry no cost in this BOM are drawn as the target
    pattern and called out as such in the notes.
    """
    totals = (pricing or {}).get("totals", {}) or {}
    cust = bom_name or "Customer"
    n = max(1, len(segments))
    # Diagram options (region names + availability-domain split) from the app menu.
    _opts = diagram_options or {}
    primary_region = _region_label(_opts.get("primaryRegion"))
    dr_region = _region_label(_opts.get("drRegion"))
    # AD capability is authoritative from the region, not the client. A named region
    # gets its real AD count; only an unnamed/"Auto" region falls back to the hint.
    _region_key = _clean(_opts.get("primaryRegion"))
    if _region_key:
        region_ads = _region_ad_count(_region_key)
    else:
        region_ads = int(_opts.get("primaryAds") or 1)
    ad_split = bool(_opts.get("splitADs")) and region_ads > 1
    # Which resource types to physically split across availability domains (from the app's
    # AD-split chips). Default: both, so picking a multi-AD region + AD split just works.
    _adres = _opts.get("adSplitResources") or {}
    split_vms = ad_split and bool(_adres.get("vms", True))
    split_dbs = ad_split and bool(_adres.get("dbs", True))
    # Is a Full Stack DR add-in actually priced in this BOM?
    dr_priced = any(
        "full stack disaster recovery" in str(r.get("ociProduct", "")).lower()
        or "full stack dr" in str(r.get("ociProduct", "")).lower()
        for r in ((pricing or {}).get("rows") or [])
    )
    # DR is drawn only when the app's "Enable DR" toggle is on (falls back to include_dr
    # for older callers/tests that don't pass the option). When on, only the resource
    # types the user chose are replicated into the secondary region.
    dr_enabled = bool(_opts.get("enableDr")) if ("enableDr" in _opts) else include_dr
    _rep = _opts.get("drReplicate") or {}
    rep_vms = bool(_rep.get("vms", True))
    rep_dbs = bool(_rep.get("dbs", True))
    rep_obj = bool(_rep.get("object", True))

    # Mapped OCI services present in the BOM -> a second row of icons under the governance
    # band. Only shown when there's a real spread of services (cloud-bill imports); a lone
    # storage entry on an on-prem BOM is already represented by the VM/storage boxes.
    services = collect_services(pricing)
    if len(services) < 2:
        services = []
    SVC_DY = 190 if services else 0
    # Full presence map so real services can be placed WHERE they live in the topology:
    # databases + data-platform services in the spoke data subnets, KMS/monitoring/WAF in
    # the hub shared/edge tiers. Driven by the priced BOM (nothing invented).
    svc_present = service_group_totals(pricing)
    db_types = collect_databases(pricing)          # managed databases split by type
    _has_db = bool(db_types)
    _has_sec = svc_present.get("Security", 0) > 0
    _has_obs = svc_present.get("Obs. & Management", 0) > 0
    _has_ai = svc_present.get("AI & Machine Learning", 0) > 0
    _waf_present = any(
        "web application firewall" in _norm(r.get("ociProduct")) or "waf" in _norm(r.get("sourceService"))
        for r in (pricing or {}).get("rows", []) if (r.get("costAction") or "") != "remove")
    # FastConnect present anywhere in the priced BOM (bill line OR add-in) — the diagram
    # (incl. DR) must reflect dedicated FastConnect connectivity when the user prices it.
    _has_fc = any(
        "fastconnect" in _norm(r.get("ociProduct")) or "fast connect" in _norm(r.get("ociProduct"))
        or "fastconnect" in _norm(r.get("sourceService")) or "fast connect" in _norm(r.get("sourceService"))
        for r in (pricing or {}).get("rows", []) if (r.get("costAction") or "") != "remove")

    spoke_x0 = HUB_X + HUB_W + GAP
    content_r = spoke_x0 + n * (SPOKE_W + GAP) - GAP
    region_w = content_r - REGION_X + 40
    tenancy_w = region_w + 64
    bottom = (DR_Y + DR_H) if dr_enabled else (VCN_Y + VCN_H + 60)
    notes_y = bottom + 50                 # base position; the draw offset SVC_DY is added later
    page_h = notes_y + SVC_DY + 300
    page_w = REGION_X + region_w + 140

    C, N, E = [], [], []          # containers, nodes, edges
    dy = [0]                      # draw offset; bumped to SVC_DY for region content

    def box(i, label, x, y, w, h, style="plain"):
        C.append({"id": i, "label": label, "style": style, "x": x, "y": y + dy[0], "w": w, "h": h})

    def icon(i, shape, label, x, y, s=88):
        N.append({"id": i, "shape": shape, "label": label, "x": x, "y": y + dy[0], "w": s, "h": s})

    def text(i, s, x, y, w, h):
        N.append({"id": i, "text": s, "x": x, "y": y + dy[0], "w": w, "h": h})

    def link(a, b, label="", style="solid"):
        E.append({"source": a, "target": b, "label": label, "style": style})

    # ---- tenancy / governance band -----------------------------------------
    box("tenancy", f"{cust} OCI Tenancy", 340, 20, tenancy_w, page_h - 250, "tenancy")
    gov_band_h = 206 + (132 if services else 0)
    box("gov", "Landing zone compartments\nnetwork hub · workload spokes · shared services · security",
        REGION_X, 62, region_w, gov_band_h, "compartment")
    N.append({"id": "govttl", "text": "Common governance and regional services",
              "x": REGION_X + region_w // 2 - 240, "y": 74, "w": 480, "h": 20})

    gov_icons = [
        ("iam", "Identity and Security - Active Directory", "Federated IAM"),
        ("dns", "Networking - DNS", "Public DNS / GTM"),
        ("cg", "Identity and Security - Cloud Guard", "Cloud Guard"),
        ("log", "Observability and Management - Logging", "Logging"),
        ("mon", "Observability and Management - Monitoring", "Monitoring"),
        ("aud", "Observability and Management - Auditing", "Audit"),
        ("vault", "Identity and Security - Vault", "Vault keys"),
    ]
    step = region_w // (len(gov_icons) + 1)
    for i, (nid, shape, label) in enumerate(gov_icons):
        icon(nid, shape, label, REGION_X + step * (i + 1) - 44, 112)

    # ---- mapped OCI services (data-driven second row) ----------------------
    if services:
        text("svcttl", "OCI services mapped from this BOM",
             REGION_X + region_w // 2 - 200, 250, 400, 20)
        sstep = region_w // (len(services) + 1)
        for i, (shape, label, mo) in enumerate(services):
            icon(f"svc{i}", shape, f"{label}\n${mo:,.0f}/mo",
                 REGION_X + sstep * (i + 1) - 40, 276, 80)

    # Everything below (external actors, region, hub, spokes, DR, notes) shifts down to
    # clear the services band.
    dy[0] = SVC_DY

    # ---- external actors ----------------------------------------------------
    box("users", "Public users\nand partners", 28, 380, 220, 110, "external")
    box("onprem", f"{cust} on-prem estate\nsource inventory · WAN", 28, 560, 220, 130, "external")
    icon("cpe", "Networking - Customer Premises Equipment CPE", "Customer Premises\nEquipment",
         256, 690)
    if sites:
        box("sites", f"{sites:,} remote sites\nbranches · plants · offices", 28, 760, 220, 110,
            "external")
        link("sites", "cpe", "Site-to-Site VPN", "dashed")
    link("users", "igw", "HTTPS", "solid")
    link("onprem", "cpe", "WAN", "solid")
    link("cpe", "drg", "FastConnect (priced)" if _has_fc else "FastConnect / IPSec VPN", "solid")

    # ---- region + hub -------------------------------------------------------
    box("region",
        (f"Primary OCI Region{(' — ' + primary_region) if primary_region else ''}\n"
         f"{int(sum(s['vms'] for s in segments)):,} migrated VMs · "
         f"{totals.get('ocpus', 0):,.0f} OCPU · "
         f"{totals.get('memoryGb', 0):,.0f} GB RAM · "
         f"{totals.get('blockStorageGb', 0):,.0f} GB block storage"
         + (f"  ·  compute spread across {region_ads} availability domains" if ad_split else "")),
        REGION_X, 270, region_w, 1010, "region")

    box("hubvcn", "Hub VCN\n10.10.0.0/16 | DRG attachment", HUB_X, VCN_Y, HUB_W, VCN_H, "vcn")
    sx, sw = HUB_X + 28, HUB_W - 56
    box("hub_dmz", "Public / DMZ Ingress Subnet\n10.10.1.0/24", sx, 420, sw, 200, "subnet")
    box("hub_insp", "Private Routing + Inspection Subnet\n10.10.2.0/24", sx, 640, sw, 200, "subnet")
    box("hub_shared", "Shared Services Subnet\n10.10.3.0/24", sx, 860, sw, 220, "subnet")

    icon("igw", "Networking - Internet Gateway", "Internet\nGateway", GW_X - 12, 424)
    icon("natgw", "Networking - NAT Gateway", "NAT\nGateway", GW_X - 12, 644)
    icon("svcgw", "Networking - Service Gateway", "Service\nGateway", GW_X - 12, 864)

    icon("lb", "Networking - Flexible Load Balancer", "Public app\nload balancer",
         sx + sw // 2 - 44, 484)
    icon("fw", "Identity and Security - Firewall", "OCI Network\nFirewall", sx + sw // 2 - 44, 702)
    icon("bastion", "Identity and Security - Bastion", "Bastion /\nadmin access", sx + 36, 922)
    icon("pdns", "Networking - DNS", "Private DNS\nforwarding", sx + sw - 124, 922)
    icon("drg", "Networking - Dynamic Routing Gateway DRG", "Shared DRG\nhub-spoke transit",
         HUB_X + HUB_W // 2 - 44, 1092)
    # Real edge/shared services placed where they belong, driven by the BOM.
    if _waf_present:
        icon("waf", "Identity and Security - WAF",
             "Web Application\nFirewall (WAF)", sx + sw - 128, 484)
        link("waf", "lb", "Filter ingress", "solid")
    if _has_sec:
        icon("vault", "Identity and Security - Vault", "Vault / KMS",
             sx + sw // 2 - 44, 922)

    link("igw", "lb", "Ingress", "solid")
    link("lb", "fw", "Inspect", "solid")
    link("fw", "drg", "Routed inspection", "solid")
    link("dns", "lb", "DNS lookup", "dashed")

    # ---- workload spokes ----------------------------------------------------
    for i, seg in enumerate(segments):
        x = spoke_x0 + i * (SPOKE_W + GAP)
        sid = f"s{i}"
        third = 20 + 10 * i
        ax, aw = x + 24, SPOKE_W - 48
        box(f"{sid}vcn",
            f"{seg['name']} Spoke VCN\n10.{third}.0.0/16 | DRG attachment",
            x, VCN_Y, SPOKE_W, VCN_H, "vcn")
        if ad_split:
            # ---- AD layout: EVERY compute/DB object lives inside an Availability Domain box.
            #      Multiple ADs when a resource type is split across them; otherwise ONE big AD.
            #      Databases are never left floating outside an AD. ----
            multi = split_vms or split_dbs
            n_ad = region_ads if multi else 1
            adw = aw // n_ad
            ad_top, ad_bottom = 415, 1005
            win_vms = int(seg.get("winvms", 0))
            reg_vms = max(0, int(seg["vms"]) - win_vms)     # regular (non-Windows) VMs
            # Distribute the databases across the AD(s). SQL Server DBs are grouped together;
            # every other DB type is spread round-robin. Even when DBs aren't "split" they still
            # sit INSIDE an AD (one big AD, or spread across the VM ADs).
            ad_dbs = [[] for _ in range(n_ad)]
            if db_types:
                sql_dbs = [d for d in db_types if "sql" in _norm(d[1])]
                other_dbs = [d for d in db_types if "sql" not in _norm(d[1])]
                if n_ad == 1:
                    db_ads = [0]
                elif split_dbs and not split_vms:
                    db_ads = list(range(1, n_ad))            # keep DBs out of the VM-only AD 1
                else:
                    db_ads = list(range(n_ad))
                for idx, d in enumerate(other_dbs):
                    ad_dbs[db_ads[idx % len(db_ads)]].append(d)
                if sql_dbs:
                    ad_dbs[db_ads[0]] = sql_dbs + ad_dbs[db_ads[0]]
            for j in range(n_ad):
                adx = ax + j * adw
                # When VMs aren't split, the AD header only carries capacity for the split
                # resources; the whole compute footprint lives in AD 1 (the main AD).
                _cap = (f"{seg['ocpu']/n_ad:,.0f} OCPU · {seg['ram']/n_ad:,.0f} GB · fault-isolated"
                        if split_vms else "fault-isolated")
                _adname = f"Availability Domain {j+1}" if multi else "Availability Domain"
                box(f"{sid}ad{j}", f"{_adname}\n{_cap}",
                    adx + 3, ad_top, adw - 6, ad_bottom - ad_top, "ad")
                yy = ad_top + 56
                if split_vms:
                    icon(f"{sid}vm{j}", "Compute - Virtual Machine VM",
                         f"{_even_share(reg_vms, n_ad, j):,} VMs", adx + adw // 2 - 30, yy, 60)
                    link("drg", f"{sid}vm{j}", "AD transit", "solid")
                    yy += 104
                    if win_vms > 0:
                        icon(f"{sid}winvm{j}", "Compute - Virtual Machine VM",
                             f"{_even_share(win_vms, n_ad, j):,} Windows VMs\n${seg['win']/n_ad:,.0f}/mo",
                             adx + adw // 2 - 30, yy, 60)
                        yy += 110
                elif j == 0:
                    # VMs NOT split -> the entire compute footprint sits in the main AD (AD 1).
                    icon(f"{sid}vm", "Compute - Virtual Machine VM",
                         f"{reg_vms:,} {seg['name']} VMs\n{seg['ocpu']:,.0f} OCPU · {seg['ram']:,.0f} GB",
                         adx + adw // 2 - 30, yy, 60)
                    link("drg", f"{sid}vm", "Hub-spoke transit", "solid")
                    yy += 104
                    if win_vms > 0:
                        icon(f"{sid}winvm", "Compute - Virtual Machine VM",
                             f"{win_vms:,} Windows VMs\n${seg['win']:,.0f}/mo licensing",
                             adx + adw // 2 - 30, yy, 60)
                        link("drg", f"{sid}winvm", "Hub-spoke transit", "solid")
                        yy += 110
                # Databases INSIDE the AD: one big AD lays them in a row (uses the full width);
                # narrow split ADs stack them below the VMs.
                dbs = ad_dbs[j]
                if n_ad == 1 and dbs:
                    dcw = adw // len(dbs)
                    for di, (stencil, label, mo) in enumerate(dbs):
                        icon(f"{sid}ad{j}db{di}", stencil, f"{label}\n${mo:,.0f}/mo",
                             adx + di * dcw + (dcw - 60) // 2, yy, 60)
                else:
                    for di, (stencil, label, mo) in enumerate(dbs):
                        icon(f"{sid}ad{j}db{di}", stencil, f"{label}\n${mo:,.0f}/mo",
                             adx + adw // 2 - 30, yy, 60)
                        yy += 96
            icon(f"{sid}bkt", "Storage - Object Storage",
                 f"{seg['name']} backup bucket\nObject Storage",
                 ax + aw // 2 - 44, VCN_Y + VCN_H - 116, 84)
        else:
            # ---- single layout (no AD split) ----
            box(f"{sid}_app", f"{seg['name']} Private App Subnet\n10.{third}.1.0/24",
                ax, 420, aw, 280, "subnet")
            box(f"{sid}_data", f"{seg['name']} Private Data / Storage Subnet\n10.{third}.2.0/24",
                ax, 720, aw, 280, "subnet")
            _wv = int(seg.get("winvms", 0))
            _rv = max(0, int(seg["vms"]) - _wv)     # regular (non-Windows) VMs
            icon(f"{sid}vm", "Compute - Virtual Machine VM",
                 (f"{_rv:,} {seg['name']} VMs\n"
                  f"{seg['ocpu']:,.0f} OCPU · {seg['ram']:,.0f} GB RAM"
                  + (f"\n{shape_label} flex" if shape_label else "")),
                 ax + 60, 500, 96)
            # Windows-licensed servers are their own VM image (not a standalone license icon).
            if _wv > 0:
                icon(f"{sid}winvm", "Compute - Virtual Machine VM",
                     f"{_wv:,} Windows VMs\n${seg['win']:,.0f}/mo licensing",
                     ax + aw - 156, 500, 96)
                link("drg", f"{sid}winvm", "Hub-spoke transit", "solid")
            if db_types:
                n = len(db_types)
                per_row = min(3, n)
                nrows = (n + per_row - 1) // per_row
                avail = aw - 170
                cellw = avail // per_row
                dsz = 84 if n <= 3 else 68
                y0 = 800 if nrows == 1 else 758
                for k, (stencil, label, mo) in enumerate(db_types):
                    col, row = k % per_row, k // per_row
                    cx = ax + 20 + col * cellw + (cellw - dsz) // 2
                    nid = f"{sid}db{k}"
                    icon(nid, stencil, f"{label}\n${mo:,.0f}/mo", cx, y0 + row * 116, dsz)
                    if k == 0:
                        link(f"{sid}vm", nid, "App -> DB", "solid")
            icon(f"{sid}bkt", "Storage - Object Storage",
                 f"{seg['name']} backup bucket\nObject Storage",
                 ax + aw // 2 - 44, VCN_Y + VCN_H - 130, 88)
            link("drg", f"{sid}vm", "Hub-spoke transit", "solid")
        # The attached block volume needs no backup edge — backups live at the DR site.

    # ---- DR region (only when the app's Enable DR toggle is on) --------------
    if dr_enabled:
        _rep_bits = []
        if rep_vms: _rep_bits.append("compute standbys")
        if rep_dbs: _rep_bits.append("database replicas")
        if rep_obj: _rep_bits.append("object / block backups")
        _rep_txt = ", ".join(_rep_bits) if _rep_bits else "region shell only"
        _dr_head = f"Secondary OCI Region for DR{(' — ' + dr_region) if dr_region else ''}"
        _dr_sub = (f"Replicating: {_rep_txt}"
                   + ("  ·  Full Stack DR priced in this BOM"
                      if dr_priced else
                      "  ·  target pattern (add Full Stack DR to cost it)"))
        box("drregion",
            f"{_dr_head}\n{_dr_sub}",
            REGION_X, DR_Y, region_w, DR_H, "region")
        box("drhub", "DR Landing Zone / Orchestration VCN\n10.110.0.0/16 | DRG + remote peering",
            HUB_X, DR_Y + 90, HUB_W, DR_H - 150, "vcn")
        box("drorch", "OCI Full Stack DR orchestration",
            HUB_X + 28, DR_Y + 150, HUB_W - 56, 190, "plain")
        # Orchestration bullets reflect what's ACTUALLY priced/selected — so an added
        # FastConnect port or a managed DB (bill or add-in) shows up here, not a fixed list.
        _dr_bullets = ["DR protection groups per workload spoke",
                       "Prechecks, drills and switchover / failover plans"]
        if rep_obj:
            _dr_bullets.append("Block Volume + Object Storage cross-region copy")
        if rep_dbs and _has_db:
            _dr_bullets.append("Managed-database replication (Data Guard / cross-region replicas)")
        if _has_fc:
            _dr_bullets.append("Dedicated FastConnect connectivity into the DR region")
        for j, t in enumerate(_dr_bullets):
            text(f"dro{j}", "· " + t, HUB_X + 48, DR_Y + 196 + j * 30, HUB_W - 96, 24)
        icon("drdrg", "Networking - Remote Peering Gateway", "DR DRG\nremote peering",
             HUB_X + HUB_W // 2 - 44, DR_Y + 470)
        link("drg", "drdrg", "DRG remote peering / DR routing", "dashed")
        # When FastConnect is priced, the customer edge reaches the DR region over
        # FastConnect too — draw that so DR reflects the added connectivity.
        if _has_fc:
            link("cpe", "drdrg", "FastConnect to DR region", "solid")

        for i, seg in enumerate(segments):
            x = spoke_x0 + i * (SPOKE_W + GAP)
            sid = f"s{i}"
            third = 120 + 10 * i
            ax, aw = x + 24, SPOKE_W - 48
            box(f"{sid}drvcn", f"{seg['name']} DR Spoke VCN\n10.{third}.0.0/16 | DRG attachment",
                x, DR_Y + 90, SPOKE_W, DR_H - 150, "vcn")
            # Only the resource types the user chose to replicate are drawn in the DR
            # region. Compute standbys, managed-DB replicas, and object/block backups are
            # each independently gated by the app's "Replicate to DR" selection.
            db_slots = db_types[:6] if (rep_dbs and db_types) else []
            if ad_split and (rep_vms or db_slots):
                # ---- DR standby objects live inside an Availability Domain too (one big AD).
                #      Regional object/block backups stay OUTSIDE the AD (they aren't AD-bound). ----
                ad_x, ad_y, ad_w, ad_h = ax, DR_Y + 150, aw, 360
                box(f"{sid}drad", "Availability Domain 1\nDR standby · fault-isolated",
                    ad_x, ad_y, ad_w, ad_h, "ad")
                yy = ad_y + 60
                _dbx0 = ad_x + 20
                _dbcols = 3
                if rep_vms:
                    icon(f"{sid}drvm", "Compute - Virtual Machine VM",
                         f"{seg['vms']:,} {seg['name']}\nstandby VMs", ad_x + 40, yy, 88)
                    link("drdrg", f"{sid}drvm", "DR transit", "dashed")
                    _dbx0 = ad_x + 210      # DB replicas sit to the right of the standby VMs
                    _dbcols = 2             # fewer, wider columns so the long DR labels fit
                if db_slots:
                    percol = min(_dbcols, len(db_slots))
                    avail = (ad_x + ad_w - 20) - _dbx0
                    cw = max(120, avail // percol)
                    for k, (stencil, label, mo) in enumerate(db_slots):
                        col, row = k % percol, k // percol
                        cx = _dbx0 + col * cw + (cw - 56) // 2
                        icon(f"{sid}drdb{k}", stencil,
                             f"(Opt.) {label}\n{_db_dr_mechanism(label)}",
                             cx, yy + row * 106, 56)
                if rep_obj:
                    icon(f"{sid}drbkt", "Storage - Object Storage",
                         f"{seg['name']} DR target\nbucket", ax + 56, ad_y + ad_h + 22, 84)
                    icon(f"{sid}drblk", "Storage - Block Storage",
                         f"(Opt.) block backups\n{seg['block']:,.0f} GB", ax + aw - 156, ad_y + ad_h + 22, 84)
                    link(f"{sid}bkt", f"{sid}drbkt", "Cross-region bucket replication", "backup")
            else:
                # ---- DR subnet layout (AD feature off) ----
                box(f"{sid}dr_app", f"{seg['name']} DR App Subnet\n10.{third}.1.0/24",
                    ax, DR_Y + 150, aw, 200, "subnet")
                box(f"{sid}dr_data", f"{seg['name']} DR Data / Restore Subnet\n10.{third}.2.0/24",
                    ax, DR_Y + 380, aw, 250, "subnet")
                if rep_vms:
                    icon(f"{sid}drvm", "Compute - Virtual Machine VM",
                         f"{seg['vms']:,} {seg['name']}\nstandby VMs", ax + 56, DR_Y + 212, 88)
                    link("drdrg", f"{sid}drvm", "DR transit", "dashed")
                if db_slots:
                    nd = len(db_slots)
                    pr = min(3, nd)
                    avail = aw - (150 if rep_obj else 40)   # reserve right margin for backups
                    cw = avail // pr
                    for k, (stencil, label, mo) in enumerate(db_slots):
                        col, row = k % pr, k // pr
                        cx = ax + 14 + col * cw + (cw - 56) // 2
                        icon(f"{sid}drdb{k}", stencil,
                             f"(Opt.) {label}\n{_db_dr_mechanism(label)}",
                             cx, DR_Y + 412 + row * 106, 56)
                if rep_obj:
                    if db_slots:
                        icon(f"{sid}drbkt", "Storage - Object Storage",
                             "DR target\nbucket", ax + aw - 118, DR_Y + 412, 64)
                        icon(f"{sid}drblk", "Storage - Block Storage",
                             f"(Opt.) block\nbackups {seg['block']:,.0f} GB",
                             ax + aw - 118, DR_Y + 520, 64)
                    else:
                        icon(f"{sid}drblk", "Storage - Block Storage",
                             f"(Optional) Backups\n{seg['block']:,.0f} GB", ax + 56, DR_Y + 442, 88)
                        icon(f"{sid}drbkt", "Storage - Object Storage",
                             f"{seg['name']} DR target\nbucket", ax + aw - 144, DR_Y + 442, 88)
                    link(f"{sid}bkt", f"{sid}drbkt", "Cross-region bucket replication", "backup")

    # ---- notes --------------------------------------------------------------
    win_total = sum(s["win"] for s in segments)
    seg_src = {"tier": "Tier", "env": "Environment", "os_family": "OS family",
               "app": "Application"}.get(segment_source, segment_source or "OS family")
    box("notes", "Notes and assumptions — everything numeric on this page comes from the "
                 "uploaded inventory and the priced BOM", REGION_X, notes_y, region_w, 240, "note")
    notes = [
        "Sizing: OCPU = vCPU / 2 for virtual rows; physical rows map 1 core = 1 OCPU. "
        "Memory and block storage carry over from the source inventory, at 10 VPUs/GB.",
        (f"Windows licensing is a separate 3rd-party line (${win_total:,.0f}/mo). The app's Hide "
         "Windows toggle removes it from both the BOM and this diagram."
         if win_total > 0 else
         "No Windows OS licensing is priced here (no Windows workloads, or licensing is excluded)."),
        f"Workloads are split into {n} spoke VCN(s) using the inventory's own {seg_src} column. "
        "Add a Tier / Environment column to split them further.",
        "Hub networking, Security/KMS, DR and backup capacity carry NO cost in this BOM — the "
        "source inventory has no data for them. They are the target pattern, not costed lines.",
        ("Remote sites come from the inventory's site / location column."
         if sites else
         "No site / location column was found, so no site-to-region topology is drawn."),
    ]
    for i, note_line in enumerate(notes):
        text(f"n{i}", note_line, REGION_X + 28, notes_y + 52 + i * 38, region_w - 60, 26)

    return {
        "title": f"{cust} OCI Target Architecture — derived from the priced BOM",
        "page": {"width": page_w, "height": page_h},
        "containers": C, "nodes": N, "edges": E,
    }


def render(spec, out_dir, name="oci_architecture"):
    """Render the spec to .drawio + .png. Returns (drawio_path, png_path|None)."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    import build_diagram  # vendored from the oci-architecture-diagrams skill

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_path = out_dir / f"{name}_spec.json"
    spec_path.write_text(json.dumps(spec, indent=2))
    drawio = out_dir / f"{name}.drawio"
    png = out_dir / f"{name}.png"
    try:
        build_diagram.build(str(spec_path), str(drawio), str(png), str(LIB_PATH))
    except Exception as exc:
        # The PNG raster needs pycairo (system cairo libs). The .drawio still builds.
        import sys as _sys
        if isinstance(exc, ModuleNotFoundError) and "cairo" in str(exc):
            print("=" * 72, file=_sys.stderr)
            print("[diagram] PNG not rendered: pycairo is not installed in this Python "
                  f"({_sys.executable}).", file=_sys.stderr)
            print("[diagram] Install it to get the rendered diagram:", file=_sys.stderr)
            print("[diagram]     macOS:  brew install cairo pkg-config && "
                  f"{_sys.executable} -m pip install pycairo", file=_sys.stderr)
            print("[diagram]     Linux:  apt-get install -y libcairo2-dev && "
                  f"{_sys.executable} -m pip install pycairo", file=_sys.stderr)
            print("[diagram] The editable .drawio is still produced.", file=_sys.stderr)
            print("=" * 72, file=_sys.stderr)
        else:
            import traceback
            traceback.print_exc()
        build_diagram.build(str(spec_path), str(drawio), None, str(LIB_PATH))
        png = None
    return drawio, (png if png and png.exists() else None)


OCI_REGION_LABELS = {
    "us-ashburn-1": "US East (Ashburn)", "us-phoenix-1": "US West (Phoenix)",
    "us-chicago-1": "US Midwest (Chicago)", "us-sanjose-1": "US West (San Jose)",
    "ca-toronto-1": "Canada Southeast (Toronto)", "ca-montreal-1": "Canada Southeast (Montreal)",
    "sa-saopaulo-1": "Brazil East (São Paulo)", "eu-frankfurt-1": "Germany Central (Frankfurt)",
    "uk-london-1": "UK South (London)", "eu-amsterdam-1": "Netherlands NW (Amsterdam)",
    "eu-zurich-1": "Switzerland North (Zurich)", "eu-paris-1": "France Central (Paris)",
    "eu-madrid-1": "Spain Central (Madrid)", "ap-tokyo-1": "Japan East (Tokyo)",
    "ap-osaka-1": "Japan Central (Osaka)", "ap-seoul-1": "South Korea Central (Seoul)",
    "ap-singapore-1": "Singapore", "ap-sydney-1": "Australia East (Sydney)",
    "ap-mumbai-1": "India West (Mumbai)", "me-dubai-1": "UAE East (Dubai)",
    "me-jeddah-1": "Saudi Arabia West (Jeddah)",
}


# Authoritative availability-domain count per commercial OCI region. Only these
# multi-AD regions can spread compute across ADs; everything else is single-AD, so
# an AD split is physically impossible there and must be refused server-side.
OCI_REGION_ADS = {
    "us-ashburn-1": 3, "us-phoenix-1": 3, "uk-london-1": 3, "eu-frankfurt-1": 3,
}


def _region_ad_count(key):
    """AD count for a named region (defaults to 1 for single-AD/unknown regions)."""
    return OCI_REGION_ADS.get(_clean(key), 1)


def _region_label(key):
    key = _clean(key)
    return f"{OCI_REGION_LABELS.get(key, key)} ({key})" if key else ""


def build_architecture(pricing, rows, fields_keys, bom_name="", shape_label="", out_dir=None,
                       sites=None, extra_priced=None, diagram_options=None):
    """Convenience: BOM -> segments -> spec -> (drawio, png). Returns (drawio, png).

    `sites` is the number of DISTINCT sites found in the inventory's site/location column,
    or None when the inventory has no such column — in which case the diagram says so
    rather than drawing sites that don't exist.
    `extra_priced` is the priced 'Add OCI services' list (oci_catalog.price_extras output);
    it's folded into the pricing the diagram reads so the picture matches the whole BOM.
    """
    segments = collect_segments(pricing, rows, fields_keys)
    if not segments:
        return None, None
    if extra_priced:
        pricing = dict(pricing or {})
        pricing["rows"] = list(pricing.get("rows") or []) + _addins_as_rows(extra_priced)
    spec = build_spec(pricing, segments, bom_name, shape_label,
                      segment_source=segment_source(rows, fields_keys), sites=sites,
                      diagram_options=diagram_options or {})
    out_dir = out_dir or tempfile.mkdtemp(prefix="ocidiag_")
    return render(spec, out_dir, name="oci_architecture")


# ---------------------------------------------------------------------------
# Site / region topology  (sites -> OCI regions, DRG/VCN/VPN/FastConnect + costs)
# ---------------------------------------------------------------------------
def load_site_regions(path):
    """Customer sites grouped by target OCI region. `path` is REQUIRED — there is no
    repo-default site file, because site data is customer-specific and must never be
    picked up implicitly for a different customer's BOM."""
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except Exception:
        return []
    return data.get("regions") or []


def _network_cost_block():
    """Networking rates for the topology's cost panel, taken from the app's OCI price
    data — never from memory. On OCI the DRG/VCN/subnets/VPN/gateways are free; the only
    recurring charges are FastConnect ports and egress beyond the 10 TB/month allowance."""
    block = {"hours_mo": 730, "fastconnect_port_hr": 1.275,
             "egress_free_tb": 10, "egress_per_gb": 0.0085}
    try:
        svc = json.loads((Path(__file__).resolve().parent / "data"
                          / "oci_service_prices.json").read_text()).get("services", {})
        fc = svc.get("OCI FastConnect") or {}
        rates = fc.get("speedRates") or {}
        if rates.get("10G"):
            block["fastconnect_port_hr"] = float(rates["10G"])
        dt = svc.get("OCI Outbound Data Transfer") or {}
        if dt.get("rate"):
            block["egress_per_gb"] = float(dt["rate"])
    except Exception:
        pass
    return block


def topology_spec_from_sites(regions, title="", subtitle=""):
    """Adapt data/customer_sites.json into the topology renderer's spec (a dict with a
    regions list). Regions sharing a regionId are merged by the renderer into ONE region
    card (one DRG, one VCN) — the correct picture — so don't pre-merge here.
    """
    out = []
    for r in regions:
        hub = r.get("vpnHub") or {}
        anchor = r.get("anchorServices")
        if isinstance(anchor, (list, tuple)):
            anchor = " · ".join(_clean(a) for a in anchor if _clean(a))
        entry = {
            "area": _clean(r.get("area")),
            "oci": _clean(r.get("ociRegion")),
            "rid": _clean(r.get("regionId")),
            "vcn": _clean(r.get("vcnCidr")),
            "hub": {
                "name": _clean(hub.get("name")),
                "sub": _clean(hub.get("detail") or hub.get("role")),
                # A conn string starting with "FastConnect" makes the renderer draw a
                # solid teal link with the $/mo label; anything else renders as VPN.
                "conn": _clean(hub.get("connection")),
            },
            # customer_sites.json stores spokes as {"name","role"}; the renderer wants pairs.
            "spokes": [[_clean(s.get("name") or s.get("site")), _clean(s.get("role"))]
                       for s in (r.get("spokes") or [])
                       if _clean(s.get("name") or s.get("site"))],
        }
        if anchor:
            entry["anchor"] = _clean(anchor)
        if r.get("sftpgo"):
            entry["sftpgo"] = True
        out.append(entry)

    return {
        "name": "oci_topology",
        "title": title or "Global Network Connectivity — Customer Sites to OCI Regions",
        "subtitle": subtitle or ("Site-to-Site VPN & FastConnect into regional DRG/VCN, "
                                 "interconnected over the OCI backbone (DRG remote peering)"),
        "backbone_label": "OCI Backbone · DRG Remote Peering",
        "width": 1840,
        "sites_width": 760,
        "show_legend": True,
        "cost": _network_cost_block(),
        "regions": out,
    }


def render_topology(regions, out_dir, name="oci_topology", limit=None, legend=True,
                    title="", subtitle=""):
    """Render the sites->regions topology (PNG + SVG + editable .drawio). Needs pycairo."""
    if not regions:
        return None, None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_path = out_dir / f"{name}_spec.json"
    spec = topology_spec_from_sites(regions, title, subtitle)
    spec["name"] = name
    spec_path.write_text(json.dumps(spec, indent=2))

    import subprocess
    cmd = [sys.executable, str(SCRIPTS_DIR / "topology.py"), str(spec_path),
           "--out", str(out_dir), "--name", name,
           "--icons", str(ICONS_PATH)]
    if limit:
        cmd += ["--limit", str(limit)]
    if not legend:
        cmd += ["--no-legend"]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=240)
    except Exception:
        return None, None   # pycairo not installed -> skip topology, don't fail the export
    png = out_dir / f"{name}.png"
    drawio = out_dir / f"{name}.drawio"
    return (drawio if drawio.exists() else None), (png if png.exists() else None)


def build_all(pricing, rows, fields_keys, bom_name="", shape_label="", out_dir=None,
              sites_path=None, sites=None):
    """Build the architecture artifacts the CURRENT BOM's data actually supports.

    - Landing-zone architecture <- the priced BOM (always, if there are workloads).
    - Site/region topology      <- ONLY when caller passes `sites_path` for THIS customer.

    NOTE: the topology is deliberately NOT auto-loaded from data/customer_sites.json.
    That file belongs to whichever customer it was built for, and silently rendering it
    beside a different customer's BOM puts one client's sites in another client's
    deliverable. A topology requires site data; an inventory with no site/location/region
    column (most VM exports, e.g. RVTools) simply has none, and we draw nothing rather
    than borrow someone else's.

    Returns {"architecture": (drawio, png), "topology": (drawio, png)}, None where absent.
    Deterministic; no model calls.
    """
    out_dir = Path(out_dir or tempfile.mkdtemp(prefix="ocidiag_"))
    result = {"architecture": (None, None), "topology": (None, None)}

    try:
        result["architecture"] = build_architecture(
            pricing, rows, fields_keys, bom_name, shape_label, out_dir, sites=sites)
    except Exception:
        pass

    if sites_path:                       # explicit opt-in only — never a repo default
        try:
            regions = load_site_regions(sites_path)
            if regions:
                result["topology"] = render_topology(regions, out_dir)
        except Exception:
            pass

    return result
