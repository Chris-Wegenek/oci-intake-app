"""Excel BOM exporter.

Reproduces the two sheets created by the "E6 Ax BOM Creator" Office Script
("BOM w E6 Acceleron" + "Overview") using openpyxl, so the app can export a
formatted workbook that matches the script's layout, pricing, and formulas.

The pricing rates here intentionally mirror the BOM script exactly:
  - E6 Acceleron OCPU      B112530   $0.0138 / OCPU-hour  x 730
  - E6 Acceleron Memory    B112530   $0.0108 / GB-hour    x 730
  - Block Volume Storage   B91961    $0.0255 / GB-month
  - Block Volume Perf Unit B91962    $0.0017 / unit-month (10 units per GB)
  - Windows OS license     B88318    $0.0920 / OCPU-hour  x 730
  - FastConnect 1 Gbps     B88326    $0.2125 / port-hour  x 730
"""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ---- Pricing constants (must match the BOM script) ----
HOURS = 730
CPU_RATE = 0.0138
MEM_RATE = 0.0108
DISK_RATE = 0.0255
PERF_RATE = 0.0017
PERF_UNITS_PER_GB = 10
WINDOWS_RATE = 0.0920
FASTCONNECT_RATE = 0.2125

# ---- Colors (hex from the script, ARGB for openpyxl) ----
HDR_FILL = "C0E6F5"
NAME_RED = "FF9999"
BV_PINK = "FFE8E8"
BORDER = "000000"
OV_NAVY = "7F1D1D"
OV_BLUE = "C0504D"
OV_LIGHT = "F2DCDB"
OV_INPUT = "FFF2CC"
OV_INPUT_BORDER = "BF8F00"

MONEY2 = '"$"#,##0.00'
MONEY4 = '"$"#,##0.0000'
MONEY0 = '"$"#,##0'
PCT0 = "0%"

# Default shape (E6 Acceleron) used when the caller does not pass shape details.
DEFAULT_SHAPE = {
    "label": "E6 Acceleron",
    "shortLabel": "E6 Acceleron",
    "computeSku": "B112530",
    "memorySku": "B112530",
    "computeRate": CPU_RATE,
    "memoryRate": MEM_RATE,
}


def _resolve_shape(shape):
    merged = dict(DEFAULT_SHAPE)
    if shape:
        for key in ("label", "shortLabel", "computeSku", "memorySku", "computeRate", "memoryRate"):
            if shape.get(key) not in (None, ""):
                merged[key] = shape[key]
    return merged


def _fill(hexcolor):
    return PatternFill("solid", fgColor="FF" + hexcolor)


def _side(color=BORDER, style="medium"):
    return Side(style=style, color="FF" + color)


def _box(ws, r1, c1, r2, c2, color=BORDER, style="medium"):
    """Apply an outer border around a rectangular range."""
    side = _side(color, style)
    for c in range(c1, c2 + 1):
        top = ws.cell(row=r1, column=c)
        bot = ws.cell(row=r2, column=c)
        top.border = Border(top=side, left=top.border.left, right=top.border.right, bottom=top.border.bottom)
        bot.border = Border(bottom=side, left=bot.border.left, right=bot.border.right, top=bot.border.top)
    for r in range(r1, r2 + 1):
        left = ws.cell(row=r, column=c1)
        right = ws.cell(row=r, column=c2)
        left.border = Border(left=side, top=left.border.top, right=left.border.right, bottom=left.border.bottom)
        right.border = Border(right=side, top=right.border.top, left=right.border.left, bottom=right.border.bottom)


CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left")


def _detect_os(server):
    text = " ".join(str(server.get(k, "")) for k in ("os", "name", "environment", "raw")).lower()
    if "windows" in text:
        return "windows"
    if "linux" in text:
        return "linux"
    return ""


