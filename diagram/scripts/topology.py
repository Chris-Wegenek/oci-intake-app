#!/usr/bin/env python3
"""
Hub-and-spoke cloud topology renderer.

Reads a JSON topology spec, builds an intermediate *display list*, then emits
the SAME coordinates three ways:
    <out>.png    high-res raster   (pycairo ImageSurface, 2x)
    <out>.svg    vector            (pycairo SVGSurface)
    <out>.drawio editable diagram  (mxGraph XML; icons inlined as SVG data URIs)

Usage:
    python3 topology.py spec.json [--out DIR] [--name BASE]
                                  [--icons assets/icons_data.json]
                                  [--limit N] [--no-legend]

Design notes live in ../reference/layout_playbook.md.
"""
import json, math, cairo, urllib.parse, html, os, argparse

# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
ap = argparse.ArgumentParser()
ap.add_argument("spec")
ap.add_argument("--out", default=".")
ap.add_argument("--name", default=None)
ap.add_argument("--icons", default=None)
ap.add_argument("--limit", type=int, default=0, help="render only first N regions (0 = all)")
ap.add_argument("--no-legend", action="store_true")
A = ap.parse_args()

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = json.load(open(A.spec))
ICONS = json.load(open(A.icons or os.path.join(HERE, "..", "assets", "icons_data.json")))
OUT = A.out
OUT_NAME = A.name or SPEC.get("name", "topology")
SHOW_LEGEND = (not A.no_legend) and SPEC.get("show_legend", True)
os.makedirs(OUT, exist_ok=True)

# --------------------------------------------------------------------------
# Palette - Oracle-ish. Override any of these from spec["palette"].
# --------------------------------------------------------------------------
P = dict(
    WHITE="#FFFFFF", INK="#1B1B1B", SUB="#5B5750",
    RED="#C74634",        # Oracle accent / region / VPN
    ORANGE="#AE562C",     # VCN boundary
    TEAL="#2D5967",       # icons / FastConnect / backbone
    ONP_FILL="#EEF3F6", ONP_BORDER="#6E8895",   # customer / on-prem group
    REG_FILL="#F5F4F2", REG_BORDER="#9E9892",   # cloud region group
    CARD="#FFFFFF", GREEN="#3A7D44",
)
P.update(SPEC.get("palette", {}))
WHITE, INK, SUB = P["WHITE"], P["INK"], P["SUB"]
RED, ORANGE, TEAL = P["RED"], P["ORANGE"], P["TEAL"]
ONP_FILL, ONP_BORDER = P["ONP_FILL"], P["ONP_BORDER"]
REG_FILL, REG_BORDER = P["REG_FILL"], P["REG_BORDER"]
CARD, GREEN = P["CARD"], P["GREEN"]
VPN, BACKBONE = RED, TEAL

# --------------------------------------------------------------------------
# Cost facts (spec-overridable). OCI: DRG/VCN/subnets/gateways/S2S-VPN are $0;
# FastConnect ports and egress > 10 TB/mo are the only recurring charges.
# --------------------------------------------------------------------------
COST = dict(hours_mo=730, fastconnect_port_hr=1.275, egress_free_tb=10, egress_per_gb=0.0085)
COST.update(SPEC.get("cost", {}))
FC_MONTHLY = COST["fastconnect_port_hr"] * COST["hours_mo"]

REGIONS = SPEC["regions"]
if A.limit:
    REGIONS = REGIONS[:A.limit]

# --------------------------------------------------------------------------
# Display list primitives
# --------------------------------------------------------------------------
D = []
def rect(x, y, w, h, fill=None, stroke=None, dash=False, r=10, lw=1.4):
    D.append(dict(t="rect", x=x, y=y, w=w, h=h, fill=fill, stroke=stroke, dash=dash, r=r, lw=lw))
def icon(name, x, y, w, h):
    D.append(dict(t="icon", name=name, x=x, y=y, w=w, h=h))
def text(x, y, s, size=12, bold=False, color=INK, anchor="w"):
    D.append(dict(t="text", x=x, y=y, s=s, size=size, bold=bold, color=color, anchor=anchor))
def edge(x1, y1, x2, y2, color=INK, dash=False, lw=1.6, arrow=True, label=None, lsize=8.5):
    D.append(dict(t="edge", x1=x1, y1=y1, x2=x2, y2=y2, color=color, dash=dash,
                  lw=lw, arrow=arrow, label=label, lsize=lsize))

