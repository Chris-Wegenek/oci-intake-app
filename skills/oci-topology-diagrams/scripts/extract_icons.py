#!/usr/bin/env python3
"""Extract OCI library stencils -> structured icon path data (icon-local px coords)."""
import json, base64, zlib, urllib.parse, re, html, xml.etree.ElementTree as ET

LIB = "/sessions/clever-sharp-keller/mnt/uploads/OCI Library.xml"

def inflate_b64(s):
    b = base64.b64decode(s)
    try:
        return zlib.decompress(b, -15).decode("utf-8", "replace")
    except Exception:
        return zlib.decompress(b).decode("utf-8", "replace")

def decode_entry_xml(s):
    return urllib.parse.unquote(inflate_b64(s))

def decode_stencil(s):
    return urllib.parse.unquote(inflate_b64(s))

def parse_style(style):
    d = {}
    for part in (style or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            d[k] = v
    return d

def cell_geom(cell):
    g = cell.find("mxGeometry")
    if g is None:
        return (0.0, 0.0, 0.0, 0.0)
    return (float(g.get("x", 0)), float(g.get("y", 0)),
            float(g.get("width", 0)), float(g.get("height", 0)))

def abs_offset(cell_id, cells, parents):
    """Sum x/y offsets walking up parents (excluding canvas 0/1)."""
    ox = oy = 0.0
    cur = parents.get(cell_id)
    while cur and cur in cells and cur not in ("0", "1"):
        x, y, w, h = cell_geom(cells[cur])
        ox += x; oy += y
        cur = parents.get(cur)
    return ox, oy

def stencil_to_subpaths(sten_xml, ox, oy, sx, sy):
    """Return list of svg-path command lists in absolute px coords."""
    root = ET.fromstring(sten_xml)
    # default coordinate space 100x100 unless shape has w/h
    cw = float(root.get("w", 100)); ch = float(root.get("h", 100))
    fx = sx / cw; fy = sy / ch
    subpaths = []
    def emit(container):
        for path in container.findall("path"):
            ops = []
            for cmd in path:
                t = cmd.tag
                def X(a): return ox + float(cmd.get(a)) * fx
                def Y(a): return oy + float(cmd.get(a)) * fy
                if t == "move":
                    ops.append(("M", X("x"), Y("y")))
                elif t == "line":
                    ops.append(("L", X("x"), Y("y")))
                elif t == "curve":
                    ops.append(("C", X("x1"), Y("y1"), X("x2"), Y("y2"), X("x3"), Y("y3")))
                elif t == "quad":
                    ops.append(("Q", X("x1"), Y("y1"), X("x2"), Y("y2")))
                elif t == "close":
                    ops.append(("Z",))
            subpaths.append(ops)
    for tag in ("background", "foreground"):
        c = root.find(tag)
        if c is not None:
            emit(c)
    # some stencils put path directly under shape
    if not subpaths:
        emit(root)
    return subpaths

def extract_icon(entry):
    xmlstr = decode_entry_xml(entry["xml"])
    root = ET.fromstring(xmlstr).find("root")
    cells = {}
    parents = {}
    order = []
    for cell in root.findall("mxCell"):
        cid = cell.get("id")
        cells[cid] = cell
        parents[cid] = cell.get("parent")
        order.append(cid)
    paths = []
    minx = miny = 1e9; maxx = maxy = -1e9
    for cid in order:
        cell = cells[cid]
        style = parse_style(cell.get("style"))
        shp = style.get("shape", "")
        m = re.search(r"stencil\(([A-Za-z0-9+/=]+)\)", shp)
        x, y, w, h = cell_geom(cell)
        ox, oy = abs_offset(cid, cells, parents)
        ax, ay = ox + x, oy + y
        if not m:
            continue
        sten = decode_stencil(m.group(1))
        color = style.get("fillColor", "#000000")
        if color == "none":
            color = style.get("strokeColor", "#000000")
        sub = stencil_to_subpaths(sten, ax, ay, w, h)
        for ops in sub:
            paths.append({"color": color, "ops": ops})
            for o in ops:
                xs = o[1::2]; ys = o[2::2]
                # generic: collect numeric coords
                nums = [v for v in o[1:]]
                for i in range(0, len(nums), 2):
                    px = nums[i]; py = nums[i+1] if i+1 < len(nums) else py
                    minx = min(minx, px); maxx = max(maxx, px)
                    miny = min(miny, py); maxy = max(maxy, py)
    if not paths:
        return None
    # normalize to local origin
    for p in paths:
        for i, o in enumerate(p["ops"]):
            if o[0] == "Z":
                continue
            vals = list(o)
            for j in range(1, len(vals), 2):
                vals[j] -= minx
                if j+1 < len(vals):
                    vals[j+1] -= miny
            p["ops"][i] = tuple(vals)
    return {"w": maxx - minx, "h": maxy - miny, "paths": paths}

def main():
    raw = open(LIB, encoding="utf-8").read()
    inner = raw.split("<mxlibrary>", 1)[1].rsplit("</mxlibrary>", 1)[0]
    data = json.loads(inner)
    byt = {html.unescape(d.get("title", "")).replace("\xa0", " ").strip(): d for d in data}

    want = {
        "DRG": "Networking - Dynamic Routing Gateway DRG",
        "ServiceGateway": "Networking - Service Gateway",
        "NATGateway": "Networking - NAT Gateway",
        "InternetGateway": "Networking - Internet Gateway",
        "LoadBalancer": "Networking - Flexible Load Balancer",
        "CPE": "Networking - Customer Premises Equipment CPE",
        "VCN": "Networking - Virtual Cloud Network VCN",
        "WAF": "Identity and Security - WAF",
        "Bastion": "Identity and Security - Bastion",
        "Policies": "Identity and Security - Policies",
        "User": "Identity and Security - User",
        "IAM": "Identity and Security - IAM Identity and Access Management",
        "APIGateway": "Developer Services - API Gateway",
        "Functions": "Compute - Functions",
        "Streaming": "Analytics and AI - Streaming",
        "ServiceConnectorHub": "Analytics and AI - Service Connector Hub",
        "DataCatalog": "Analytics and AI - Data Catalog",
        "DataFlow": "Analytics and AI - Data Flow",
        "DataIntegration": "Analytics and AI - Data Integration",
        "DataScience": "Analytics and AI - Data Science",
        "Analytics": "Analytics and AI",
        "ADW": "Database - Autonomous Data Warehouse ADW",
        "ObjectStorage": "Storage - Object Storage",
        "Buckets": "Storage - Buckets",
        "Auditing": "Observability and Management - Auditing",
        "Logging": "Observability and Management - Logging",
        "VM": "Compute - Virtual Machine VM",
        "Database": "Database - Database System",
        "ERP": "Applications - ERP",
        "Fusion": "Applications - Fusion",
        "FileStorage": "Storage - File Storage",
    }
    out = {}
    missing = []
    for name, title in want.items():
        if title not in byt:
            missing.append((name, title)); continue
        try:
            ic = extract_icon(byt[title])
            if ic:
                out[name] = ic
            else:
                missing.append((name, title + " [no paths]"))
        except Exception as e:
            missing.append((name, title + f" [ERR {e}]"))
    json.dump(out, open("/sessions/clever-sharp-keller/mnt/outputs/icons_data.json", "w"))
    print("extracted:", len(out))
    for k, v in out.items():
        print(f"  {k:22s} {v['w']:.0f}x{v['h']:.0f}  paths={len(v['paths'])}")
    if missing:
        print("MISSING:")
        for n, t in missing:
            print("  ", n, "->", t)

if __name__ == "__main__":
    main()
