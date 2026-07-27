"""Adapt BOM-derived OCI topology into the Boeing architecture renderer.

The LLM plans architecture intent. Deterministic code owns quantities, geometry,
official icon resolution, draw.io authoring, and artifact review.
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT / "scripts"
SHARED_DIR = ROOT / "shared"

for dependency_dir in (SCRIPTS_DIR, SHARED_DIR):
    if str(dependency_dir) not in sys.path:
        sys.path.insert(0, str(dependency_dir))

import render_oci_drawio as boeing_renderer  # noqa: E402
import preview_audit  # noqa: E402
import select_reference_architecture  # noqa: E402


_CATALOG: Any | None = None
_RENDERER: Any | None = None


GROUPING_QUERIES = {
    "tenancy": "tenancy",
    "region": "region",
    "compartment": "compartment",
    "vcn": "VCN",
    "subnet": "subnet",
    "ad": "availability domain",
}

SHAPE_STYLES = {
    "external": (
        "rounded=1;arcSize=8;fillColor=#EEF3F6;strokeColor=#6E8895;"
        "fontColor=#312D2A;fontFamily=Oracle Sans;fontSize=12;"
    ),
    "plain": (
        "rounded=1;arcSize=8;fillColor=#FCFBFA;strokeColor=#9E9892;"
        "fontColor=#312D2A;fontFamily=Oracle Sans;fontSize=12;"
    ),
    "note": (
        "rounded=1;arcSize=8;fillColor=#FFFFFF;strokeColor=#B5B0AA;"
        "fontColor=#312D2A;fontFamily=Oracle Sans;fontSize=11;"
    ),
}


@lru_cache(maxsize=64)
def select_reference_baseline(query: str) -> dict[str, Any]:
    """Return the compact reference bundle used during Boeing architecture planning."""
    bundle = select_reference_architecture.select_reference_bundle(query, max_supporting=2)

    def compact(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None
        return {
            "title": item.get("title"),
            "file": Path(item.get("path", "")).name,
            "score": item.get("score"),
            "viewKind": item.get("view_kind"),
            "tags": item.get("tags", [])[:16],
            "traits": item.get("traits", [])[:16],
            "pageNames": item.get("page_names", [])[:8],
            "sampleLabels": item.get("sample_labels", [])[:16],
            "matchedTags": item.get("matched_tags", [])[:12],
        }

    return {
        "query": query,
        "primary": compact(bundle.get("primary")),
        "supporting": [
            compact(item)
            for item in bundle.get("supplemental", [])
            if compact(item)
        ],
        "uncoveredTags": bundle.get("uncovered_tags", []),
    }


def _clean(value: Any) -> str:
    return "" if value is None else str(value).replace("\xa0", " ").strip()


def _contains(outer: dict[str, Any], inner: dict[str, Any], padding: float = 1.0) -> bool:
    ox, oy = float(outer["x"]), float(outer["y"])
    ow, oh = float(outer["w"]), float(outer["h"])
    ix, iy = float(inner["x"]), float(inner["y"])
    iw, ih = float(inner["w"]), float(inner["h"])
    return (
        ox - padding <= ix
        and oy - padding <= iy
        and ix + iw <= ox + ow + padding
        and iy + ih <= oy + oh + padding
    )


def _area(item: dict[str, Any]) -> float:
    return float(item.get("w", 0)) * float(item.get("h", 0))


def _ordered_containers(containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parent_map = {
        str(container.get("id")): _parent_for(container, containers)
        for container in containers
    }
    depth_cache: dict[str, int] = {}

    def depth(container: dict[str, Any]) -> int:
        identifier = str(container.get("id"))
        if identifier in depth_cache:
            return depth_cache[identifier]
        parent = parent_map.get(identifier)
        result = 0 if parent is None else depth(parent) + 1
        depth_cache[identifier] = result
        return result

    style_order = {
        "tenancy": 0,
        "region": 1,
        "compartment": 2,
        "vcn": 3,
        "ad": 4,
        "subnet": 5,
        "plain": 6,
        "external": 6,
        "note": 7,
    }
    return sorted(
        containers,
        key=lambda item: (
            depth(item),
            style_order.get(_clean(item.get("style")), 6),
            -_area(item),
        ),
    )


def _parent_for(item: dict[str, Any], containers: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        container
        for container in containers
        if container.get("id") != item.get("id") and _contains(container, item)
    ]
    return min(candidates, key=_area) if candidates else None


def _relative_position(item: dict[str, Any], parent: dict[str, Any] | None) -> tuple[float, float]:
    x, y = float(item["x"]), float(item["y"])
    if parent:
        return x - float(parent["x"]), y - float(parent["y"])
    return x, y


def _side_from_fraction(value: Any) -> str | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    x, y = float(value[0]), float(value[1])
    distances = {
        "left": abs(x),
        "right": abs(1 - x),
        "top": abs(y),
        "bottom": abs(1 - y),
    }
    return min(distances, key=distances.get)


def _center(item: dict[str, Any]) -> tuple[float, float]:
    return (
        float(item["x"]) + float(item["w"]) / 2,
        float(item["y"]) + float(item["h"]) / 2,
    )


def _anchor_point(item: dict[str, Any], side: str) -> tuple[float, float]:
    x, y = float(item["x"]), float(item["y"])
    w, h = float(item["w"]), float(item["h"])
    if side == "left":
        return x, y + h / 2
    if side == "right":
        return x + w, y + h / 2
    if side == "top":
        return x + w / 2, y
    return x + w / 2, y + h


def _default_sides(source: dict[str, Any], target: dict[str, Any]) -> tuple[str, str]:
    sx, sy = _center(source)
    tx, ty = _center(target)
    if abs(tx - sx) >= abs(ty - sy):
        return ("right", "left") if tx >= sx else ("left", "right")
    return ("bottom", "top") if ty >= sy else ("top", "bottom")


def _waypoints(
    source: dict[str, Any],
    target: dict[str, Any],
    source_side: str,
    target_side: str,
) -> list[list[float]]:
    start = _anchor_point(source, source_side)
    end = _anchor_point(target, target_side)
    if abs(start[0] - end[0]) < 1 or abs(start[1] - end[1]) < 1:
        return []
    if source_side in {"left", "right"} and target_side in {"left", "right"}:
        middle_x = (start[0] + end[0]) / 2
        return [[middle_x, start[1]], [middle_x, end[1]]]
    if source_side in {"top", "bottom"} and target_side in {"top", "bottom"}:
        middle_y = (start[1] + end[1]) / 2
        return [[start[0], middle_y], [end[0], middle_y]]
    if source_side in {"left", "right"}:
        return [[end[0], start[1]]]
    return [[start[0], end[1]]]


def clarification_gate(options: dict[str, Any], plan: dict[str, Any] | None) -> dict[str, Any]:
    plan = plan or {}
    enable_dr = bool(options.get("enableDr"))
    split_ads = bool(options.get("splitADs"))
    if enable_dr:
        availability = "Cross-region DR with the selected replicated resource types."
    elif split_ads:
        availability = "Single-region multi-AD high availability."
    else:
        availability = "Single-region deployment without an explicit AD split."
    database = _clean(plan.get("databaseStrategy")) or (
        "Use only database services supported by the priced BOM."
    )
    return {
        "status": "satisfied",
        "notes": (
            "Architecture controls and priced BOM evidence satisfy the planning gate. "
            "Unspecified OCI subnet scope follows Oracle's regional-subnet recommendation."
        ),
        "decisions": [
            {
                "topic": "availability",
                "question": "Should the design show HA, DR, or both?",
                "recommended_option": "Use the availability and DR controls selected in the application.",
                "selected_option": availability,
                "resolution_source": "thread_context",
                "rationale": "The application captures the region, AD split, DR region, and replication scope.",
            },
            {
                "topic": "database",
                "question": "Which database type should appear?",
                "recommended_option": "Render only database products present in deterministic pricing.",
                "selected_option": database,
                "resolution_source": "thread_context",
                "rationale": "The priced BOM is the authoritative service and cost source.",
            },
            {
                "topic": "subnet_scope",
                "question": "Should subnets be regional or AD-specific?",
                "recommended_option": "Use regional subnets unless AD-specific framing is explicitly required.",
                "selected_option": "Regional subnets with AD placement shown as background lanes when enabled.",
                "resolution_source": "recommendation_accepted",
                "rationale": "Regional subnet framing is the normal OCI default and avoids implying false AD scope.",
            },
            {
                "topic": "icon_resolution",
                "question": "How should missing service icons be handled?",
                "recommended_option": (
                    "Use direct official OCI icons first, approved aliases second, and an honest "
                    "labeled placeholder only when no official mapping exists."
                ),
                "selected_option": "Use official icons and disclose every fallback in the icon mapping report.",
                "resolution_source": "recommendation_accepted",
                "rationale": "A visually similar but incorrect service icon would make the architecture misleading.",
            },
        ],
    }


def build_boeing_spec(
    legacy_spec: dict[str, Any],
    options: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert the BOM layout into the renderer used by the Boeing OCI workflow."""
    options = options or {}
    reference_query = " ".join(
        part
        for part in [
            "OCI physical landing zone hub spoke migration architecture",
            "multi AD regional subnets" if options.get("splitADs") else "single region",
            "cross region disaster recovery" if options.get("enableDr") else "",
            _clean(legacy_spec.get("title")),
        ]
        if part
    )
    selected_reference = select_reference_baseline(reference_query)
    planned_reference = _clean((plan or {}).get("referenceBaseline"))
    containers = [dict(item) for item in legacy_spec.get("containers", [])]
    nodes = [dict(item) for item in legacy_spec.get("nodes", [])]
    bounds = {
        str(item["id"]): item
        for item in [*containers, *nodes]
        if item.get("id")
    }
    elements: list[dict[str, Any]] = []

    for container in _ordered_containers(containers):
        style = _clean(container.get("style")) or "plain"
        parent = _parent_for(container, containers)
        x, y = _relative_position(container, parent)
        common = {
            "id": container["id"],
            "x": x,
            "y": y,
            "w": float(container["w"]),
            "h": float(container["h"]),
        }
        if parent:
            common["parent"] = parent["id"]
        if style in GROUPING_QUERIES:
            elements.append(
                {
                    **common,
                    "query": GROUPING_QUERIES[style],
                    "value": _clean(container.get("label")).replace("\n", "<br>"),
                }
            )
        else:
            elements.append(
                {
                    **common,
                    "type": "shape",
                    "shape": "rounded-rectangle",
                    "label": _clean(container.get("label")),
                    "style": SHAPE_STYLES.get(style, SHAPE_STYLES["plain"]),
                }
            )

    for node in nodes:
        parent = _parent_for(node, containers)
        x, y = _relative_position(node, parent)
        common = {
            "id": node["id"],
            "x": x,
            "y": y,
            "w": float(node.get("w", 84)),
            "h": float(node.get("h", 84)),
        }
        if parent:
            common["parent"] = parent["id"]
        if "text" in node:
            elements.append(
                {
                    **common,
                    "type": "text",
                    "text": _clean(node.get("text")),
                    "style": (
                        "fontFamily=Oracle Sans;fontSize=11;fontColor=#312D2A;"
                        "align=left;verticalAlign=middle;"
                    ),
                }
            )
        else:
            external_label = _clean(node.get("label"))
            label_lines = max(1, external_label.count("\n") + 1)
            elements.append(
                {
                    **common,
                    "icon_title": _clean(node.get("shape")),
                    "external_label": external_label,
                    "hide_internal_label": True,
                    "external_label_height": max(34, label_lines * 16 + 4),
                    "service_name": _clean(node.get("serviceName")),
                    "skus": list(node.get("skus") or []),
                    "mapping_resolution": _clean(node.get("mappingResolution")),
                }
            )

    routing_anchors: dict[int, dict[str, dict[str, Any]]] = {}
    for index, edge in enumerate(legacy_spec.get("edges", []), start=1):
        source = bounds.get(str(edge.get("source")))
        target = bounds.get(str(edge.get("target")))
        source_anchor = edge.get("sourceAnchor")
        target_anchor = edge.get("targetAnchor")
        if (
            target
            and _clean(target.get("style")) == "vcn"
            and isinstance(target_anchor, (list, tuple))
            and len(target_anchor) == 2
        ):
            target_anchor_id = f"{target['id']}-attachment-{index}"
            target_route_anchor = {
                "id": target_anchor_id,
                "x": float(target["x"]) + float(target["w"]) * float(target_anchor[0]) - 2,
                "y": float(target["y"]) + float(target["h"]) * float(target_anchor[1]) - 2,
                "w": 4,
                "h": 4,
            }
            edge_anchors = {"target": target_route_anchor}
            bounds[target_anchor_id] = target_route_anchor
            elements.append(
                {
                    **target_route_anchor,
                    "type": "shape",
                    "shape": "rounded-rectangle",
                    "label": "",
                    "style": "fillOpacity=0;strokeOpacity=0;opacity=0;",
                }
            )
            if (
                source
                and isinstance(source_anchor, (list, tuple))
                and len(source_anchor) == 2
            ):
                source_anchor_id = f"{source['id']}-attachment-{index}"
                source_route_anchor = {
                    "id": source_anchor_id,
                    "x": float(source["x"]) + float(source["w"]) * float(source_anchor[0]) - 2,
                    "y": float(source["y"]) + float(source["h"]) * float(source_anchor[1]) - 2,
                    "w": 4,
                    "h": 4,
                }
                edge_anchors["source"] = source_route_anchor
                bounds[source_anchor_id] = source_route_anchor
                elements.append(
                    {
                        **source_route_anchor,
                        "type": "shape",
                        "shape": "rounded-rectangle",
                        "label": "",
                        "style": "fillOpacity=0;strokeOpacity=0;opacity=0;",
                    }
                )
            routing_anchors[index] = edge_anchors

    for index, edge in enumerate(legacy_spec.get("edges", []), start=1):
        source_id, target_id = str(edge.get("source")), str(edge.get("target"))
        if index in routing_anchors:
            source_id = routing_anchors[index].get("source", {}).get("id", source_id)
            target_id = routing_anchors[index]["target"]["id"]
        source, target = bounds.get(source_id), bounds.get(target_id)
        if not source or not target:
            continue
        default_source, default_target = _default_sides(source, target)
        source_side = _side_from_fraction(edge.get("sourceAnchor")) or default_source
        target_side = _side_from_fraction(edge.get("targetAnchor")) or default_target
        style_parts = []
        edge_style = _clean(edge.get("style"))
        if edge_style in {"dashed", "backup"}:
            style_parts.append("dashed=1;dashPattern=6 4;")
        if edge_style == "plain":
            style_parts.append("endArrow=none;")
        raw_waypoints = edge.get("waypoints")
        if isinstance(raw_waypoints, list):
            waypoints = [
                [float(point[0]), float(point[1])]
                for point in raw_waypoints
                if isinstance(point, (list, tuple)) and len(point) == 2
            ]
        else:
            waypoints = _waypoints(source, target, source_side, target_side)
        elements.append(
            {
                "id": f"flow-{index}",
                "type": "edge",
                "source": source_id,
                "target": target_id,
                "connector": "physical",
                "label": _clean(edge.get("label")),
                "source_anchor": source_side,
                "target_anchor": target_side,
                "waypoints": waypoints,
                "style": "".join(style_parts),
            }
        )

    page = legacy_spec.get("page") or {}
    return {
        "title": _clean(legacy_spec.get("title")) or "OCI Target Architecture",
        "clarification_gate": clarification_gate(options, plan),
        "architecture_metadata": {
            "workflow": "Boeing OCI architecture authoring pipeline",
            "view": "physical",
            "reference_baseline": planned_reference or selected_reference.get("primary"),
            "supporting_references": selected_reference.get("supporting", []),
            "reference_query": reference_query,
            "reference_rationale": _clean((plan or {}).get("referenceRationale")),
            "availability_posture": _clean((plan or {}).get("availabilityPosture")),
            "subnet_scope": "regional",
            "database_strategy": _clean((plan or {}).get("databaseStrategy")),
            "ingress_strategy": _clean((plan or {}).get("ingressStrategy")),
            "egress_strategy": _clean((plan or {}).get("egressStrategy")),
            "management_strategy": _clean((plan or {}).get("managementStrategy")),
        },
        "pages": [
            {
                "name": "Physical - OCI Target Architecture",
                "page_type": "physical",
                "width": float(page.get("width", 2600)),
                "height": float(page.get("height", 2050)),
                "elements": elements,
            }
        ],
    }