# --------------------------------------------------------------------------
# LAYOUT
#   left column  = customer / on-prem site bands (one per site-area)
#   right column = cloud region cards (site-areas sharing a region are MERGED)
#   far right    = backbone spine joining every DRG
# --------------------------------------------------------------------------
W = SPEC.get("width", 1840)
MARGIN, band_gap, ROWH = 30, 18, 78
y = 0

rect(0, 0, W, 86, fill=WHITE, r=0)
text(MARGIN, 38, SPEC.get("title", "Network Connectivity"), size=24, bold=True, color=INK)
text(MARGIN, 66, SPEC.get("subtitle", ""), size=12.5, color=SUB)
y = 98

left_x = MARGIN
sites_w = SPEC.get("sites_width", 760)
gap_mid = 150                       # connection corridor
reg_x = left_x + sites_w + gap_mid
reg_w = W - reg_x - MARGIN - 70     # leave room for the backbone spine
spine_x = W - MARGIN - 34

band_tops, drg_points = [], []

# Group site-areas that share one cloud region id -> ONE region card.
groups = {}
for R in REGIONS:
    groups.setdefault(R["rid"], []).append(R)

def member_height(R):
    rows = 1 + len(R.get("spokes", []))
    return max(70 + rows * ROWH + 30, 200)

