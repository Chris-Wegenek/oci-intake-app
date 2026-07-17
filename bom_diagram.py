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
        s = segs.setdefault(name, {"name": name, "vms": 0, "ocpu": 0.0, "ram": 0.0,
                                   "block": 0.0, "win": 0.0})
        s["vms"] += 1
        s["ocpu"] += float(specs.get("ocpus") or 0)
        s["ram"] += float(specs.get("memoryGb") or 0)
        s["block"] += float(specs.get("blockStorageGb") or 0)
        s["win"] += float(p.get("windowsLicenseMonthly") or 0)

    out = sorted(segs.values(), key=lambda s: -s["vms"])
    if len(out) > MAX_SPOKES:                       # fold the tail into one "Other" spoke
        head, tail = out[:MAX_SPOKES - 1], out[MAX_SPOKES - 1:]
        merged = {"name": "Other workloads", "vms": 0, "ocpu": 0.0, "ram": 0.0,
                  "block": 0.0, "win": 0.0}
        for t in tail:
            for k in ("vms", "ocpu", "ram", "block", "win"):
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


def collect_services(pricing, max_items=8):
    """Which OCI service groups the priced BOM actually contains, biggest $ first, mapped to
    a stencil. Compute is excluded (it's the VM boxes). Only real, present services — nothing
    invented. Returns [(stencil, label, monthly), ...]."""
    try:
        import bom_export
        group_of = bom_export._cloud_product_group
    except Exception:
        group_of = None
    totals = {}
    for r in (pricing or {}).get("rows", []):
        if (r.get("costAction") or "") == "remove":
            continue
        cat = _clean(r.get("ociServiceCategory"))
        grp = group_of(cat, r.get("sourceService")) if group_of else (cat or "")
        if not grp or grp == "Compute":
            continue
        if grp not in _SERVICE_STENCILS:
            continue
        totals[grp] = totals.get(grp, 0.0) + float(r.get("monthly") or 0)
    out = []
    for grp, mo in sorted(totals.items(), key=lambda kv: -kv[1]):
        if mo <= 0:
            continue
        stencil, label = _SERVICE_STENCILS[grp]
        out.append((stencil, label, mo))
    return out[:max_items]


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
               sites=None, include_dr=True):
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

    # Mapped OCI services present in the BOM -> a second row of icons under the governance
    # band. Only shown when there's a real spread of services (cloud-bill imports); a lone
    # storage entry on an on-prem BOM is already represented by the VM/storage boxes.
    services = collect_services(pricing)
    if len(services) < 2:
        services = []
    SVC_DY = 190 if services else 0

    spoke_x0 = HUB_X + HUB_W + GAP
    content_r = spoke_x0 + n * (SPOKE_W + GAP) - GAP
    region_w = content_r - REGION_X + 40
    tenancy_w = region_w + 64
    bottom = (DR_Y + DR_H) if include_dr else (VCN_Y + VCN_H + 60)
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
    link("cpe", "drg", "FastConnect / IPSec VPN", "solid")

    # ---- region + hub -------------------------------------------------------
    box("region",
        ("Primary OCI Region\n"
         f"{int(sum(s['vms'] for s in segments)):,} migrated VMs · "
         f"{totals.get('ocpus', 0):,.0f} OCPU · "
         f"{totals.get('memoryGb', 0):,.0f} GB RAM · "
         f"{totals.get('blockStorageGb', 0):,.0f} GB block storage"),
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
        box(f"{sid}_app", f"{seg['name']} Private App Subnet\n10.{third}.1.0/24",
            ax, 420, aw, 280, "subnet")
        box(f"{sid}_data", f"{seg['name']} Private Data / Storage Subnet\n10.{third}.2.0/24",
            ax, 720, aw, 280, "subnet")

        icon(f"{sid}vm", "Compute - Virtual Machine VM",
             (f"{seg['vms']:,} {seg['name']} VMs\n"
              f"{seg['ocpu']:,.0f} OCPU · {seg['ram']:,.0f} GB RAM"
              + (f"\n{shape_label} flex" if shape_label else "")),
             ax + 60, 500, 96)
        # Attached block volumes are part of the VM — not drawn as a separate icon.
        if seg["win"] > 0:
            icon(f"{sid}lic", "Governance and Administration - License Manager",
                 f"Windows OS licensing\n${seg['win']:,.0f}/mo (3rd-party)",
                 ax + aw - 156, 500, 96)
        # Local backup bucket in the data/storage subnet.
        icon(f"{sid}bkt", "Storage - Object Storage",
             f"{seg['name']} backup bucket\nObject Storage", ax + 60, 800, 96)

        link("drg", f"{sid}vm", "Hub-spoke transit", "solid")
        # The attached block volume needs no backup edge — backups live at the DR site.

    # ---- DR region (target pattern; not priced in this BOM) ------------------
    if include_dr:
        box("drregion",
            "Secondary OCI Region for DR — target landing-zone pattern\n"
            "NOT priced in this BOM (no DR requirement in the source inventory)",
            REGION_X, DR_Y, region_w, DR_H, "region")
        box("drhub", "DR Landing Zone / Orchestration VCN\n10.110.0.0/16 | DRG + remote peering",
            HUB_X, DR_Y + 90, HUB_W, DR_H - 150, "vcn")
        box("drorch", "OCI Full Stack DR orchestration",
            HUB_X + 28, DR_Y + 150, HUB_W - 56, 190, "plain")
        for j, t in enumerate([
                "DR protection groups per workload spoke",
                "Prechecks, drills and switchover / failover plans",
                "Block Volume + Object Storage cross-region copy",
                "Database replication where a database is in scope"]):
            text(f"dro{j}", "· " + t, HUB_X + 48, DR_Y + 196 + j * 30, HUB_W - 96, 24)
        icon("drdrg", "Networking - Remote Peering Gateway", "DR DRG\nremote peering",
             HUB_X + HUB_W // 2 - 44, DR_Y + 470)
        link("drg", "drdrg", "DRG remote peering / DR routing", "dashed")

        for i, seg in enumerate(segments):
            x = spoke_x0 + i * (SPOKE_W + GAP)
            sid = f"s{i}"
            third = 120 + 10 * i
            ax, aw = x + 24, SPOKE_W - 48
            box(f"{sid}drvcn", f"{seg['name']} DR Spoke VCN\n10.{third}.0.0/16 | DRG attachment",
                x, DR_Y + 90, SPOKE_W, DR_H - 150, "vcn")
            box(f"{sid}dr_app", f"{seg['name']} DR App Subnet\n10.{third}.1.0/24",
                ax, DR_Y + 150, aw, 200, "subnet")
            box(f"{sid}dr_data", f"{seg['name']} DR Data / Restore Subnet\n10.{third}.2.0/24",
                ax, DR_Y + 380, aw, 200, "subnet")
            icon(f"{sid}drvm", "Compute - Virtual Machine VM",
                 f"{seg['vms']:,} {seg['name']}\nstandby VMs", ax + 56, DR_Y + 212, 88)
            # The block-volume capacity is shown here as optional DR backups, not as a
            # priced primary-region tier.
            icon(f"{sid}drblk", "Storage - Block Storage",
                 f"(Optional) Backups\n{seg['block']:,.0f} GB", ax + 56, DR_Y + 442, 88)
            icon(f"{sid}drbkt", "Storage - Object Storage",
                 f"{seg['name']} DR target\nbucket", ax + aw - 144, DR_Y + 442, 88)
            link(f"{sid}bkt", f"{sid}drbkt", "Cross-region bucket replication", "backup")
            link("drdrg", f"{sid}drvm", "DR transit", "dashed")

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


def build_architecture(pricing, rows, fields_keys, bom_name="", shape_label="", out_dir=None,
                       sites=None):
    """Convenience: BOM -> segments -> spec -> (drawio, png). Returns (drawio, png).

    `sites` is the number of DISTINCT sites found in the inventory's site/location column,
    or None when the inventory has no such column — in which case the diagram says so
    rather than drawing sites that don't exist.
    """
    segments = collect_segments(pricing, rows, fields_keys)
    if not segments:
        return None, None
    spec = build_spec(pricing, segments, bom_name, shape_label,
                      segment_source=segment_source(rows, fields_keys), sites=sites)
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