def build_bom_sheet(ws, servers, shape=None, hide_windows=False):
    """Render the BOM sheet for the selected shape. Returns the windows OCPU total."""
    shape = _resolve_shape(shape)
    headers = ["Part", "Description", "Part Qty", "Instance Qty", "Usage Qty (Hours)",
               "Unit Price", "Monthly Cost", "VM Cost"]
    for i, text in enumerate(headers, start=1):
        c = ws.cell(row=3, column=i, value=text)
        c.fill = _fill(HDR_FILL)
        c.font = Font(bold=True, size=11)
        c.alignment = CENTER if i in (5, 7, 8) else Alignment(horizontal="left", vertical="center")
    ws.cell(row=3, column=9).fill = _fill(HDR_FILL)

    # --- Free Tier block ---
    ws.cell(row=4, column=2, value="Free Tier").font = Font(bold=True, size=17)
    free_rows = [
        "OCI Data Ingress (Inbound Data Transfer)",
        "OCI Data Egress (Outbound) (first 10TB)",
        "Flexible Network Load Balancer",
        "OCI Vault Secrets Security",
        "OCI User Management and MFA",
        "OCI Cloud Guard (Monitoring and Defense)",
        "OCI Data Encryption",
        "OCI Network Firewall",
        "Support",
    ]
    for i, label in enumerate(free_rows):
        r = 5 + i
        ws.cell(row=r, column=2, value=label).font = Font(bold=True, size=11)
        ws.cell(row=r, column=3, value=("Included" if label == "Support" else "Free")).font = Font(size=11)
        g = ws.cell(row=r, column=7, value=0)
        g.font = Font(bold=True)
        g.number_format = MONEY2

    # --- FastConnect ---
    ws.cell(row=16, column=2, value="FastConnect").font = Font(bold=True, size=17)
    _line(ws, 17, "B88326", "          OCI - FastConnect 1 Gbps (Port Hour)", 0, 1, HOURS, FASTCONNECT_RATE)

    # --- Windows Licenses (qty filled after blocks) ---
    ws.cell(row=19, column=2, value="Windows Licenses").font = Font(bold=True, size=17)
    _line(ws, 20, "B88318", "          Compute - Windows OS (OCPU Per Hour)", 0, 1, HOURS, WINDOWS_RATE)

    # --- Virtual Machines header ---
    ws.cell(row=22, column=2, value="Virtual Machines").font = Font(bold=True, size=17)

    block_size = 7
    first_name_row = 24  # Excel row of the first server name
    windows_cpu_total = 0

    for b, server in enumerate(servers):
        name_row = first_name_row + b * block_size
        cpu_row, ram_row, bv_row, disk_row, perf_row = (name_row + k for k in range(1, 6))

        ocpus = int(server.get("ocpus") or 0)
        memory = int(server.get("memory") or 0)
        disk = float(server.get("disk") or 0)
        if _detect_os(server) == "windows" and not hide_windows:
            windows_cpu_total += ocpus

        # Server name row: fill across A-H. Color by feasibility against the OCI shape.
        status = server.get("sizeStatus", "ok")
        if status == "impossible":
            row_fill, name_color = _fill("C00000"), "FFFFFFFF"   # strong red = cannot be built
        elif status == "baremetal":
            row_fill, name_color = _fill("FFC000"), "FF000000"   # orange = needs bare metal
        else:
            row_fill, name_color = _fill(NAME_RED), "FF000000"
        for c in range(1, 9):
            ws.cell(row=name_row, column=c).fill = row_fill
        nm = ws.cell(row=name_row, column=2, value=server.get("name", f"Server {b + 1}"))
        nm.font = Font(bold=True, size=15, color=name_color)
        nm.alignment = Alignment(horizontal="left", vertical="bottom", indent=1)
        if status != "ok" and server.get("sizeMessage"):
            note = ws.cell(row=name_row, column=10,
                           value=("IMPOSSIBLE: " if status == "impossible" else "NEEDS BARE METAL: ") + server["sizeMessage"])
            note.font = Font(bold=True, size=10, color=("FFC00000" if status == "impossible" else "FFBF8F00"))

        _line(ws, cpu_row, shape["computeSku"],
              f" Compute - {shape['label']} - OCPU (OCPU Per Hour)      Capacity Type: On - Demand",
              ocpus, 1, HOURS, shape["computeRate"])
        _line(ws, ram_row, shape["memorySku"],
              f" Compute - {shape['label']} - Memory(Gigabyte Per Hour)    Capacity Type: On - Demand",
              memory, 1, HOURS, shape["memoryRate"])

        bv = ws.cell(row=bv_row, column=2, value=" Boot Volume (Local Storage Sizes)")
        bv.fill = _fill(BV_PINK)
        bv.font = Font(bold=True)

        _line(ws, disk_row, "B91961",
              "Storage - Block Volume - Storage (Gigabyte Storage Capacity Per Month)",
              disk, 1, 1, DISK_RATE)
        _line(ws, perf_row, "B91962",
              "Storage - Block Volume - Performance Units (Performance Units Per Gigabyte Per Month)",
              PERF_UNITS_PER_GB * disk, 1, 1, PERF_RATE)

        # Col H VM cost box
        h = ws.cell(row=disk_row, column=8, value="Total VM Cost")
        h.font = Font(bold=True)
        h.alignment = CENTER
        tot = ws.cell(row=perf_row, column=8, value=f"=SUM(G{cpu_row}:G{perf_row})")
        tot.font = Font(bold=True)
        tot.alignment = CENTER
        tot.number_format = MONEY2

        _box(ws, name_row, 1, perf_row, 8, BORDER, "medium")
        _box(ws, disk_row, 8, perf_row, 8, BORDER, "medium")

    # Windows license quantity -> C20, drives G20
    if servers:
        ws.cell(row=20, column=3, value=windows_cpu_total).alignment = CENTER

    # --- Totals ---
    total_row = first_name_row + len(servers) * block_size
    ws.cell(row=total_row, column=7, value="Total Per Month:").font = Font(bold=True, size=15)
    g_tot = ws.cell(row=total_row, column=8, value="=SUM(G:G)")
    g_tot.font = Font(bold=True, size=15)
    g_tot.number_format = MONEY2

    # Summary cells in cols I/J referenced by the Overview sheet
    ws.cell(row=14, column=9, value="Total Per Month:").font = Font(bold=True, size=15)
    j15 = ws.cell(row=15, column=10, value="=SUM(G:G)")
    j15.font = Font(bold=True, size=15)
    j15.number_format = MONEY2
    ws.cell(row=17, column=9, value="Total Per Year:").font = Font(bold=True, size=15)
    j18 = ws.cell(row=18, column=10, value="=J15*12")
    j18.font = Font(bold=True, size=15)
    j18.number_format = MONEY0

    # Column number formats / widths
    for r in range(1, total_row + 2):
        ws.cell(row=r, column=6).number_format = MONEY4
        ws.cell(row=r, column=7).number_format = MONEY2
        ws.cell(row=r, column=8).number_format = MONEY2
    widths = {1: 12, 2: 62, 3: 10, 4: 12, 5: 16, 6: 12, 7: 14, 8: 16, 9: 18, 10: 16}
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w

    return windows_cpu_total


