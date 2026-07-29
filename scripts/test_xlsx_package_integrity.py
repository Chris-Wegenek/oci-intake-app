#!/usr/bin/env python3
"""Excel-opens-clean checks for the Full BOM export.

Excel refuses a workbook whose package graph is broken - "we found a problem with some content
... do you want us to try to recover" - while openpyxl and LibreOffice happily read the same
file. Neither of those is a substitute for validating the package itself, so this does it
directly: every relationship must resolve to a part that exists, every r:id used in a part must
be declared in that part's rels, [Content_Types].xml must cover every part and reference none
that are missing, and nothing may sit in the zip that the workbook can't reach.
"""

import posixpath
import re
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bom_template

REL = re.compile(r"<Relationship\b[^>]*/>")


def _resolve(owner_part, target):
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(owner_part), target))


def _rels_path(part):
    if not part:
        return "_rels/.rels"
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


def package_faults(blob):
    """Every way this package could make Excel offer to 'recover' the file."""
    z = zipfile.ZipFile(blob)
    names = set(z.namelist())
    content_types = z.read("[Content_Types].xml").decode()
    defaults = {m.group(1).lower()
                for m in re.finditer(r'<Default[^>]*Extension="([^"]+)"', content_types)}
    overrides = {m.group(1).lstrip("/")
                 for m in re.finditer(r'<Override[^>]*PartName="([^"]+)"', content_types)}
    faults = []

    def rels_of(part):
        path = _rels_path(part)
        if path not in names:
            return []
        out = []
        for tag in REL.findall(z.read(path).decode("utf-8", "replace")):
            if 'TargetMode="External"' in tag:
                continue
            rid = re.search(r'Id="([^"]+)"', tag)
            target = re.search(r'Target="([^"]+)"', tag)
            if rid and target:
                out.append((rid.group(1), _resolve(part, target.group(1))))
        return out

    for name in names:
        if not name.endswith(".rels"):
            continue
        owner = "" if name == "_rels/.rels" else name.replace("/_rels/", "/", 1)[:-5]
        for _rid, target in rels_of(owner):
            if target not in names:
                faults.append(f"dangling relationship: {name} -> {target}")

    for name in names:
        if not (name.startswith("xl/") and name.endswith(".xml")):
            continue
        used = set(re.findall(r'r:(?:id|embed)="([^"]+)"',
                              z.read(name).decode("utf-8", "replace")))
        if not used:
            continue
        declared = {rid for rid, _t in rels_of(name)}
        for missing in sorted(used - declared):
            faults.append(f"undeclared relationship id: {name} -> {missing}")

    for name in names:
        if name.endswith("/") or name == "[Content_Types].xml":
            continue
        if name not in overrides and name.rsplit(".", 1)[-1].lower() not in defaults:
            faults.append(f"part has no content type: {name}")
    for override in sorted(overrides):
        if override not in names:
            faults.append(f"content type points at a missing part: {override}")

    # Content-level faults Excel rejects even when the package graph is sound. A conditional
    # formatting rule whose type implies a payload must carry it; openpyxl will happily write
    # <cfRule type="dataBar"/> if the caller never built the DataBar, and Excel then refuses
    # the whole sheet. LibreOffice and openpyxl both read such a file without complaint.
    needs_child = {"dataBar": "dataBar", "colorScale": "colorScale",
                   "iconSet": "iconSet", "cellIs": "formula", "expression": "formula"}
    for name in sorted(names):
        if not name.startswith("xl/worksheets/"):
            continue
        sheet = z.read(name).decode("utf-8", "replace")
        for rule in re.finditer(r"<cfRule\b[^>]*?/>|<cfRule\b[^>]*?>.*?</cfRule>", sheet, re.S):
            body = rule.group(0)
            kind = re.search(r'type="([^"]+)"', body)
            child = needs_child.get(kind.group(1) if kind else "")
            if child and f"<{child}" not in body:
                faults.append(f"conditional rule missing its {child}: {name} {body[:60]}")

    reachable, queue = set(), [""]
    while queue:
        part = queue.pop()
        for _rid, target in rels_of(part):
            if target in names and target not in reachable:
                reachable.add(target)
                queue.append(target)
        path = _rels_path(part)
        if path in names:
            reachable.add(path)
    for name in sorted(names):
        if name in reachable or name in {"[Content_Types].xml", "_rels/.rels"}:
            continue
        faults.append(f"unreachable part: {name}")
    return faults


def _sample_bom(**kwargs):
    fields = [{"key": "server", "sourceHeader": "Server Name"},
              {"key": "app", "sourceHeader": "Application"}]
    rows = [{"__id": f"r{i}", "server": f"SRV{i:03d}", "app": "Finance" if i % 2 else "HR"}
            for i in range(40)]
    priced = [{
        "rowId": f"r{i}", "name": f"SRV{i:03d}",
        "ociProduct": "Compute - Virtual Machine", "ociShape": "VM.Standard.E6.Flex",
        "monthly": 180.0,
        "windowsLicenseMonthly": 40.0 if i % 5 == 0 else 0.0,
        "os": "Windows" if i % 5 == 0 else "Linux",
        "specs": {"ocpus": 4, "memoryGb": 32, "blockStorageGb": 250},
        "lineItems": [
            {"sku": "B93826", "description": "OCPU hr rate", "unit": "OCPU-hour",
             "qty": 4, "rate": 0.0138, "monthly": 41.0},
            {"sku": "B93827", "description": "Memory GB hr", "unit": "GB-hour",
             "qty": 32, "rate": 0.0108, "monthly": 257.0},
        ],
    } for i in range(40)]
    pricing = {"rows": priced, "totals": {"ociMonthly": 7200.0, "monthly": 7200.0}}
    return bom_template.build_full_bom_bytes(
        pricing, rows=rows, fields=fields, bom_name="Package Integrity", **kwargs)


class FullBomPackageIntegrityTests(unittest.TestCase):
    def test_export_opens_without_excel_repair(self):
        import io
        for label, kwargs in (
            ("no diagram", {"include_diagram": False}),
            ("with diagram", {"include_diagram": True}),
            ("workflow embed", {"include_diagram": False,
                                "workflow_json": '{"state":{"step":"price"}}'}),
        ):
            with self.subTest(label):
                faults = package_faults(io.BytesIO(_sample_bom(**kwargs)))
                self.assertEqual(faults, [], f"{label}: " + "; ".join(faults[:6]))

    def test_cleanup_repairs_a_package_with_dangling_drawing_rels(self):
        """The exact corruption shipped once: drawing parts deleted, references left behind."""
        import io, shutil, tempfile
        raw = _sample_bom(include_diagram=False)
        src = zipfile.ZipFile(io.BytesIO(raw))
        broken = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        broken.close()
        with zipfile.ZipFile(broken.name, "w", zipfile.ZIP_DEFLATED) as out:
            for item in src.namelist():
                if re.match(r"xl/drawings/", item):
                    continue                      # drop the parts, keep every reference
                out.writestr(item, src.read(item))
        self.assertTrue(package_faults(broken.name), "fixture should start broken")
        bom_template._strip_orphan_drawings(broken.name)
        self.assertEqual(package_faults(broken.name), [],
                         "cleanup must heal dangling references, not leave them")
        shutil.os.unlink(broken.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