def render_boeing_drawio(
    spec: dict[str, Any],
    out_dir: str | Path,
    name: str = "oci_architecture",
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_path = out_dir / f"{name}_spec.json"
    drawio_path = out_dir / f"{name}.drawio"
    report_path = out_dir / f"{name}_icon_mapping.json"
    quality_path = out_dir / f"{name}_geometry_review.json"
    spec_path.write_text(json.dumps(spec, indent=2) + "\n")

    global _CATALOG, _RENDERER
    if _CATALOG is None:
        _CATALOG = boeing_renderer.SnippetCatalog(ROOT)
    if _RENDERER is None:
        _RENDERER = boeing_renderer.DrawioRenderer(_CATALOG)

    mxfile, report = _RENDERER.render_spec(spec)
    drawio_path.write_text(ET.tostring(mxfile, encoding="unicode"))
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    quality = boeing_renderer.review_render_report(report)
    validation = boeing_renderer.validate_drawio_file(drawio_path)
    quality["drawio_validation"] = validation
    quality_path.write_text(json.dumps(quality, indent=2) + "\n")

    return {
        "drawio": drawio_path,
        "spec": spec_path,
        "report": report_path,
        "quality": quality_path,
        "reportData": report,
        "qualityData": quality,
        "validation": validation,
    }


def inspect_drawio_artifact(
    drawio_path: str | Path,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Inspect compressed draw.io pages and their official OCI icon report."""
    drawio_path = Path(drawio_path)
    validation = boeing_renderer.validate_drawio_file(drawio_path)
    cells = []
    for _page_name, model in boeing_renderer.read_drawio_page_models(drawio_path):
        graph_root = model.find("root")
        if graph_root is not None:
            cells.extend(boeing_renderer.flatten_graph_cells(graph_root))

    report = []
    if report_path:
        candidate = Path(report_path)
        if candidate.exists():
            loaded = json.loads(candidate.read_text())
            if isinstance(loaded, list):
                report = loaded

    official_icons = [
        row
        for row in report
        if row.get("kind") == "library"
        and row.get("role") == "icon"
        and row.get("resolution") in {"direct", "alias", "closest"}
    ]
    placeholders = [
        row
        for row in report
        if (
            row.get("role") == "placeholder"
            or row.get("resolution") in {"placeholder", "unresolved"}
        )
        and (
            _clean(row.get("query"))
            or _clean(row.get("label")).upper().startswith("PLACEHOLDER:")
        )
    ]
    return {
        "validation": validation,
        "cellCount": len(cells),
        "edgeCount": sum(1 for cell in cells if cell.attrib.get("edge") == "1"),
        "officialIconCount": len(official_icons),
        "placeholderCount": len(placeholders),
    }


def write_architecture_review(
    spec_path: str | Path,
    report_path: str | Path,
    geometry_path: str | Path,
    visual_path: str | Path | None,
    out_path: str | Path,
) -> dict[str, Any]:
    """Write the final architecture and visual quality gate used for delivery."""
    spec = json.loads(Path(spec_path).read_text())
    report = json.loads(Path(report_path).read_text())
    geometry = json.loads(Path(geometry_path).read_text())
    visual = {}
    if visual_path and Path(visual_path).exists():
        visual = json.loads(Path(visual_path).read_text())

    metadata = spec.get("architecture_metadata") or {}
    pages = spec.get("pages") or []
    official_icons = [
        row
        for row in report
        if row.get("kind") == "library"
        and row.get("role") == "icon"
        and row.get("resolution") in {"direct", "alias", "closest"}
    ]
    service_placeholders = [
        row
        for row in report
        if row.get("role") == "placeholder" and _clean(row.get("query"))
    ]
    regional_subnets = [
        element
        for page in pages
        for element in page.get("elements", [])
        if "regional" in _clean(
            element.get("value") or element.get("label") or element.get("text")
        ).lower()
        and "subnet" in _clean(
            element.get("value") or element.get("label") or element.get("text")
        ).lower()
    ]
    geometry_issues = geometry.get("issues") or []
    visual_issues = visual.get("issues") or []
    errors = [
        *[
            {
                "gate": "geometry",
                "type": item.get("code"),
                "message": item.get("message"),
            }
            for item in geometry_issues
        ],
        *[
            {
                "gate": "visual",
                "type": item.get("type"),
                "message": item.get("message"),
            }
            for item in visual_issues
            if item.get("severity", "error") == "error"
        ],
    ]
    checks = [
        {
            "name": "clarification_gate",
            "passed": (spec.get("clarification_gate") or {}).get("status") == "satisfied",
            "evidence": "Architecture choices and priced BOM evidence resolved the planning gate.",
        },
        {
            "name": "physical_view",
            "passed": bool(pages) and all(page.get("page_type") == "physical" for page in pages),
            "evidence": f"{len(pages)} physical page(s).",
        },
        {
            "name": "oracle_reference_baseline",
            "passed": bool(metadata.get("reference_baseline")),
            "evidence": metadata.get("reference_baseline"),
        },
        {
            "name": "official_oci_icons",
            "passed": len(official_icons) >= 10 and not service_placeholders,
            "evidence": (
                f"{len(official_icons)} official service icons; "
                f"{len(service_placeholders)} unresolved service placeholders."
            ),
        },
        {
            "name": "regional_subnet_framing",
            "passed": metadata.get("subnet_scope") == "regional" and bool(regional_subnets),
            "evidence": f"{len(regional_subnets)} regional subnet grouping(s).",
        },
        {
            "name": "geometry_review",
            "passed": not geometry_issues,
            "evidence": f"{len(geometry_issues)} geometry finding(s).",
        },
        {
            "name": "visual_review",
            "passed": not errors or not any(item["gate"] == "visual" for item in errors),
            "evidence": f"{len(visual_issues)} visual finding(s).",
        },
    ]
    failed_checks = [check for check in checks if not check["passed"]]
    review = {
        "status": "passed" if not failed_checks and not errors else "needs_review",
        "passed": not failed_checks and not errors,
        "workflow": metadata.get("workflow"),
        "referenceBaseline": metadata.get("reference_baseline"),
        "checks": checks,
        "findings": errors,
    }
    Path(out_path).write_text(json.dumps(review, indent=2) + "\n")
    return review


def review_preview(
    png_path: str | Path,
    report_path: str | Path,
    spec_path: str | Path,
    out_path: str | Path,
) -> dict[str, Any]:
    audit = preview_audit.audit_preview(
        preview_path=Path(png_path),
        report_path=Path(report_path),
        spec_path=Path(spec_path),
        page_name=None,
        page_width=1600,
        page_height=900,
    )
    Path(out_path).write_text(json.dumps(audit, indent=2) + "\n")
    return audit