for rid, members in groups.items():
    heights = [member_height(R) for R in members]
    group_top = y
    group_h = sum(heights) + band_gap * (len(members) - 1)
    band_tops.append(group_top)
    rep = members[0]                # representative for region label / VCN

    # ---------- ONE cloud region container ----------
    rx, ry, rw, rh = reg_x, group_top, reg_w, group_h
    rect(rx, ry, rw, rh, fill=REG_FILL, stroke=REG_BORDER, r=12, lw=1.6)
    text(rx + 44, ry + 24, f"OCI · {rep['oci']}", size=13.5, bold=True, color=INK)
    text(rx + 44, ry + 42, rep["rid"], size=10.5, color=RED)
    icon("VCN", rx + 10, ry + 10, 26, 26)

    vx, vy, vw, vh = rx + 150, ry + 52, rw - 170, rh - 70
    rect(vx, vy, vw, vh, fill=WHITE, stroke=ORANGE, dash=True, r=8, lw=1.6)
    text(vx + 40, vy + 20, "VCN", size=11.5, bold=True, color=ORANGE)
    text(vx + 40, vy + 34, rep["vcn"], size=9.5, color=SUB)
    icon("VCN", vx + 8, vy + 8, 26, 26)

    has_sftp = any(m.get("sftpgo") for m in members)
    sn_w = (vw - 360) if has_sftp else (vw - 32)
    sn_y = vy + 50
    for label, cidr in [("Public/Hub Subnet", ".0.0/24"), ("Private/Workload Subnet", ".1.0/24")]:
        rect(vx + 16, sn_y, sn_w, 30, fill="#FCFBFA", stroke=ORANGE, dash=True, r=6, lw=1.0)
        text(vx + 26, sn_y + 19, f"{label}   {rep['vcn'][:-7]}{cidr}", size=9.2, color=SUB)
        sn_y += 38

    if has_sftp:   # optional SFTPGo + Object Storage inset (AWS Transfer Family replacement)
        scx, scy, scw, sch = vx + vw - 330, vy + 48, 312, vh - 66
        rect(scx, scy, scw, sch, fill="#F1F7F2", stroke=GREEN, dash=True, r=8, lw=1.3)
        text(scx + 12, scy + 20, "SFTP service - replaces AWS Transfer Family", size=9.2, bold=True, color=GREEN)
        rect(scx + 18, scy + 34, 120, 96, fill=WHITE, stroke=GREEN, r=8, lw=1.6)
        icon("VM", scx + 59, scy + 44, 38, 44)
        text(scx + 78, scy + 110, "SFTPGo", size=10, bold=True, color=INK, anchor="c")
        text(scx + 78, scy + 124, "Ampere VM", size=8.0, color=SUB, anchor="c")
        rect(scx + 174, scy + 34, 120, 96, fill=WHITE, stroke=TEAL, r=8, lw=1.6)
        icon("Buckets", scx + 211, scy + 44, 46, 46)
        text(scx + 234, scy + 110, "Object Storage", size=9.2, bold=True, color=INK, anchor="c")
        text(scx + 234, scy + 124, "S3-compat", size=8.0, color=SUB, anchor="c")
        edge(scx + 138, scy + 82, scx + 174, scy + 82, color=GREEN, lw=1.8, label="S3 API", lsize=8.0)
        text(scx + 12, scy + sch - 12, "SFTP/FTPS in → lands directly in bucket · no per-endpoint fee",
             size=8.2, color=SUB)

    # one DRG, vertically centred in the (possibly merged) group
    dgx, dgy = rx + 58, ry + rh / 2 - 26
    icon("DRG", dgx, dgy, 52, 52)
    text(dgx + 26, dgy + 64, "DRG", size=9.5, bold=True, color=TEAL, anchor="c")
    drg_in = (dgx, dgy + 26)
    drg_points.append((spine_x, ry + rh / 2, dgx + 26, dgy + 26))

    # ---------- each member gets its own site band on the left ----------
    my = group_top
    for R, bh in zip(members, heights):
        sx, sy, sw, sh = left_x, my, sites_w, bh
        rect(sx, sy, sw, sh, fill=ONP_FILL, stroke=ONP_BORDER, r=12, lw=1.6)
        text(sx + 16, sy + 24, f"Customer Sites - {R['area']}", size=13, bold=True, color="#33505C")
        if R.get("anchor"):
            text(sx + 16, sy + 42, f"Anchor services: {R['anchor']}", size=9.2, color=SUB)

        hb_x, hb_y, hb_w, hb_h = sx + sw - 300, sy + 58, 284, 60
        rect(hb_x, hb_y, hb_w, hb_h, fill=WHITE, stroke=RED, r=8, lw=2.0)
        icon("CPE", hb_x + 8, hb_y + 10, 34, 42)
        text(hb_x + 52, hb_y + 22, R["hub"]["name"], size=11.5, bold=True, color=INK)
        text(hb_x + 52, hb_y + 37, R["hub"].get("sub", ""), size=8.3, color=SUB)
        text(hb_x + 52, hb_y + 50, "◢ Regional VPN hub / edge", size=8.0, bold=True, color=RED)
        hub_out = (hb_x + hb_w, hb_y + hb_h / 2)
        hub_in_left = (hb_x, hb_y + hb_h / 2)

        spy = hb_y + hb_h + 16
        for nm, role in R.get("spokes", []):
            sbw, sbh = 250, 50
            bx, by = sx + 24, spy
            rect(bx, by, sbw, sbh, fill=CARD, stroke="#B9C6CC", r=7, lw=1.1)
            icon("CPE", bx + 8, by + 8, 26, 34)
            text(bx + 42, by + 21, nm, size=10.2, bold=True, color=INK)
            text(bx + 42, by + 36, role, size=8.4, color=SUB)
            edge(bx + sbw, by + sbh / 2, hub_in_left[0], hub_in_left[1],
                 color=ONP_BORDER, lw=1.2, arrow=True)
            spy += sbh + 12

        conn = R["hub"]["conn"]
        is_fc = conn.startswith("FastConnect")
        conn_label = f"{conn} · ~${FC_MONTHLY:,.0f}/mo" if is_fc else f"{conn} · $0/mo"
        edge(hub_out[0], hub_out[1], drg_in[0], drg_in[1],
             color=(TEAL if is_fc else VPN), dash=(not is_fc),
             lw=(3.0 if is_fc else 2.0), arrow=True, label=conn_label, lsize=9.0)
        if not is_fc:   # second, redundant IPSec tunnel
            edge(hub_out[0], hub_out[1] + 8, drg_in[0], drg_in[1] + 10,
                 color=VPN, dash=True, lw=1.4, arrow=True)
        my += bh + band_gap

    y = group_top + group_h + band_gap

# ---------- backbone spine joining every DRG ----------
sp_top = band_tops[0] + 30
sp_bot = drg_points[-1][1]
rect(spine_x - 2, sp_top, 4, sp_bot - sp_top, fill=BACKBONE, r=2)
for (sxp, syp, dgx, dgy) in drg_points:
    edge(dgx, dgy, spine_x, syp, color=BACKBONE, dash=True, lw=1.3, arrow=False)
text(spine_x + 10, (sp_top + sp_bot) / 2, SPEC.get("backbone_label", "OCI Backbone · DRG Remote Peering"),
     size=10, bold=True, color=BACKBONE)
D[-1]["vert"] = True

TOTAL_H = (y + 300) if SHOW_LEGEND else (y + 24)