def _line(ws, row, part, desc, qty, instance_qty, hours, unit_price):
    """Write a standard BOM line row (cols A-G) with the G=C*D*E*F formula."""
    ws.cell(row=row, column=1, value=part).font = Font(bold=True)
    ws.cell(row=row, column=2, value=desc).font = Font(size=11)
    ws.cell(row=row, column=3, value=qty).alignment = CENTER
    ws.cell(row=row, column=4, value=instance_qty).alignment = CENTER
    ws.cell(row=row, column=5, value=hours).alignment = CENTER
    f = ws.cell(row=row, column=6, value=unit_price)
    f.alignment = CENTER
    f.number_format = MONEY4
    g = ws.cell(row=row, column=7, value=f"=C{row}*D{row}*E{row}*F{row}")
    g.number_format = MONEY2


def build_overview_sheet(ws, util_by_year, existing_infra_cost, bom_sheet_name="BOM w E6 Acceleron"):
    """Render the 'Overview' sheet, pulling the 5-year utilization ramp from the app."""
    BOM = f"'{bom_sheet_name}'"
    ws.column_dimensions["A"].width = 28
    for col in "BCDEF":
        ws.column_dimensions[col].width = 16

    def band(cell, text, size=13):
        c = ws[cell]
        c.value = text
        c.fill = _fill(OV_NAVY)
        c.font = Font(bold=True, color="FFFFFFFF", size=size)
        c.alignment = CENTER

    def colhead(cell, text):
        c = ws[cell]
        c.value = text
        c.fill = _fill(OV_BLUE)
        c.font = Font(bold=True, color="FFFFFFFF")
        c.alignment = CENTER

    # Title banner
    ws.merge_cells("A1:H2")
    t = ws["A1"]
    t.value = "Cloud Migration Cost Overview"
    t.fill = _fill(OV_NAVY)
    t.font = Font(bold=True, color="FFFFFFFF", size=26, name="Calibri")
    t.alignment = CENTER

    # KPI cards
    ws.merge_cells("B4:C4")
    band("B4", "Total Monthly Cost")
    ws.merge_cells("B5:C6")
    ws["B5"] = f"={BOM}!J15"
    ws.merge_cells("E4:F4")
    band("E4", "Total Annual Cost (Full)")
    ws.merge_cells("E5:F6")
    ws["E5"] = f"={BOM}!J18"
    for cell in ("B4", "E4"):
        ws[cell].fill = _fill(OV_BLUE)
    for cell in ("B5", "E5"):
        c = ws[cell]
        c.fill = _fill(OV_LIGHT)
        c.font = Font(bold=True, size=24)
        c.alignment = CENTER
        c.number_format = MONEY2
    _box(ws, 5, 2, 6, 3, OV_NAVY, "medium")
    _box(ws, 5, 5, 6, 6, OV_NAVY, "medium")

    # 5-Year Cost Projection (Utilization % comes from the app ramp)
    ws.merge_cells("A8:D8")
    band("A8", "5-Year Cost Projection")
    for cell, text in (("A9", "Year"), ("B9", "Utilization %"), ("C9", "OCI Annual Cost"), ("D9", "Cumulative")):
        colhead(cell, text)
    for y in range(5):
        row = 10 + y
        ws[f"A{row}"] = y + 1
        ws[f"A{row}"].alignment = CENTER
        util = util_by_year[y] if y < len(util_by_year) else 1.0
        b = ws[f"B{row}"]
        b.value = round(util, 4)
        b.number_format = PCT0
        b.alignment = CENTER
        b.fill = _fill(OV_INPUT)
        ws[f"C{row}"] = f"=$E$5*B{row}"
        ws[f"D{row}"] = (f"=C{row}" if y == 0 else f"=D{row - 1}+C{row}")
        ws[f"C{row}"].number_format = MONEY2
        ws[f"D{row}"].number_format = MONEY2
    ws.merge_cells("A15:B15")
    ws["A15"] = "5-Year Total"
    ws["C15"] = "=SUM(C10:C14)"
    ws["D15"] = "=D14"
    for cell in ("A15", "B15", "C15", "D15"):
        ws[cell].font = Font(bold=True)
        ws[cell].fill = _fill(OV_LIGHT)
    ws["C15"].number_format = MONEY2
    ws["D15"].number_format = MONEY2
    _box(ws, 10, 2, 14, 2, OV_INPUT_BORDER, "thin")
    _box(ws, 9, 1, 15, 4, OV_NAVY, "thin")

    # Existing vs OCI savings
    ws.merge_cells("A17:D17")
    band("A17", "Existing Infrastructure vs. OCI Estimate")
    rows = [
        ("A18", "Existing Infra Cost (enter):", "B18", existing_infra_cost, MONEY2),
        ("A19", "OCI Estimated Annual:", "B19", "=$E$5", MONEY2),
        ("A20", "Estimated Annual Savings:", "B20", "=B18-B19", MONEY2),
        ("A21", "Estimated 5-Year Savings:", "B21", "=(B18*5)-SUM(C10:C14)", MONEY2),
        ("A22", "Savings % vs. Existing:", "B22", "=IF(B18=0,0,(B18-B19)/B18)", "0.0%"),
    ]
    for la, label, ba, val, fmt in rows:
        ws[la] = label
        ws[la].font = Font(bold=True)
        c = ws[ba]
        c.value = val
        c.number_format = fmt
        c.alignment = CENTER
    ws["B18"].fill = _fill(OV_INPUT)
    _box(ws, 18, 2, 18, 2, OV_INPUT_BORDER, "medium")

    # Chart data — comparison table
    ws.merge_cells("A23:F23")
    band("A23", "Chart Data — Comparison", size=12)
    for cell, text in (("A24", "Year"), ("B24", "OCI Estimate"), ("C24", "Existing Infra Cost"),
                       ("D24", "Combined Cost"), ("E24", "Current Spend"), ("F24", "Total Savings")):
        colhead(cell, text)
    ws["A25"] = "Today"
    ws["A25"].alignment = CENTER
    ws["C25"] = "=$B$18"
    ws["E25"] = "=$B$18"
    ws["F25"] = "=$B$18-C25"
    for y in range(5):
        r = 26 + y
        ws[f"A{r}"] = f"Year {y + 1}"
        ws[f"A{r}"].alignment = CENTER
        ws[f"B{r}"] = f"=C{10 + y}"
        ws[f"C{r}"] = f"=U{10 + y}"
        ws[f"D{r}"] = f"=B{r}+C{r}"
        ws[f"E{r}"] = "=$B$18"
        ws[f"F{r}"] = f"=$B$18-D{r}"
    for r in range(25, 31):
        for col in "BCDEF":
            ws[f"{col}{r}"].number_format = MONEY2
    _box(ws, 24, 1, 30, 6, OV_NAVY, "thin")

    # Existing-spend ramp adjuster (cols T:V)
    for col in "TUV":
        ws.column_dimensions[col].width = 18
    ws.merge_cells("T8:V8")
    band("T8", "Existing Spend — Ramp %", size=12)
    for cell, text in (("T9", "Year"), ("U9", "Existing Infra Cost"), ("V9", "Existing Util %")):
        colhead(cell, text)
    for y in range(5):
        r = 10 + y
        ws[f"T{r}"] = f"Year {y + 1}"
        ws[f"T{r}"].alignment = CENTER
        v = ws[f"V{r}"]
        v.value = 1
        v.number_format = PCT0
        v.alignment = CENTER
        v.fill = _fill(OV_INPUT)
        ws[f"U{r}"] = f"=$B$18*V{r}"
        ws[f"U{r}"].number_format = MONEY2
    _box(ws, 10, 22, 14, 22, OV_INPUT_BORDER, "thin")
    _box(ws, 9, 20, 14, 22, OV_NAVY, "thin")

    # Comparison chart (clustered columns + reference line)
    chart = BarChart()
    chart.type = "col"
    chart.grouping = "clustered"
    chart.title = "Existing Infra vs. OCI Estimate (Today + 5-Year)"
    chart.height = 9
    chart.width = 20
    data = Reference(ws, min_col=2, max_col=4, min_row=24, max_row=30)
    cats = Reference(ws, min_col=1, min_row=25, max_row=30)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)

    line = LineChart()
    ldata = Reference(ws, min_col=5, max_col=5, min_row=24, max_row=30)
    line.add_data(ldata, titles_from_data=True)
    chart += line
    ws.add_chart(chart, "H8")