def draw_legend():
    ly = y + 10
    rect(MARGIN, ly, W - 2 * MARGIN, 120, fill="#FAFAF9", stroke=REG_BORDER, r=10, lw=1.2)
    text(MARGIN + 18, ly + 26, "Legend", size=13, bold=True, color=INK)
    lx, lyy = MARGIN + 18, ly + 52
    def leg(x, yv, color, dash, label, fc=False):
        edge(x, yv, x + 60, yv, color=color, dash=dash, lw=(3.0 if fc else 2.0), arrow=True)
        text(x + 72, yv + 4, label, size=10.5, color=INK)
    leg(lx, lyy, TEAL, False, "FastConnect (dedicated)", fc=True)
    leg(lx, lyy + 34, VPN, True, "Site-to-Site VPN (IPSec, redundant tunnels)")
    leg(lx + 360, lyy, ONP_BORDER, False, "Spoke site → regional VPN hub")
    leg(lx + 360, lyy + 34, BACKBONE, True, "OCI backbone (DRG remote peering)")
    gx = lx + 760
    for nm, lab in [("DRG", "Dynamic Routing Gateway"), ("VCN", "Virtual Cloud Network"),
                    ("CPE", "Customer Premises Equip.")]:
        icon(nm, gx, lyy - 18, 26, 30); text(gx + 34, lyy + 2, lab, size=10, color=INK); lyy += 34
        if lyy > ly + 110: lyy = ly + 52; gx += 300

    cy = ly + 132
    rect(MARGIN, cy, W - 2 * MARGIN, 150, fill=WHITE, stroke=REG_BORDER, r=10, lw=1.2)
    text(MARGIN + 18, cy + 26, "Estimated monthly OCI networking cost", size=13, bold=True, color=INK)
    cl, cyy = MARGIN + 18, cy + 50
    n_vpn = sum(1 for R in REGIONS if not R["hub"]["conn"].startswith("FastConnect"))
    n_fc = sum(1 for R in REGIONS if R["hub"]["conn"].startswith("FastConnect"))
    rows = [
        (f"Site-to-Site VPN (IPSec) - {n_vpn} region(s), redundant tunnels", "$0",
         "OCI does not charge for VPN connections"),
        ("DRG · VCN · subnets · route tables · Internet/NAT/Service gateways", "$0",
         "No hourly or per-GB charge on OCI"),
        (f"FastConnect port × {n_fc} (10 Gbps tier @ ${COST['fastconnect_port_hr']}/port-hr)",
         f"~${FC_MONTHLY * max(n_fc,1):,.0f}/mo", "Only recurring networking charge"),
        ("Outbound data transfer", "$0",
         f"Free up to {COST['egress_free_tb']} TB/month, then ~${COST['egress_per_gb']}/GB"),
    ]
    for label, cost, note in rows:
        text(cl, cyy, label, size=10.5, color=INK)
        text(cl + 560, cyy, cost, size=10.5, bold=True, color=(RED if cost.startswith("~") else GREEN))
        text(cl + 700, cyy, note, size=9.2, color=SUB)
        cyy += 22
    text(cl, cyy + 6, "Total recurring OCI networking ≈", size=11.5, bold=True, color=INK)
    text(cl + 560, cyy + 6, f"${FC_MONTHLY * max(n_fc,1):,.0f}/mo", size=12, bold=True, color=RED)
    text(cl + 700, cyy + 6, "everything except the FastConnect port is $0 on OCI", size=9.2, color=SUB)

if SHOW_LEGEND:
    draw_legend()

# ==========================================================================
# RENDER - pycairo → PNG + SVG
# ==========================================================================
def hx(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))

def path_ops(ctx, ops, ox, oy, sc):
    for o in ops:
        k = o[0]
        if k == "M":   ctx.move_to(ox + o[1] * sc, oy + o[2] * sc)
        elif k == "L": ctx.line_to(ox + o[1] * sc, oy + o[2] * sc)
        elif k == "C": ctx.curve_to(ox + o[1] * sc, oy + o[2] * sc, ox + o[3] * sc, oy + o[4] * sc,
                                    ox + o[5] * sc, oy + o[6] * sc)
        elif k == "Z": ctx.close_path()

def draw_icon(ctx, name, x, y, w, h):
    ic = ICONS.get(name)
    if not ic: return
    sc = min(w / ic["w"], h / ic["h"])
    ox, oy = x + (w - ic["w"] * sc) / 2, y + (h - ic["h"] * sc) / 2
    for p in ic["paths"]:
        col = p["color"]
        if not col or not col.startswith("#"):   # fillColor=none paths
            continue
        ctx.new_path(); path_ops(ctx, p["ops"], ox, oy, sc)
        ctx.set_source_rgb(*hx(col)); ctx.fill()