def _util_by_year(ramp):
    """Translate the app ramp into 5 yearly utilization fractions (0..1)."""
    if not ramp:
        return [1.0] * 5
    if isinstance(ramp, dict) and ramp.get("utilByYear"):
        vals = [float(v) for v in ramp["utilByYear"]]
    else:
        ceiling = float((ramp or {}).get("ceiling") or 0)
        monthly = [float(x) for x in (ramp or {}).get("monthly") or []]
        if ceiling <= 0 or not monthly:
            return [1.0] * 5
        vals = []
        for y in range(5):
            chunk = monthly[y * 12:(y + 1) * 12]
            vals.append((sum(chunk) / len(chunk) / ceiling) if chunk else 1.0)
    vals = [max(0.0, min(1.0, v)) for v in vals]
    while len(vals) < 5:
        vals.append(1.0)
    return vals[:5]


def build_workbook_bytes(servers, ramp=None, existing_infra_cost=0, shape=None, hide_windows=False):
    shape = _resolve_shape(shape)
    sheet_name = f"BOM w {shape['shortLabel']}"[:31]
    wb = Workbook()
    bom = wb.active
    bom.title = sheet_name
    build_bom_sheet(bom, servers, shape, hide_windows)
    overview = wb.create_sheet("Overview")
    build_overview_sheet(overview, _util_by_year(ramp), float(existing_infra_cost or 0), sheet_name)
    overview.sheet_view.tabSelected = True
    wb.active = wb.sheetnames.index("Overview")
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def servers_from_pricing(pricing, raw_rows=None):
    """Build the per-server list the exporter needs from a pricing payload."""
    os_by_id = {}
    if raw_rows:
        for row in raw_rows:
            text = " ".join(str(v) for v in row.values()).lower()
            os_by_id[row.get("__id")] = "windows" if "windows" in text else ("linux" if "linux" in text else "")
    servers = []
    for row in pricing.get("rows", []):
        specs = row.get("specs", {})
        size = row.get("sizeCheck") or {}
        servers.append({
            "name": row.get("name") or "Server",
            "ocpus": specs.get("ocpus") or 0,
            "memory": specs.get("memoryGb") or 0,
            "disk": specs.get("blockStorageGb") or 0,
            "os": os_by_id.get(row.get("rowId"), ""),
            "environment": row.get("environment") or "",
            "sizeStatus": size.get("status", "ok"),
            "sizeMessage": size.get("message", ""),
        })
    return servers