def rounded(ctx, x, y, w, h, r):
    ctx.new_path()
    ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    ctx.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
    ctx.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
    ctx.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
    ctx.close_path()

def draw_text(ctx, e):
    ctx.select_font_face("DejaVu Sans", cairo.FONT_SLANT_NORMAL,
                         cairo.FONT_WEIGHT_BOLD if e["bold"] else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(e["size"]); ctx.set_source_rgb(*hx(e["color"]))
    s = e["s"]
    _, _, tw, _, _, _ = ctx.text_extents(s)
    x, y = e["x"], e["y"]
    if e.get("vert"):
        ctx.save(); ctx.translate(x, y); ctx.rotate(-math.pi / 2)
        ctx.move_to(-tw / 2, 0); ctx.show_text(s); ctx.restore(); return
    if e["anchor"] == "c": x -= tw / 2
    elif e["anchor"] == "e": x -= tw
    ctx.move_to(x, y); ctx.show_text(s)

def draw_edge(ctx, e):
    ctx.set_source_rgb(*hx(e["color"]))
    ctx.set_line_width(e["lw"]); ctx.set_dash([6, 4] if e["dash"] else [])
    x1, y1, x2, y2 = e["x1"], e["y1"], e["x2"], e["y2"]
    ctx.new_path(); ctx.move_to(x1, y1); ctx.line_to(x2, y2); ctx.stroke()
    ctx.set_dash([])
    if e["arrow"]:
        ang, al = math.atan2(y2 - y1, x2 - x1), 7
        ctx.move_to(x2, y2)
        ctx.line_to(x2 - al * math.cos(ang - 0.4), y2 - al * math.sin(ang - 0.4))
        ctx.line_to(x2 - al * math.cos(ang + 0.4), y2 - al * math.sin(ang + 0.4))
        ctx.close_path(); ctx.fill()
    if e["label"]:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        ctx.select_font_face("DejaVu Sans", 0, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(e["lsize"])
        _, _, tw, th, _, _ = ctx.text_extents(e["label"])
        ctx.set_source_rgb(1, 1, 1)                    # knock-out box so the label stays legible
        ctx.rectangle(mx - tw / 2 - 3, my - th - 6, tw + 6, th + 6); ctx.fill()
        ctx.set_source_rgb(*hx(e["color"]))
        ctx.move_to(mx - tw / 2, my - 4); ctx.show_text(e["label"])

def render(ctx):
    for e in D:
        t = e["t"]
        if t == "rect":
            rounded(ctx, e["x"], e["y"], e["w"], e["h"], e["r"])
            if e["fill"]:
                ctx.set_source_rgb(*hx(e["fill"])); ctx.fill_preserve()
            if e["stroke"]:
                ctx.set_source_rgb(*hx(e["stroke"])); ctx.set_line_width(e["lw"])
                ctx.set_dash([5, 4] if e["dash"] else []); ctx.stroke()
            else:
                ctx.new_path()
        elif t == "icon": draw_icon(ctx, e["name"], e["x"], e["y"], e["w"], e["h"])
        elif t == "text": draw_text(ctx, e)
        elif t == "edge": draw_edge(ctx, e)

scale = 2
surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(W * scale), int(TOTAL_H * scale))
ctx = cairo.Context(surf); ctx.scale(scale, scale)
ctx.set_source_rgb(1, 1, 1); ctx.paint(); render(ctx)
surf.write_to_png(f"{OUT}/{OUT_NAME}.png")

svgsurf = cairo.SVGSurface(f"{OUT}/{OUT_NAME}.svg", W, TOTAL_H)
sctx = cairo.Context(svgsurf)
sctx.set_source_rgb(1, 1, 1); sctx.paint(); render(sctx); svgsurf.finish()

# ==========================================================================
# EMIT editable .drawio - same coordinates, icons as SVG data URIs
# ==========================================================================
def icon_datauri(name):
    ic = ICONS[name]; parts = []
    for p in ic["paths"]:
        col = p["color"]
        if not col or not col.startswith("#"): continue
        d = []
        for o in p["ops"]:
            k = o[0]
            if k == "M":   d.append(f"M{o[1]:.1f} {o[2]:.1f}")
            elif k == "L": d.append(f"L{o[1]:.1f} {o[2]:.1f}")
            elif k == "C": d.append(f"C{o[1]:.1f} {o[2]:.1f} {o[3]:.1f} {o[4]:.1f} {o[5]:.1f} {o[6]:.1f}")
            elif k == "Z": d.append("Z")
        parts.append(f'<path d="{"".join(d)}" fill="{col}"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ic["w"]:.1f} {ic["h"]:.1f}">'
           f'{"".join(parts)}</svg>')
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="/")

def esc(s): return html.escape(str(s), quote=True)

cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
for i, e in enumerate(D, start=2):
    cid, t = f"c{i}", e["t"]
    if t == "rect":
        st = (f'rounded=1;arcSize=6;whiteSpace=wrap;html=1;fillColor={e["fill"] or "none"};'
              f'strokeColor={e["stroke"] or "none"};strokeWidth={e["lw"]};'
              f'{"dashed=1;" if e["dash"] else "dashed=0;"}')
        cells.append(f'<mxCell id="{cid}" value="" style="{esc(st)}" vertex="1" parent="1">'
                     f'<mxGeometry x="{e["x"]:.1f}" y="{e["y"]:.1f}" width="{e["w"]:.1f}" '
                     f'height="{e["h"]:.1f}" as="geometry"/></mxCell>')
    elif t == "icon":
        st = ('shape=image;verticalLabelPosition=bottom;verticalAlign=top;imageAspect=1;'
              f'aspect=fixed;image={icon_datauri(e["name"])};')
        cells.append(f'<mxCell id="{cid}" value="" style="{esc(st)}" vertex="1" parent="1">'
                     f'<mxGeometry x="{e["x"]:.1f}" y="{e["y"]:.1f}" width="{e["w"]:.1f}" '
                     f'height="{e["h"]:.1f}" as="geometry"/></mxCell>')
    elif t == "text":
        align = {"w": "left", "c": "center", "e": "right"}[e["anchor"]]
        tw = max(40, len(e["s"]) * e["size"] * 0.62)
        bx = e["x"] if e["anchor"] == "w" else (e["x"] - tw / 2 if e["anchor"] == "c" else e["x"] - tw)
        st = (f'text;html=1;align={align};verticalAlign=middle;whiteSpace=wrap;'
              f'fontSize={e["size"]:.0f};fontStyle={1 if e["bold"] else 0};fontColor={e["color"]};')
        cells.append(f'<mxCell id="{cid}" value="{esc(e["s"])}" style="{esc(st)}" vertex="1" parent="1">'
                     f'<mxGeometry x="{bx:.1f}" y="{e["y"] - e["size"]:.1f}" width="{tw:.1f}" '
                     f'height="{e["size"] * 1.6:.1f}" as="geometry"/></mxCell>')
    elif t == "edge":
        st = (f'endArrow={"classic" if e["arrow"] else "none"};html=1;rounded=0;'
              f'strokeColor={e["color"]};strokeWidth={e["lw"]};{"dashed=1;" if e["dash"] else ""}')
        cells.append(f'<mxCell id="{cid}" value="{esc(e["label"] or "")}" style="{esc(st)}" edge="1" parent="1">'
                     f'<mxGeometry relative="1" as="geometry">'
                     f'<mxPoint x="{e["x1"]:.1f}" y="{e["y1"]:.1f}" as="sourcePoint"/>'
                     f'<mxPoint x="{e["x2"]:.1f}" y="{e["y2"]:.1f}" as="targetPoint"/>'
                     f'</mxGeometry></mxCell>')

xml = (f'<mxfile host="app.diagrams.net" version="24.0.0">'
       f'<diagram name="{esc(SPEC.get("title", "Topology"))}" id="topology">'
       f'<mxGraphModel dx="1422" dy="800" grid="0" gridSize="10" guides="1" tooltips="1" '
       f'connect="1" arrows="1" fold="1" page="1" pageScale="1" '
       f'pageWidth="{W}" pageHeight="{int(TOTAL_H)}" math="0" shadow="0">'
       f'<root>{"".join(cells)}</root></mxGraphModel></diagram></mxfile>')
open(f"{OUT}/{OUT_NAME}.drawio", "w", encoding="utf-8").write(xml)

print(f"{OUT_NAME}: {W}x{int(TOTAL_H)} · {len(D)} elements · {len(cells)} drawio cells")
print(f"  -> {OUT}/{OUT_NAME}.png / .svg / .drawio")
