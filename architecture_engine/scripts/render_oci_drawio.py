#!/usr/bin/env python3
"""Render OCI architecture JSON specs into finalized draw.io files."""

from __future__ import annotations

import argparse
import base64
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import html
from itertools import combinations
import json
import re
from pathlib import Path
from typing import Any
import urllib.parse
import xml.etree.ElementTree as ET
import zlib

from build_icon_catalog import SUPPLEMENTAL_ICONS, normalize, tokenize
from resolve_oci_icon import resolve_icon

DEFAULT_PAGE_WIDTH = 1600
DEFAULT_PAGE_HEIGHT = 900
DEFAULT_ICON_MAX_DIMENSION = 90.0
EDGE_SEGMENT_TOLERANCE = 0.1
EDGE_LANE_OVERLAP_TOLERANCE = 4.0
EDGE_LANE_OVERLAP_MIN_LENGTH = 24.0
EDGE_BORDER_OVERLAP_TOLERANCE = 3.0
EDGE_BORDER_OVERLAP_MIN_LENGTH = 24.0
NODE_OVERLAP_PADDING = 4.0
PARENT_BOUNDARY_TOLERANCE = 2.0
PARENT_CENTER_TOLERANCE = 1.0
MAX_EDGE_BENDS = 3
REQUIRED_CLARIFICATION_TOPICS = (
    "availability",
    "database",
    "subnet_scope",
    "icon_resolution",
)
ALLOWED_CLARIFICATION_GATE_STATUSES = {"satisfied", "waived"}
ALLOWED_DECISION_RESOLUTION_SOURCES = {
    "user_answer",
    "thread_context",
    "recommendation_accepted",
    "assumed",
    "not_applicable",
}

TEXT_STYLE = (
    "whiteSpace=wrap;html=1;strokeColor=none;fillColor=none;align=center;"
    "verticalAlign=middle;fontFamily=Oracle Sans;fontSize=11;fontColor=#312D2A;"
)

PLACEHOLDER_STYLES = {
    "rounded-rectangle": (
        "rounded=1;whiteSpace=wrap;html=1;arcSize=10;fillColor=#FCFBFA;"
        "strokeColor=#9E9892;fontColor=#312D2A;fontFamily=Oracle Sans;"
        "fontSize=11;dashed=1;dashPattern=4 4;"
    ),
    "cylinder": (
        "shape=cylinder;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;"
        "fillColor=#FCFBFA;strokeColor=#9E9892;fontColor=#312D2A;"
        "fontFamily=Oracle Sans;fontSize=11;dashed=1;dashPattern=4 4;"
    ),
    "hexagon": (
        "shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;"
        "fillColor=#FCFBFA;strokeColor=#9E9892;fontColor=#312D2A;"
        "fontFamily=Oracle Sans;fontSize=11;dashed=1;dashPattern=4 4;"
    ),
    "cloud": (
        "shape=cloud;whiteSpace=wrap;html=1;fillColor=#FCFBFA;strokeColor=#9E9892;"
        "fontColor=#312D2A;fontFamily=Oracle Sans;fontSize=11;dashed=1;"
        "dashPattern=4 4;"
    ),
    "ellipse": (
        "ellipse;whiteSpace=wrap;html=1;fillColor=#FCFBFA;strokeColor=#9E9892;"
        "fontColor=#312D2A;fontFamily=Oracle Sans;fontSize=11;dashed=1;"
        "dashPattern=4 4;"
    ),
}

ANCHOR_STYLE_HINTS = {
    "strokeColor=none",
    "fillColor=none",
}

CONNECTOR_STYLES = {
    "physical": (
        "endArrow=open;html=1;startArrow=none;startFill=0;endFill=0;rounded=0;"
        "fontFamily=Oracle Sans;fontSize=10.5;fontColor=#312D2A;"
        "labelBackgroundColor=none;strokeColor=#312D2A;"
        "edgeStyle=orthogonalEdgeStyle;orthogonalLoop=1;jettySize=auto;"
        "jumpStyle=gap;jumpSize=6;endSize=6;elbow=vertical;"
    ),
    "logical-dataflow": (
        "endArrow=open;html=1;startArrow=none;startFill=0;endFill=0;rounded=0;"
        "fontFamily=Oracle Sans;fontSize=10.5;fontColor=#312D2A;"
        "labelBackgroundColor=none;strokeColor=#312D2A;"
        "edgeStyle=orthogonalEdgeStyle;orthogonalLoop=1;jettySize=auto;"
        "jumpStyle=gap;jumpSize=6;endSize=6;elbow=vertical;"
    ),
    "logical-user": (
        "endArrow=open;html=1;startArrow=none;startFill=0;endFill=0;rounded=0;"
        "fontFamily=Oracle Sans;fontSize=10.5;fontColor=#312D2A;"
        "labelBackgroundColor=none;strokeColor=#312D2A;"
        "edgeStyle=orthogonalEdgeStyle;orthogonalLoop=1;jettySize=auto;"
        "jumpStyle=gap;jumpSize=6;dashed=1;endSize=6;elbow=vertical;"
    ),
}

CONNECTOR_KEY_ALIASES = {
    "physical": "physical",
    "physical connector": "physical",
    "logical": "logical-dataflow",
    "logical dataflow": "logical-dataflow",
    "logical-dataflow": "logical-dataflow",
    "dataflow": "logical-dataflow",
    "logical user": "logical-user",
    "logical-user": "logical-user",
    "logical user interaction": "logical-user",
    "user interaction": "logical-user",
    "user": "logical-user",
}

ANCHOR_POINTS = {
    "left": ("0", "0.5"),
    "right": ("1", "0.5"),
    "top": ("0.5", "0"),
    "bottom": ("0.5", "1"),
}

VCN_LIKE_TITLES = {
    "Physical - Grouping - VCN",
    "Physical - Grouping - Subnet",
}

HORIZONTAL_SPECIAL_CONNECTOR_TITLES = {
    "Physical - Special Connectors - FastConnect - Horizontal",
    "Physical - Special Connectors - Remote Peering - Horizontal",
}

UNPARENTED_LIBRARY_ICON_ALLOWLIST = {
    "Networking - Customer Premises Equipment CPE",
}


@dataclass
class Snippet:
    title: str
    source: str
    cells: list[ET.Element]
    root_ids: list[str]
    text_cell_ids: list[str]
    width: float
    height: float


@dataclass
class ToolkitIndex:
    cells: list[ET.Element]
    by_id: dict[str, ET.Element]
    children: dict[str, list[str]]
    positions: dict[str, tuple[float, float]]
    root_ids: list[str]
    texts_by_root: dict[str, list[str]]


def parse_number(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


def format_number(value: float) -> str:
    rounded = round(value, 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def strip_html(value: str) -> str:
    cleaned = html.unescape(value or "").replace("\xa0", " ")
    cleaned = re.sub(r"<br\s*/?>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return " ".join(cleaned.split())


def text_to_html(value: str) -> str:
    return html.escape(value).replace("\n", "<br>")


def require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def validate_clarification_gate(spec: dict[str, Any]) -> None:
    gate = spec.get("clarification_gate")
    if not isinstance(gate, dict):
        raise ValueError("Spec must include a top-level clarification_gate object before rendering.")

    status = require_non_empty_string(gate.get("status"), "clarification_gate.status").lower()
    if status not in ALLOWED_CLARIFICATION_GATE_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_CLARIFICATION_GATE_STATUSES))
        raise ValueError(f"clarification_gate.status must be one of: {allowed}.")

    require_non_empty_string(gate.get("notes"), "clarification_gate.notes")

    if status == "waived":
        require_non_empty_string(gate.get("waiver_reason"), "clarification_gate.waiver_reason")
        return

    decisions = gate.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ValueError("clarification_gate.decisions must be a non-empty list when status is 'satisfied'.")

    seen_topics: set[str] = set()
    for index, decision in enumerate(decisions, start=1):
        if not isinstance(decision, dict):
            raise ValueError(f"clarification_gate.decisions[{index}] must be an object.")

        prefix = f"clarification_gate.decisions[{index}]"
        topic = require_non_empty_string(decision.get("topic"), f"{prefix}.topic").lower()
        if topic in seen_topics:
            raise ValueError(f"{prefix}.topic duplicates '{topic}'. Each clarification topic must appear only once.")
        seen_topics.add(topic)

        require_non_empty_string(decision.get("question"), f"{prefix}.question")
        require_non_empty_string(decision.get("recommended_option"), f"{prefix}.recommended_option")
        require_non_empty_string(decision.get("selected_option"), f"{prefix}.selected_option")
        resolution_source = require_non_empty_string(decision.get("resolution_source"), f"{prefix}.resolution_source").lower()
        if resolution_source not in ALLOWED_DECISION_RESOLUTION_SOURCES:
            allowed = ", ".join(sorted(ALLOWED_DECISION_RESOLUTION_SOURCES))
            raise ValueError(f"{prefix}.resolution_source must be one of: {allowed}.")
        require_non_empty_string(decision.get("rationale"), f"{prefix}.rationale")

    missing_topics = [topic for topic in REQUIRED_CLARIFICATION_TOPICS if topic not in seen_topics]
    if missing_topics:
        joined = ", ".join(missing_topics)
        raise ValueError(
            "clarification_gate.decisions is missing required topics: "
            f"{joined}. Record the selected and recommended options before rendering."
        )


def library_role(icon_title: str | None) -> str:
    title = str(icon_title or "")
    if " - Special Connectors - " in title:
        return "special-connector"
    if " - Grouping - " in title or title in VCN_LIKE_TITLES:
        return "grouping"
    return "icon"


def scale_dimensions_to_max_dimension(width: float, height: float, max_dimension: float) -> tuple[float, float]:
    largest = max(width, height, 0.0)
    if largest <= 0:
        return width, height
    scale = max_dimension / largest
    return width * scale, height * scale


def fit_dimensions_within_box(
    native_width: float,
    native_height: float,
    max_width: float,
    max_height: float,
) -> tuple[float, float]:
    if native_width <= 0 or native_height <= 0:
        return max_width, max_height
    scale = min(max_width / native_width, max_height / native_height)
    return native_width * scale, native_height * scale


def append_style(style: str, additions: dict[str, str] | str | None = None) -> str:
    if not additions:
        return style

    if isinstance(additions, str):
        extra = additions.strip().strip(";")
    else:
        extra = ";".join(f"{key}={value}" for key, value in additions.items() if value is not None)
    if not extra:
        return style
    if style and not style.endswith(";"):
        style += ";"
    return style + extra + ";"


def is_anchor_shape_element(element: dict[str, Any], width: float, height: float, style: str) -> bool:
    identifier = str(element.get("id") or "")
    if identifier.endswith("-anchor"):
        return True
    if max(width, height) > 6.0:
        return False
    return all(fragment in style for fragment in ANCHOR_STYLE_HINTS)


def same_point(
    first: tuple[float, float],
    second: tuple[float, float],
    *,
    tolerance: float = EDGE_SEGMENT_TOLERANCE,
) -> bool:
    return abs(first[0] - second[0]) <= tolerance and abs(first[1] - second[1]) <= tolerance


def orthogonalize_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not points:
        return []

    orthogonal: list[tuple[float, float]] = [points[0]]
    for current in points[1:]:
        previous = orthogonal[-1]
        if abs(previous[0] - current[0]) <= EDGE_SEGMENT_TOLERANCE or abs(previous[1] - current[1]) <= EDGE_SEGMENT_TOLERANCE:
            orthogonal.append(current)
            continue

        if len(orthogonal) >= 2:
            prior = orthogonal[-2]
            if abs(prior[0] - previous[0]) <= EDGE_SEGMENT_TOLERANCE:
                elbow = (previous[0], current[1])
            elif abs(prior[1] - previous[1]) <= EDGE_SEGMENT_TOLERANCE:
                elbow = (current[0], previous[1])
            else:
                elbow = (current[0], previous[1])
        elif abs(current[0] - previous[0]) >= abs(current[1] - previous[1]):
            elbow = (current[0], previous[1])
        else:
            elbow = (previous[0], current[1])

        if not same_point(previous, elbow):
            orthogonal.append(elbow)
        if not same_point(orthogonal[-1], current):
            orthogonal.append(current)

    return orthogonal


def simplify_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    simplified: list[tuple[float, float]] = []
    for point in points:
        if simplified and same_point(simplified[-1], point):
            continue
        simplified.append(point)

    index = 1
    while index < len(simplified) - 1:
        previous = simplified[index - 1]
        current = simplified[index]
        following = simplified[index + 1]
        same_x = abs(previous[0] - current[0]) <= EDGE_SEGMENT_TOLERANCE and abs(current[0] - following[0]) <= EDGE_SEGMENT_TOLERANCE
        same_y = abs(previous[1] - current[1]) <= EDGE_SEGMENT_TOLERANCE and abs(current[1] - following[1]) <= EDGE_SEGMENT_TOLERANCE
        if same_x or same_y:
            simplified.pop(index)
            continue
        index += 1

    return simplified


def normalize_connector_points(
    start: tuple[float, float],
    end: tuple[float, float],
    waypoints: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    return simplify_points(orthogonalize_points([start, *waypoints, end]))


def encode_diagram(xml_text: str) -> str:
    encoded = urllib.parse.quote(xml_text, safe="~()*!.'")
    compressor = zlib.compressobj(level=9, wbits=-15)
    compressed = compressor.compress(encoded.encode("utf-8")) + compressor.flush()
    return base64.b64encode(compressed).decode("ascii")


def decode_diagram(payload: str) -> str:
    text = (payload or "").strip()
    if text.startswith("<mxGraphModel"):
        return text
    return urllib.parse.unquote(zlib.decompress(base64.b64decode(text), -15).decode("utf-8"))


def flatten_graph_cells(graph_root: ET.Element) -> list[ET.Element]:
    cells: list[ET.Element] = []
    for child in graph_root:
        if child.tag == "mxCell":
            cells.append(deepcopy(child))
            continue

        nested = child.find("mxCell")
        if nested is None:
            continue

        merged = ET.Element("mxCell")
        for key, value in nested.attrib.items():
            merged.set(key, value)

        if "id" not in merged.attrib and child.attrib.get("id"):
            merged.set("id", child.attrib["id"])

        if "value" not in merged.attrib:
            if child.attrib.get("value") is not None:
                merged.set("value", child.attrib["value"])
            elif child.attrib.get("label") is not None:
                merged.set("value", child.attrib["label"])

        for grandchild in nested:
            merged.append(deepcopy(grandchild))

        cells.append(merged)

    return cells


def build_cell_indexes(cells: list[ET.Element]) -> tuple[dict[str, ET.Element], dict[str, list[str]]]:
    by_id: dict[str, ET.Element] = {}
    children: dict[str, list[str]] = {}

    for cell in cells:
        cell_id = cell.attrib.get("id")
        if not cell_id:
            raise ValueError("Encountered a cell without an id.")
        by_id[cell_id] = cell
        parent = cell.attrib.get("parent")
        if parent:
            children.setdefault(parent, []).append(cell_id)

    return by_id, children


def build_absolute_positions(by_id: dict[str, ET.Element]) -> dict[str, tuple[float, float]]:
    cache: dict[str, tuple[float, float]] = {}

    def resolve(cell_id: str) -> tuple[float, float]:
        if cell_id in cache:
            return cache[cell_id]

        cell = by_id[cell_id]
        geometry = cell.find("mxGeometry")
        x = parse_number(geometry.attrib.get("x")) if geometry is not None else 0.0
        y = parse_number(geometry.attrib.get("y")) if geometry is not None else 0.0
        parent = cell.attrib.get("parent")

        if parent and parent in by_id and parent not in {"0", "1"}:
            parent_x, parent_y = resolve(parent)
            x += parent_x
            y += parent_y

        cache[cell_id] = (x, y)
        return cache[cell_id]

    for cell_id in by_id:
        resolve(cell_id)

    return cache


def collect_descendant_ids(root_id: str, children: dict[str, list[str]]) -> list[str]:
    ordered: list[str] = []
    stack = list(reversed(children.get(root_id, [])))

    while stack:
        current = stack.pop()
        ordered.append(current)
        stack.extend(reversed(children.get(current, [])))

    return ordered


def cell_bbox(cell_id: str, by_id: dict[str, ET.Element], positions: dict[str, tuple[float, float]]) -> tuple[float, float, float, float]:
    cell = by_id[cell_id]
    geometry = cell.find("mxGeometry")
    x, y = positions[cell_id]
    width = parse_number(geometry.attrib.get("width")) if geometry is not None else 0.0
    height = parse_number(geometry.attrib.get("height")) if geometry is not None else 0.0
    return x, y, x + width, y + height


def build_snippet(title: str, source: str, cells: list[ET.Element], root_ids: list[str]) -> Snippet:
    by_id, children = build_cell_indexes(cells)
    positions = build_absolute_positions(by_id)

    selected_ids: list[str] = []
    for root_id in root_ids:
        selected_ids.append(root_id)
        selected_ids.extend(collect_descendant_ids(root_id, children))

    selected_set = set(selected_ids)
    ordered_cells = [deepcopy(cell) for cell in cells if cell.attrib["id"] in selected_set]
    ordered_by_id = {cell.attrib["id"]: cell for cell in ordered_cells}

    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    for cell_id in selected_ids:
        x1, y1, x2, y2 = cell_bbox(cell_id, by_id, positions)
        min_x = min(min_x, x1)
        min_y = min(min_y, y1)
        max_x = max(max_x, x2)
        max_y = max(max_y, y2)

    if min_x == float("inf") or max_x == float("-inf"):
        min_x = 0.0
        min_y = 0.0
        max_x = 0.0
        max_y = 0.0

    for root_id in root_ids:
        geometry = ordered_by_id[root_id].find("mxGeometry")
        if geometry is None:
            continue
        new_x = parse_number(geometry.attrib.get("x")) - min_x
        new_y = parse_number(geometry.attrib.get("y")) - min_y
        geometry.set("x", format_number(new_x))
        geometry.set("y", format_number(new_y))

    text_rows: list[tuple[float, float, str]] = []
    for cell_id in selected_ids:
        value = ordered_by_id[cell_id].attrib.get("value", "")
        plain = strip_html(value)
        if not plain:
            continue
        abs_x, abs_y = positions[cell_id]
        text_rows.append((abs_y - min_y, abs_x - min_x, cell_id))

    text_rows.sort()
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)

    return Snippet(
        title=title,
        source=source,
        cells=ordered_cells,
        root_ids=list(root_ids),
        text_cell_ids=[cell_id for _, _, cell_id in text_rows],
        width=width,
        height=height,
    )


def parse_library_snippets(library_path: Path) -> dict[str, Snippet]:
    content = library_path.read_text()
    match = re.search(r"<mxlibrary>(.*)</mxlibrary>", content, re.DOTALL)
    if not match:
        raise ValueError(f"Could not find <mxlibrary> payload in {library_path}")

    snippets: dict[str, Snippet] = {}
    for raw_item in json.loads(match.group(1)):
        title = " ".join(html.unescape(raw_item.get("title", "")).replace("\xa0", " ").split())
        encoded_xml = raw_item.get("xml")
        if not title or not encoded_xml:
            continue
        xml_text = decode_diagram(encoded_xml)
        model = ET.fromstring(xml_text)
        cells = flatten_graph_cells(model.find("root"))
        root_ids = [cell.attrib["id"] for cell in cells if cell.attrib.get("parent") == "1"]
        snippets[title] = build_snippet(title, "oci-library.xml", cells, root_ids)

    return snippets


def build_toolkit_index(toolkit_path: Path) -> ToolkitIndex:
    mxfile = ET.fromstring(toolkit_path.read_text())
    icons_page = None
    for diagram in mxfile.findall("diagram"):
        if diagram.attrib.get("name") == "Icons":
            icons_page = diagram
            break

    if icons_page is None:
        raise ValueError(f"Could not find Icons page in {toolkit_path}")

    model = ET.fromstring(decode_diagram(icons_page.text or ""))
    cells = flatten_graph_cells(model.find("root"))
    by_id, children = build_cell_indexes(cells)
    positions = build_absolute_positions(by_id)
    root_ids = [cell_id for cell_id, cell in by_id.items() if cell.attrib.get("parent") == "1"]
    texts_by_root: dict[str, list[str]] = {}

    for root_id in root_ids:
        text_rows: list[tuple[float, float, str]] = []
        for cell_id in [root_id, *collect_descendant_ids(root_id, children)]:
            plain = strip_html(by_id[cell_id].attrib.get("value", ""))
            if not plain:
                continue
            abs_x, abs_y = positions[cell_id]
            text_rows.append((abs_y, abs_x, plain))
        text_rows.sort()
        texts_by_root[root_id] = [plain for _, _, plain in text_rows]

    return ToolkitIndex(
        cells=cells,
        by_id=by_id,
        children=children,
        positions=positions,
        root_ids=root_ids,
        texts_by_root=texts_by_root,
    )


def score_toolkit_candidate(target_name: str, texts: list[str]) -> float:
    if not texts:
        return 0.0

    target_norm = normalize(target_name)
    target_tokens = set(tokenize(target_name))
    best = 0.0
    candidates: list[str] = [" ".join(texts), *texts]

    if len(texts) > 2:
        for start in range(len(texts)):
            for end in range(start + 2, len(texts) + 1):
                candidates.append(" ".join(texts[start:end]))

    seen: set[str] = set()
    for candidate in candidates:
        candidate_norm = normalize(candidate)
        if not candidate_norm or candidate_norm in seen:
            continue
        seen.add(candidate_norm)
        candidate_tokens = set(tokenize(candidate))

        if candidate_norm == target_norm:
            return 1.0

        if candidate_norm in target_norm or target_norm in candidate_norm:
            best = max(best, 0.95)

        overlap = len(candidate_tokens & target_tokens)
        if overlap:
            ratio = overlap / max(len(target_tokens), 1)
            if candidate_tokens <= target_tokens or target_tokens <= candidate_tokens:
                ratio += 0.1
            best = max(best, min(ratio, 0.89))

    return best


class SnippetCatalog:
    def __init__(self, skill_dir: Path) -> None:
        self.skill_dir = skill_dir
        self.library_path = skill_dir / "assets" / "drawio" / "oci-library.xml"
        self.toolkit_path = skill_dir / "assets" / "drawio" / "oci-architecture-toolkit-v24.2.drawio"
        self.library_snippets = parse_library_snippets(self.library_path)
        self.toolkit_index: ToolkitIndex | None = None
        self.toolkit_cache: dict[str, Snippet] = {}
        self.toolkit_titles = {entry["title"] for entry in SUPPLEMENTAL_ICONS}

    def get(self, title: str) -> Snippet:
        if title in self.library_snippets:
            return self.library_snippets[title]
        if title in self.toolkit_cache:
            return self.toolkit_cache[title]
        if title not in self.toolkit_titles:
            raise KeyError(f"Icon title not found in bundled OCI assets: {title}")

        snippet = self._extract_toolkit_snippet(title)
        self.toolkit_cache[title] = snippet
        return snippet

    def _extract_toolkit_snippet(self, title: str) -> Snippet:
        if self.toolkit_index is None:
            self.toolkit_index = build_toolkit_index(self.toolkit_path)

        assert self.toolkit_index is not None
        target_name = title.split(" - ", 1)[1] if " - " in title else title
        best_root_id = None
        best_score = 0.0
        best_area = float("inf")

        for root_id in self.toolkit_index.root_ids:
            texts = self.toolkit_index.texts_by_root.get(root_id, [])
            score = score_toolkit_candidate(target_name, texts)
            if score <= 0:
                continue
            x1, y1, x2, y2 = cell_bbox(root_id, self.toolkit_index.by_id, self.toolkit_index.positions)
            area = max(x2 - x1, 1.0) * max(y2 - y1, 1.0)
            if score > best_score or (abs(score - best_score) < 1e-9 and area < best_area):
                best_root_id = root_id
                best_score = score
                best_area = area

        if best_root_id is None or best_score < 0.6:
            raise KeyError(
                f"Could not locate a toolkit snippet for '{title}'. "
                f"Best score was {round(best_score, 3)}."
            )

        return build_snippet(
            title=title,
            source="toolkit-v24.2-icons-page",
            cells=self.toolkit_index.cells,
            root_ids=[best_root_id],
        )


def new_graph_model(width: float, height: float) -> ET.Element:
    model = ET.Element(
        "mxGraphModel",
        {
            "dx": format_number(width),
            "dy": format_number(height),
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": format_number(width),
            "pageHeight": format_number(height),
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    return model


class DrawioRenderer:
    def __init__(self, catalog: SnippetCatalog) -> None:
        self.catalog = catalog
        self._next_id = 2

    def _new_id(self) -> str:
        value = f"cell-{self._next_id}"
        self._next_id += 1
        return value

    def render_spec(self, spec: dict[str, Any]) -> tuple[ET.Element, list[dict[str, Any]]]:
        validate_clarification_gate(spec)
        self._next_id = 2
        created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        mxfile = ET.Element(
            "mxfile",
            {
                "host": "app.diagrams.net",
                "modified": created,
                "agent": "Codex OCI architecture renderer",
                "version": "24.2.5",
                "type": "device",
            },
        )

        report: list[dict[str, Any]] = []
        pages = spec.get("pages", [])
        for index, page in enumerate(pages, start=1):
            diagram, page_report = self.render_page(page, index)
            mxfile.append(diagram)
            report.extend(page_report)

        return mxfile, report

    def render_page(self, page: dict[str, Any], page_number: int) -> tuple[ET.Element, list[dict[str, Any]]]:
        width = float(page.get("width", DEFAULT_PAGE_WIDTH))
        height = float(page.get("height", DEFAULT_PAGE_HEIGHT))
        page_type = str(page.get("page_type", "physical"))
        page_name = str(page.get("name", f"Page {page_number}"))
        model = new_graph_model(width, height)
        root = model.find("root")
        assert root is not None

        placed: dict[str, dict[str, Any]] = {}
        report: list[dict[str, Any]] = []

        elements = page.get("elements", [])
        node_elements = [element for element in elements if self._element_kind(element) != "edge"]
        edge_elements = [element for element in elements if self._element_kind(element) == "edge"]

        for element in node_elements:
            record = self._render_non_edge(root, element, page_type, placed)
            record["page"] = page_name
            report.append(record)

        for element in edge_elements:
            record = self._render_edge(root, element, page_type, placed)
            record["page"] = page_name
            report.append(record)

        diagram = ET.Element("diagram", {"id": f"page-{page_number}", "name": page_name})
        diagram.text = encode_diagram(ET.tostring(model, encoding="unicode"))
        return diagram, report

    def _element_kind(self, element: dict[str, Any]) -> str:
        kind = str(element.get("type", "")).strip().lower()
        if kind:
            if kind in {"library", "icon", "container", "service"}:
                return "library"
            if kind in {"shape", "placeholder"}:
                return "shape"
            if kind == "text":
                return "text"
            if kind == "edge":
                return "edge"
            return kind

        if "source" in element and "target" in element:
            return "edge"
        if element.get("shape") or element.get("placeholder_shape"):
            return "shape"
        if element.get("text") and not element.get("query") and not element.get("icon_title"):
            return "text"
        return "library"

    def _resolve_position(self, element: dict[str, Any], placed: dict[str, dict[str, Any]]) -> tuple[float, float]:
        x = float(element.get("x", 0))
        y = float(element.get("y", 0))
        parent_ref = element.get("parent")
        if parent_ref:
            if parent_ref not in placed:
                raise KeyError(f"Parent reference '{parent_ref}' was used before it was placed.")
            x += placed[parent_ref]["x"]
            y += placed[parent_ref]["y"]
        return x, y

    def _resolve_library_dimensions(
        self,
        element: dict[str, Any],
        snippet: Snippet,
        icon_title: str,
    ) -> tuple[float, float, str, str]:
        role = library_role(icon_title)
        explicit_width = element.get("w", element.get("width"))
        explicit_height = element.get("h", element.get("height"))

        size_policy = str(element.get("size_policy", "")).strip().lower()
        if role == "special-connector":
            default_width, default_height = self._special_connector_root_dimensions(snippet)
            default_mode = "native-special-connector"
        elif role == "grouping" or size_policy == "native":
            default_width = snippet.width
            default_height = snippet.height
            default_mode = "native"
        else:
            max_dimension = float(element.get("icon_max_dimension", DEFAULT_ICON_MAX_DIMENSION))
            default_width, default_height = scale_dimensions_to_max_dimension(
                snippet.width,
                snippet.height,
                max_dimension,
            )
            default_mode = "normalized-default"

        if explicit_width is not None and explicit_height is not None:
            explicit_box_width = float(explicit_width)
            explicit_box_height = float(explicit_height)
            if role == "icon" and not bool(element.get("allow_aspect_distortion")):
                fitted_width, fitted_height = fit_dimensions_within_box(
                    snippet.width,
                    snippet.height,
                    explicit_box_width,
                    explicit_box_height,
                )
                return fitted_width, fitted_height, "explicit-fit", role
            return explicit_box_width, explicit_box_height, "explicit", role

        if explicit_width is not None:
            width = float(explicit_width)
            if default_width > 0:
                height = width * (default_height / default_width)
            else:
                height = default_height
            return width, height, "explicit", role

        if explicit_height is not None:
            height = float(explicit_height)
            if default_height > 0:
                width = height * (default_width / default_height)
            else:
                width = default_width
            return width, height, "explicit", role

        return default_width, default_height, default_mode, role

    def _special_connector_root_dimensions(self, snippet: Snippet) -> tuple[float, float]:
        if not snippet.root_ids:
            return snippet.width, snippet.height

        root_id = snippet.root_ids[0]
        geometry = next(
            (
                cell.find("mxGeometry")
                for cell in snippet.cells
                if cell.attrib.get("id") == root_id
            ),
            None,
        )
        if geometry is None:
            return snippet.width, snippet.height

        width = parse_number(geometry.attrib.get("width"), snippet.width)
        height = parse_number(geometry.attrib.get("height"), snippet.height)
        return width or snippet.width, height or snippet.height

    def _special_connector_parts(
        self,
        snippet: Snippet,
    ) -> tuple[str, float, float, str | None, str | None]:
        image_style: str | None = None
        image_width = 0.0
        image_height = 0.0
        text_value: str | None = None
        text_style: str | None = None

        for cell in snippet.cells:
            style = cell.attrib.get("style", "")
            geometry = cell.find("mxGeometry")
            if "shape=image" in style and geometry is not None and image_style is None:
                image_style = style
                image_width = parse_number(geometry.attrib.get("width"), 0.0)
                image_height = parse_number(geometry.attrib.get("height"), 0.0)
                continue
            if strip_html(cell.attrib.get("value", "")) and geometry is not None and text_value is None:
                text_value = cell.attrib.get("value")
                text_style = style

        if image_style is None or image_width <= 0 or image_height <= 0:
            raise ValueError(f"Special connector snippet '{snippet.title}' is missing its image payload.")

        return image_style, image_width, image_height, text_value, text_style

    def _render_non_edge(
        self,
        root: ET.Element,
        element: dict[str, Any],
        page_type: str,
        placed: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        kind = self._element_kind(element)
        if kind == "text":
            return self._render_text(root, element, placed)
        if kind == "shape":
            return self._render_shape(root, element, placed, resolution="placeholder")
        return self._render_library(root, element, page_type, placed)

    def _render_text(self, root: ET.Element, element: dict[str, Any], placed: dict[str, dict[str, Any]]) -> dict[str, Any]:
        x, y = self._resolve_position(element, placed)
        width = float(element.get("w", element.get("width", 120)))
        height = float(element.get("h", element.get("height", 20)))
        text = str(element.get("text", element.get("label", element.get("value", ""))))
        style = append_style(TEXT_STYLE, element.get("style"))
        value = text if element.get("html") else text_to_html(text)

        cell_id = self._new_id()
        cell = ET.Element(
            "mxCell",
            {
                "id": cell_id,
                "value": value,
                "style": style,
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": format_number(x),
                "y": format_number(y),
                "width": format_number(width),
                "height": format_number(height),
                "as": "geometry",
            },
        )
        root.append(cell)

        if element.get("id"):
            placed[str(element["id"])] = {
                "x": x,
                "y": y,
                "w": width,
                "h": height,
                "cell_id": cell_id,
            }

        return {
            "element_id": element.get("id"),
            "parent_element_id": element.get("parent"),
            "kind": "text",
            "role": "text",
            "resolution": "text",
            "icon_title": None,
            "source": None,
            "query": None,
            "cell_id": cell_id,
            "x": x,
            "y": y,
            "w": width,
            "h": height,
        }

    def _render_shape(
        self,
        root: ET.Element,
        element: dict[str, Any],
        placed: dict[str, dict[str, Any]],
        resolution: str,
        query: str | None = None,
    ) -> dict[str, Any]:
        x, y = self._resolve_position(element, placed)
        width = float(element.get("w", element.get("width", 110)))
        height = float(element.get("h", element.get("height", 70)))
        shape_name = str(element.get("shape", element.get("placeholder_shape", "rounded-rectangle")))
        style = PLACEHOLDER_STYLES.get(shape_name)
        if style is None:
            raise KeyError(f"Unsupported placeholder shape: {shape_name}")
        style = append_style(style, element.get("style"))
        label = str(element.get("label", element.get("value", element.get("text", ""))))
        is_anchor = is_anchor_shape_element(element, width, height, style)

        cell_id = self._new_id()
        cell = ET.Element(
            "mxCell",
            {
                "id": cell_id,
                "value": text_to_html(label),
                "style": style,
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": format_number(x),
                "y": format_number(y),
                "width": format_number(width),
                "height": format_number(height),
                "as": "geometry",
            },
        )
        root.append(cell)

        if element.get("id"):
            placed[str(element["id"])] = {
                "x": x,
                "y": y,
                "w": width,
                "h": height,
                "cell_id": cell_id,
            }

        return {
            "element_id": element.get("id"),
            "parent_element_id": element.get("parent"),
            "kind": "shape",
            "role": "anchor" if is_anchor else "placeholder",
            "resolution": "anchor" if is_anchor else resolution,
            "icon_title": None,
            "source": None,
            "query": query,
            "label": element.get("label"),
            "placeholder_shape": shape_name,
            "cell_id": cell_id,
            "x": x,
            "y": y,
            "w": width,
            "h": height,
        }

    def _render_library(
        self,
        root: ET.Element,
        element: dict[str, Any],
        page_type: str,
        placed: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        query = element.get("query")
        icon_title = element.get("icon_title") or element.get("title")
        source = "explicit"
        resolution = "direct"

        if not icon_title and not query:
            raise ValueError("Library elements must provide either 'query' or 'icon_title'.")

        if not icon_title:
            result = resolve_icon(str(query), page=str(element.get("page", page_type)))
            resolution = result["resolution"]
            source = result.get("source")
            if resolution == "placeholder":
                placeholder_label = str(element.get("label", result.get("label_template", f"PLACEHOLDER: {query}")))
                placeholder_element = dict(element)
                placeholder_element["placeholder_shape"] = result["placeholder_shape"]
                placeholder_element["label"] = placeholder_label
                record = self._render_shape(root, placeholder_element, placed, resolution="placeholder", query=str(query))
                record["closest_official_icon"] = result.get("closest_official_icon")
                return record
            icon_title = result["icon_title"]

        try:
            snippet = self.catalog.get(str(icon_title))
        except KeyError:
            original_icon_title = str(icon_title)
            page = str(element.get("page", page_type))
            candidates = [str(query)] if query else []
            if " - " in original_icon_title:
                candidates.append(original_icon_title.split(" - ", 1)[1])
            candidates.append(original_icon_title)

            seen_candidates: set[str] = set()
            fallback_result: dict[str, Any] | None = None
            snippet = None
            for candidate in candidates:
                normalized_candidate = normalize(candidate)
                if not normalized_candidate or normalized_candidate in seen_candidates:
                    continue
                seen_candidates.add(normalized_candidate)
                result = resolve_icon(candidate, page=page)
                fallback_result = fallback_result or result
                resolved_title = result.get("icon_title")
                if result.get("resolution") == "placeholder" or not resolved_title:
                    continue
                try:
                    snippet = self.catalog.get(str(resolved_title))
                except KeyError:
                    continue
                icon_title = resolved_title
                resolution = result["resolution"]
                source = result.get("source")
                fallback_result = result
                break

            if snippet is None:
                placeholder_result = fallback_result or {}
                placeholder_label = str(
                    element.get("label")
                    or placeholder_result.get("label_template")
                    or f"PLACEHOLDER: {query or original_icon_title}"
                )
                placeholder_element = dict(element)
                placeholder_element["placeholder_shape"] = placeholder_result.get(
                    "placeholder_shape",
                    "rounded-rectangle",
                )
                placeholder_element["label"] = placeholder_label
                record = self._render_shape(
                    root,
                    placeholder_element,
                    placed,
                    resolution="placeholder",
                    query=str(query or original_icon_title),
                )
                record["failed_icon_title"] = original_icon_title
                record["closest_official_icon"] = placeholder_result.get("closest_official_icon")
                return record

        x, y = self._resolve_position(element, placed)
        width, height, size_mode, role = self._resolve_library_dimensions(element, snippet, str(icon_title))
        if size_mode == "explicit-fit":
            explicit_box_width = float(element.get("w", element.get("width", width)))
            explicit_box_height = float(element.get("h", element.get("height", height)))
            x += max((explicit_box_width - width) / 2, 0.0)
            y += max((explicit_box_height - height) / 2, 0.0)

        if str(icon_title) in VCN_LIKE_TITLES:
            primary_cell_id = self._place_vcn_like_snippet(root, snippet, x, y, width, height, element)
        elif str(icon_title) in HORIZONTAL_SPECIAL_CONNECTOR_TITLES:
            primary_cell_id = self._place_horizontal_special_connector(root, snippet, x, y, width, height, element)
        else:
            primary_cell_id = self._place_generic_snippet(root, snippet, x, y, width, height, element)

        if element.get("external_label"):
            self._render_text(
                root,
                {
                    "id": f"{element['id']}__external_label" if element.get("id") else None,
                    "x": x,
                    "y": y + height + float(element.get("external_label_offset", 2)),
                    "w": width,
                    "h": float(element.get("external_label_height", 20)),
                    "text": str(element["external_label"]),
                },
                placed,
            )

        if element.get("id"):
            placed[str(element["id"])] = {
                "x": x,
                "y": y,
                "w": width,
                "h": height,
                "cell_id": primary_cell_id,
            }

        native_width = snippet.width
        native_height = snippet.height
        if role == "special-connector":
            native_width, native_height = self._special_connector_root_dimensions(snippet)

        return {
            "element_id": element.get("id"),
            "parent_element_id": element.get("parent"),
            "kind": "library",
            "role": role,
            "resolution": resolution,
            "icon_title": icon_title,
            "source": source if source != "explicit" else snippet.source,
            "query": query,
            "cell_id": primary_cell_id,
            "x": x,
            "y": y,
            "w": width,
            "h": height,
            "native_w": native_width,
            "native_h": native_height,
            "size_mode": size_mode,
            "service_name": element.get("service_name"),
            "skus": list(element.get("skus") or []),
            "mapping_resolution": element.get("mapping_resolution"),
        }

    def _instantiate_snippet(
        self,
        snippet: Snippet,
    ) -> tuple[dict[str, str], dict[str, ET.Element], list[ET.Element]]:
        id_map: dict[str, str] = {}
        originals = {cell.attrib["id"]: cell for cell in snippet.cells}
        clones: list[ET.Element] = []

        for cell in snippet.cells:
            id_map[cell.attrib["id"]] = self._new_id()

        for cell in snippet.cells:
            clone = deepcopy(cell)
            old_id = cell.attrib["id"]
            clone.set("id", id_map[old_id])

            parent = cell.attrib.get("parent")
            if parent in id_map:
                clone.set("parent", id_map[parent])
            elif parent:
                clone.set("parent", parent)

            for ref in ("source", "target"):
                target = cell.attrib.get(ref)
                if target in id_map:
                    clone.set(ref, id_map[target])

            clones.append(clone)

        return id_map, originals, clones

    def _scale_geometry(
        self,
        original: ET.Element,
        clone: ET.Element,
        scale_x: float,
        scale_y: float,
        translate_x: float = 0.0,
        translate_y: float = 0.0,
        is_root: bool = False,
    ) -> None:
        original_geo = original.find("mxGeometry")
        clone_geo = clone.find("mxGeometry")
        if original_geo is None or clone_geo is None:
            return

        def assign(attr: str, factor: float, translation: float) -> None:
            if attr in original_geo.attrib:
                value = parse_number(original_geo.attrib[attr]) * factor + translation
                clone_geo.set(attr, format_number(value))
            elif translation:
                clone_geo.set(attr, format_number(translation))

        assign("x", scale_x, translate_x if is_root else 0.0)
        assign("y", scale_y, translate_y if is_root else 0.0)
        if "width" in original_geo.attrib:
            clone_geo.set("width", format_number(parse_number(original_geo.attrib["width"]) * scale_x))
        if "height" in original_geo.attrib:
            clone_geo.set("height", format_number(parse_number(original_geo.attrib["height"]) * scale_y))

        for index, original_child in enumerate(list(original_geo)):
            if index >= len(clone_geo):
                break
            clone_child = clone_geo[index]
            if clone_child.tag == "mxPoint":
                if "x" in original_child.attrib:
                    value = parse_number(original_child.attrib["x"]) * scale_x + (translate_x if is_root else 0.0)
                    clone_child.set("x", format_number(value))
                if "y" in original_child.attrib:
                    value = parse_number(original_child.attrib["y"]) * scale_y + (translate_y if is_root else 0.0)
                    clone_child.set("y", format_number(value))
            elif clone_child.tag == "Array":
                for point_index, original_point in enumerate(list(original_child)):
                    if point_index >= len(clone_child):
                        break
                    clone_point = clone_child[point_index]
                    if "x" in original_point.attrib:
                        value = parse_number(original_point.attrib["x"]) * scale_x
                        clone_point.set("x", format_number(value))
                    if "y" in original_point.attrib:
                        value = parse_number(original_point.attrib["y"]) * scale_y
                        clone_point.set("y", format_number(value))

    def _apply_text_overrides(
        self,
        snippet: Snippet,
        originals: dict[str, ET.Element],
        clones_by_old_id: dict[str, ET.Element],
        element: dict[str, Any],
    ) -> bool:
        if element.get("text_values"):
            values = list(element["text_values"])
            for cell_id, value in zip(snippet.text_cell_ids, values):
                clones_by_old_id[cell_id].set("value", str(value))
            return True

        if element.get("value") is not None and snippet.text_cell_ids:
            clones_by_old_id[snippet.text_cell_ids[0]].set("value", str(element["value"]))
            return True

        if element.get("label") is not None and len(snippet.text_cell_ids) == 1 and element.get("label_mode") != "external":
            clones_by_old_id[snippet.text_cell_ids[0]].set("value", text_to_html(str(element["label"])))
            return True

        hide_internal_label = element.get("hide_internal_label")
        if hide_internal_label is None:
            hide_internal_label = bool(element.get("external_label")) and not bool(element.get("preserve_internal_label"))
        if hide_internal_label and snippet.text_cell_ids:
            for cell_id in snippet.text_cell_ids:
                clones_by_old_id[cell_id].set("value", "")
            return True

        return False

    def _append_clones(
        self,
        root: ET.Element,
        clones: list[ET.Element],
    ) -> None:
        for clone in clones:
            root.append(clone)

    def _primary_root_id(self, snippet: Snippet, id_map: dict[str, str]) -> str:
        return id_map[snippet.root_ids[0]]

    def _place_generic_snippet(
        self,
        root: ET.Element,
        snippet: Snippet,
        x: float,
        y: float,
        width: float,
        height: float,
        element: dict[str, Any],
    ) -> str:
        id_map, originals, clones = self._instantiate_snippet(snippet)
        clones_by_old_id = {original_id: clone for original_id, clone in zip(originals, clones)}
        scale_x = width / snippet.width
        scale_y = height / snippet.height

        for old_id, original in originals.items():
            self._scale_geometry(
                original,
                clones_by_old_id[old_id],
                scale_x,
                scale_y,
                translate_x=x,
                translate_y=y,
                is_root=old_id in snippet.root_ids,
            )

        self._apply_text_overrides(snippet, originals, clones_by_old_id, element)
        self._append_clones(root, clones)
        return self._primary_root_id(snippet, id_map)

    def _place_vcn_like_snippet(
        self,
        root: ET.Element,
        snippet: Snippet,
        x: float,
        y: float,
        width: float,
        height: float,
        element: dict[str, Any],
    ) -> str:
        id_map, originals, clones = self._instantiate_snippet(snippet)
        clones_by_old_id = {original_id: clone for original_id, clone in zip(originals, clones)}
        delta_width = width - snippet.width

        text_ids = set(snippet.text_cell_ids)

        for old_id, original in originals.items():
            clone = clones_by_old_id[old_id]
            original_geo = original.find("mxGeometry")
            clone_geo = clone.find("mxGeometry")
            if original_geo is None or clone_geo is None:
                continue

            if old_id in snippet.root_ids:
                clone_geo.set("x", format_number(x))
                clone_geo.set("y", format_number(y))
                clone_geo.set("width", format_number(width))
                clone_geo.set("height", format_number(height))
                continue

            old_x = parse_number(original_geo.attrib.get("x"))
            old_y = parse_number(original_geo.attrib.get("y"))
            old_width = parse_number(original_geo.attrib.get("width"))
            old_height = parse_number(original_geo.attrib.get("height"))

            if old_id in text_ids:
                clone_geo.set("x", format_number(old_x))
                clone_geo.set("y", format_number(old_y))
                clone_geo.set("width", format_number(width))
                clone_geo.set("height", format_number(max(height - old_y, old_height)))
            elif "shape=image" in original.attrib.get("style", ""):
                clone_geo.set("x", format_number(old_x + delta_width))
                clone_geo.set("y", format_number(old_y))
                clone_geo.set("width", format_number(old_width))
                clone_geo.set("height", format_number(old_height))
            else:
                self._scale_geometry(
                    original,
                    clone,
                    width / snippet.width,
                    height / snippet.height,
                    is_root=False,
                )

        self._apply_text_overrides(snippet, originals, clones_by_old_id, element)
        self._append_clones(root, clones)
        return self._primary_root_id(snippet, id_map)

    def _place_horizontal_special_connector(
        self,
        root: ET.Element,
        snippet: Snippet,
        x: float,
        y: float,
        width: float,
        height: float,
        element: dict[str, Any],
    ) -> str:
        image_style, image_native_width, image_native_height, default_text_value, default_text_style = (
            self._special_connector_parts(snippet)
        )

        group_id = self._new_id()
        group = ET.Element(
            "mxCell",
            {
                "id": group_id,
                "value": "",
                "style": "group",
                "vertex": "1",
                "connectable": "0",
                "parent": "1",
            },
        )
        ET.SubElement(
            group,
            "mxGeometry",
            {
                "x": format_number(x),
                "y": format_number(y),
                "width": format_number(width),
                "height": format_number(height),
                "as": "geometry",
            },
        )
        root.append(group)

        hide_internal_label = element.get("hide_internal_label")
        if hide_internal_label is None:
            hide_internal_label = bool(element.get("external_label")) and not bool(element.get("preserve_internal_label"))

        internal_label_value = None
        if not hide_internal_label:
            if element.get("label") is not None:
                internal_label_value = text_to_html(str(element["label"]))
            elif default_text_value:
                internal_label_value = default_text_value

        padding = max(min(height * 0.15, 10.0), 4.0)
        text_gap = max(min(height * 0.18, 8.0), 4.0)
        if internal_label_value:
            icon_width, icon_height = fit_dimensions_within_box(
                image_native_width,
                image_native_height,
                max(width * 0.42, 32.0),
                max(height - (padding * 2), 12.0),
            )
            icon_x = padding
            icon_y = (height - icon_height) / 2
            text_x = icon_x + icon_width + text_gap
            text_width = max(width - text_x - padding, 30.0)
        else:
            icon_width, icon_height = fit_dimensions_within_box(
                image_native_width,
                image_native_height,
                max(width - (padding * 2), 12.0),
                max(height - (padding * 2), 12.0),
            )
            icon_x = (width - icon_width) / 2
            icon_y = (height - icon_height) / 2
            text_x = padding
            text_width = max(width - (padding * 2), 0.0)

        image_id = self._new_id()
        image_cell = ET.Element(
            "mxCell",
            {
                "id": image_id,
                "value": "",
                "style": append_style(image_style, element.get("special_connector_icon_style")),
                "vertex": "1",
                "parent": group_id,
            },
        )
        ET.SubElement(
            image_cell,
            "mxGeometry",
            {
                "x": format_number(icon_x),
                "y": format_number(icon_y),
                "width": format_number(icon_width),
                "height": format_number(icon_height),
                "as": "geometry",
            },
        )
        root.append(image_cell)

        if internal_label_value and text_width > 0:
            label_id = self._new_id()
            label_cell = ET.Element(
                "mxCell",
                {
                    "id": label_id,
                    "value": internal_label_value,
                    "style": append_style(
                        default_text_style or TEXT_STYLE,
                        {
                            "fillColor": "none",
                            "strokeColor": "none",
                            "rounded": "0",
                            "align": "left",
                            "verticalAlign": "middle",
                            "fontFamily": "Oracle Sans",
                        },
                    ),
                    "vertex": "1",
                    "parent": group_id,
                },
            )
            ET.SubElement(
                label_cell,
                "mxGeometry",
                {
                    "x": format_number(text_x),
                    "y": "0",
                    "width": format_number(text_width),
                    "height": format_number(height),
                    "as": "geometry",
                },
            )
            root.append(label_cell)

        return group_id

    def _render_edge(
        self,
        root: ET.Element,
        element: dict[str, Any],
        page_type: str,
        placed: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        source_ref = str(element["source"])
        target_ref = str(element["target"])
        if source_ref not in placed:
            raise KeyError(f"Edge source '{source_ref}' is not a placed element.")
        if target_ref not in placed:
            raise KeyError(f"Edge target '{target_ref}' is not a placed element.")

        connector_key = self._normalize_connector_key(element.get("connector"), page_type)
        style = CONNECTOR_STYLES[connector_key]

        source_anchor = element.get("source_anchor")
        target_anchor = element.get("target_anchor")
        additions: dict[str, str] = {}

        if source_anchor in ANCHOR_POINTS:
            additions.update(
                {
                    "exitX": ANCHOR_POINTS[str(source_anchor)][0],
                    "exitY": ANCHOR_POINTS[str(source_anchor)][1],
                    "exitDx": "0",
                    "exitDy": "0",
                }
            )
        if target_anchor in ANCHOR_POINTS:
            additions.update(
                {
                    "entryX": ANCHOR_POINTS[str(target_anchor)][0],
                    "entryY": ANCHOR_POINTS[str(target_anchor)][1],
                    "entryDx": "0",
                    "entryDy": "0",
                }
            )

        style = append_style(style, additions)
        style = append_style(style, element.get("style"))

        cell_id = self._new_id()
        edge = ET.Element(
            "mxCell",
            {
                "id": cell_id,
                "value": text_to_html(str(element.get("label", ""))),
                "style": style,
                "edge": "1",
                "parent": "1",
                "source": placed[source_ref]["cell_id"],
                "target": placed[target_ref]["cell_id"],
            },
        )

        geometry = ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        normalized_waypoints: list[dict[str, float]] = []
        if element.get("waypoints"):
            raw_waypoints: list[tuple[float, float]] = []
            for waypoint in element["waypoints"]:
                if isinstance(waypoint, dict):
                    point_x = float(waypoint["x"])
                    point_y = float(waypoint["y"])
                else:
                    point_x = float(waypoint[0])
                    point_y = float(waypoint[1])
                raw_waypoints.append((point_x, point_y))

            normalized_points = normalize_connector_points(
                anchor_point(placed[source_ref], source_anchor),
                anchor_point(placed[target_ref], target_anchor),
                raw_waypoints,
            )
            normalized_waypoints = [
                {"x": point_x, "y": point_y}
                for point_x, point_y in normalized_points[1:-1]
            ]
            if normalized_waypoints:
                array = ET.SubElement(geometry, "Array", {"as": "points"})
                for waypoint in normalized_waypoints:
                    ET.SubElement(
                        array,
                        "mxPoint",
                        {"x": format_number(waypoint["x"]), "y": format_number(waypoint["y"])},
                    )

        root.append(edge)

        return {
            "element_id": element.get("id"),
            "kind": "edge",
            "role": "edge",
            "resolution": connector_key,
            "icon_title": None,
            "source": None,
            "query": None,
            "cell_id": cell_id,
            "source_element_id": source_ref,
            "target_element_id": target_ref,
            "source_anchor": source_anchor,
            "target_anchor": target_anchor,
            "waypoints": normalized_waypoints,
            "label": element.get("label"),
        }

    def _normalize_connector_key(self, connector: Any, page_type: str) -> str:
        if connector is None:
            return "physical" if page_type == "physical" else "logical-dataflow"
        normalized = normalize(str(connector))
        key = CONNECTOR_KEY_ALIASES.get(normalized)
        if key is None:
            raise KeyError(f"Unsupported connector style: {connector}")
        return key


def render_spec_to_file(spec_path: Path, output_path: Path, report_path: Path | None = None) -> list[dict[str, Any]]:
    spec = json.loads(spec_path.read_text())
    skill_dir = Path(__file__).resolve().parents[1]
    renderer = DrawioRenderer(SnippetCatalog(skill_dir))
    mxfile, report = renderer.render_spec(spec)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(ET.tostring(mxfile, encoding="unicode"))

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")

    return report


def read_drawio_page_models(drawio_path: Path) -> list[tuple[str, ET.Element]]:
    mxfile = ET.fromstring(drawio_path.read_text())
    pages: list[tuple[str, ET.Element]] = []
    for diagram in mxfile.findall("diagram"):
        page_name = diagram.attrib.get("name", "")
        model = ET.fromstring(decode_diagram(diagram.text or ""))
        pages.append((page_name, model))
    return pages


def validate_drawio_file(drawio_path: Path) -> dict[str, Any]:
    issues: list[str] = []
    pages: list[dict[str, Any]] = []

    for page_name, model in read_drawio_page_models(drawio_path):
        graph_root = model.find("root")
        if graph_root is None:
            issues.append(f"Page '{page_name}' is missing <root>.")
            continue

        cells = flatten_graph_cells(graph_root)
        ids = [cell.attrib.get("id", "") for cell in cells]
        id_set = set(ids)

        if "0" not in id_set or "1" not in id_set:
            issues.append(f"Page '{page_name}' is missing base ids 0/1.")

        if len(ids) != len(id_set):
            issues.append(f"Page '{page_name}' contains duplicate cell ids.")

        for cell in cells:
            cell_id = cell.attrib.get("id", "")
            parent = cell.attrib.get("parent")
            if parent and parent not in id_set and parent != "0":
                issues.append(f"Page '{page_name}' cell '{cell_id}' has unknown parent '{parent}'.")
            for ref in ("source", "target"):
                target = cell.attrib.get(ref)
                if target and target not in id_set:
                    issues.append(f"Page '{page_name}' cell '{cell_id}' has unknown {ref} '{target}'.")

        pages.append({"name": page_name, "cell_count": len(cells)})

    return {"page_count": len(pages), "pages": pages, "issues": issues}


def record_identifier(record: dict[str, Any]) -> str:
    return str(record.get("element_id") or record.get("cell_id") or record.get("kind") or "record")


def record_bounds(record: dict[str, Any]) -> tuple[float, float, float, float] | None:
    if any(record.get(key) is None for key in ("x", "y", "w", "h")):
        return None
    return (
        float(record["x"]),
        float(record["y"]),
        float(record["w"]),
        float(record["h"]),
    )


def is_anchor_record(record: dict[str, Any]) -> bool:
    identifier = str(record.get("element_id") or "")
    bounds = record_bounds(record)
    if identifier.endswith("-anchor"):
        return True
    if bounds is None:
        return False
    _, _, width, height = bounds
    return max(width, height) <= 6.0


def is_container_record(record: dict[str, Any]) -> bool:
    if record.get("kind") != "shape":
        return False
    identifier = str(record.get("element_id") or "")
    bounds = record_bounds(record)
    if identifier.endswith("-box") or "container" in identifier:
        return True
    if bounds is None:
        return False
    _, _, width, height = bounds
    return width >= 180.0 or height >= 140.0


def anchor_point(record: dict[str, Any], anchor: str | None) -> tuple[float, float]:
    bounds = record_bounds(record)
    if bounds is None:
        return (0.0, 0.0)
    x, y, width, height = bounds
    if anchor == "left":
        return (x, y + height / 2)
    if anchor == "right":
        return (x + width, y + height / 2)
    if anchor == "top":
        return (x + width / 2, y)
    if anchor == "bottom":
        return (x + width / 2, y + height)
    return (x + width / 2, y + height / 2)


def segment_orientation(start: tuple[float, float], end: tuple[float, float]) -> str:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    if abs(delta_x) <= EDGE_SEGMENT_TOLERANCE and abs(delta_y) <= EDGE_SEGMENT_TOLERANCE:
        return "point"
    if abs(delta_x) <= EDGE_SEGMENT_TOLERANCE:
        return "vertical"
    if abs(delta_y) <= EDGE_SEGMENT_TOLERANCE:
        return "horizontal"
    return "diagonal"


def overlap_length(first_start: float, first_end: float, second_start: float, second_end: float) -> float:
    left = max(min(first_start, first_end), min(second_start, second_end))
    right = min(max(first_start, first_end), max(second_start, second_end))
    return max(0.0, right - left)


def rectangles_overlap(
    first: tuple[float, float, float, float] | None,
    second: tuple[float, float, float, float] | None,
    padding: float = 0.0,
) -> bool:
    if first is None or second is None:
        return False

    first_left, first_top, first_width, first_height = first
    second_left, second_top, second_width, second_height = second
    first_right = first_left + first_width
    first_bottom = first_top + first_height
    second_right = second_left + second_width
    second_bottom = second_top + second_height

    return (
        max(first_left + padding, second_left + padding) < min(first_right - padding, second_right - padding)
        and max(first_top + padding, second_top + padding) < min(first_bottom - padding, second_bottom - padding)
    )


def point_within_rect(
    point: tuple[float, float],
    rect: tuple[float, float, float, float] | None,
    tolerance: float = 0.0,
) -> bool:
    if rect is None:
        return False

    left, top, width, height = rect
    right = left + width
    bottom = top + height
    return (
        left - tolerance <= point[0] <= right + tolerance
        and top - tolerance <= point[1] <= bottom + tolerance
    )


def rect_within_rect(
    inner: tuple[float, float, float, float] | None,
    outer: tuple[float, float, float, float] | None,
    tolerance: float = 0.0,
) -> bool:
    if inner is None or outer is None:
        return False

    inner_left, inner_top, inner_width, inner_height = inner
    outer_left, outer_top, outer_width, outer_height = outer
    inner_right = inner_left + inner_width
    inner_bottom = inner_top + inner_height
    outer_right = outer_left + outer_width
    outer_bottom = outer_top + outer_height

    return (
        inner_left >= outer_left - tolerance
        and inner_top >= outer_top - tolerance
        and inner_right <= outer_right + tolerance
        and inner_bottom <= outer_bottom + tolerance
    )


def segment_intersects_rect(
    start: tuple[float, float],
    end: tuple[float, float],
    rect: tuple[float, float, float, float] | None,
    padding: float = 0.0,
) -> bool:
    if rect is None:
        return False

    left, top, width, height = rect
    right = left + width
    bottom = top + height
    orientation = segment_orientation(start, end)

    if orientation == "horizontal":
        seg_y = start[1]
        seg_left, seg_right = sorted((start[0], end[0]))
        return top + padding < seg_y < bottom - padding and seg_left < right - padding and seg_right > left + padding

    if orientation == "vertical":
        seg_x = start[0]
        seg_top, seg_bottom = sorted((start[1], end[1]))
        return left + padding < seg_x < right - padding and seg_top < bottom - padding and seg_bottom > top + padding

    return False


def segment_runs_along_rect_border(
    start: tuple[float, float],
    end: tuple[float, float],
    rect: tuple[float, float, float, float] | None,
    tolerance: float = EDGE_BORDER_OVERLAP_TOLERANCE,
    min_overlap: float = EDGE_BORDER_OVERLAP_MIN_LENGTH,
) -> bool:
    if rect is None:
        return False

    left, top, width, height = rect
    right = left + width
    bottom = top + height
    orientation = segment_orientation(start, end)

    if orientation == "horizontal":
        y = start[1]
        if abs(y - top) > tolerance and abs(y - bottom) > tolerance:
            return False
        overlap = overlap_length(start[0], end[0], left, right)
        return overlap > min_overlap

    if orientation == "vertical":
        x = start[0]
        if abs(x - left) > tolerance and abs(x - right) > tolerance:
            return False
        overlap = overlap_length(start[1], end[1], top, bottom)
        return overlap > min_overlap

    return False


def build_edge_points(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> list[tuple[float, float]] | None:
    source = nodes_by_id.get(str(edge.get("source_element_id")))
    target = nodes_by_id.get(str(edge.get("target_element_id")))
    if source is None or target is None:
        return None

    start = anchor_point(source, edge.get("source_anchor"))
    end = anchor_point(target, edge.get("target_anchor"))
    points: list[tuple[float, float]] = [start]

    for waypoint in edge.get("waypoints", []):
        if isinstance(waypoint, dict):
            points.append((float(waypoint["x"]), float(waypoint["y"])))
        else:
            points.append((float(waypoint[0]), float(waypoint[1])))

    if len(points) == 1:
        if abs(start[0] - end[0]) <= EDGE_SEGMENT_TOLERANCE or abs(start[1] - end[1]) <= EDGE_SEGMENT_TOLERANCE:
            points.append(end)
        elif edge.get("source_anchor") in {"left", "right"}:
            midpoint_x = (start[0] + end[0]) / 2
            points.extend([(midpoint_x, start[1]), (midpoint_x, end[1]), end])
        else:
            midpoint_y = (start[1] + end[1]) / 2
            points.extend([(start[0], midpoint_y), (end[0], midpoint_y), end])
    else:
        points.append(end)
    return points


def review_render_report(report: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    rows_by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in report:
        rows_by_page[str(row.get("page", ""))].append(row)

    for page_name, rows in rows_by_page.items():
        page_issues: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()

        def add_issue(code: str, message: str, primary: str = "", secondary: str = "", **extra: Any) -> None:
            key = (page_name, code, primary, secondary)
            if key in seen:
                return
            seen.add(key)
            issue = {"page": page_name, "code": code, "message": message}
            issue.update({name: value for name, value in extra.items() if value is not None})
            page_issues.append(issue)

        nodes_by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.get("kind") not in {"library", "shape", "text"}:
                continue
            identifier = record_identifier(row)
            nodes_by_id[identifier] = row
            if row.get("element_id") is not None:
                nodes_by_id[str(row["element_id"])] = row

        region_records = [
            row
            for row in rows
            if row.get("kind") == "library"
            and row.get("role") == "grouping"
            and "Region" in str(row.get("icon_title") or "")
        ]

        for row in rows:
            if row.get("kind") != "library" or row.get("role") != "icon" or is_anchor_record(row):
                continue
            if row.get("parent_element_id"):
                continue
            icon_title = str(row.get("icon_title") or "")
            if icon_title in UNPARENTED_LIBRARY_ICON_ALLOWLIST:
                continue
            if not region_records:
                continue

            bounds = record_bounds(row)
            if bounds is None:
                continue
            center = (bounds[0] + (bounds[2] / 2), bounds[1] + (bounds[3] / 2))
            if any(point_within_rect(center, record_bounds(region), tolerance=PARENT_CENTER_TOLERANCE) for region in region_records):
                continue

            element_ref = record_identifier(row)
            add_issue(
                "oci-icon-outside-region",
                f"{element_ref} is an OCI service icon but sits outside every OCI Region boundary.",
                primary=element_ref,
                element_id=row.get("element_id"),
            )

        for row in rows:
            if row.get("role") != "placeholder" or is_anchor_record(row):
                continue

            placeholder_query = str(row.get("query") or "").strip()
            if not placeholder_query:
                placeholder_label = str(row.get("label") or "").replace("\n", " ").strip()
                if placeholder_label.upper().startswith("PLACEHOLDER:"):
                    placeholder_query = re.sub(r"(?i)^PLACEHOLDER:\s*", "", placeholder_label).strip()

            if not placeholder_query:
                continue

            resolved = resolve_icon(placeholder_query, "physical")
            if resolved.get("resolution") not in {"direct", "alias"}:
                continue

            element_ref = record_identifier(row)
            add_issue(
                "placeholder-despite-direct-icon",
                (
                    f"{element_ref} uses a placeholder even though {placeholder_query} resolves to the "
                    f"official OCI icon {resolved.get('icon_title')}."
                ),
                primary=element_ref,
                element_id=row.get("element_id"),
                resolved_icon_title=resolved.get("icon_title"),
            )

        icon_records = [
            row
            for row in rows
            if row.get("kind") == "library" and row.get("role") == "icon" and not is_anchor_record(row)
        ]

        icon_max_dimensions = sorted(
            max(float(row["w"]), float(row["h"]))
            for row in icon_records
            if row.get("w") is not None and row.get("h") is not None and row.get("size_mode") != "explicit"
        )
        if len(icon_max_dimensions) >= 4:
            midpoint = len(icon_max_dimensions) // 2
            if len(icon_max_dimensions) % 2:
                median_max_dimension = icon_max_dimensions[midpoint]
            else:
                median_max_dimension = (icon_max_dimensions[midpoint - 1] + icon_max_dimensions[midpoint]) / 2

            for row in icon_records:
                if row.get("size_mode") in {"explicit", "explicit-fit"}:
                    continue
                max_dimension = max(float(row["w"]), float(row["h"]))
                if max_dimension < median_max_dimension * 0.6 or max_dimension > median_max_dimension * 1.5:
                    element_ref = record_identifier(row)
                    add_issue(
                        "icon-size-outlier",
                        f"{element_ref} is sized far outside the page's normal service-icon range.",
                        primary=element_ref,
                        element_id=row.get("element_id"),
                    )

        for row in icon_records:
            native_width = float(row.get("native_w") or 0.0)
            native_height = float(row.get("native_h") or 0.0)
            if native_width <= 0 or native_height <= 0:
                continue
            rendered_aspect = float(row["w"]) / float(row["h"]) if float(row["h"]) else 0.0
            native_aspect = native_width / native_height if native_height else 0.0
            if native_aspect <= 0 or rendered_aspect <= 0:
                continue
            distortion = abs(rendered_aspect - native_aspect) / native_aspect
            if distortion > 0.75:
                element_ref = record_identifier(row)
                add_issue(
                    "icon-aspect-distorted",
                    f"{element_ref} is stretched away from its native OCI icon aspect ratio.",
                    primary=element_ref,
                    element_id=row.get("element_id"),
                )

        parented_layout_nodes = [
            row
            for row in rows
            if row.get("kind") in {"library", "shape"}
            and not is_anchor_record(row)
            and row.get("parent_element_id")
        ]
        for row in parented_layout_nodes:
            parent = nodes_by_id.get(str(row.get("parent_element_id")))
            if parent is None:
                continue

            child_bounds = record_bounds(row)
            parent_bounds = record_bounds(parent)
            if child_bounds is None or parent_bounds is None:
                continue

            child_x, child_y, child_width, child_height = child_bounds
            child_center = (child_x + child_width / 2, child_y + child_height / 2)
            child_ref = record_identifier(row)
            parent_ref = record_identifier(parent)

            if not point_within_rect(child_center, parent_bounds, tolerance=PARENT_CENTER_TOLERANCE):
                add_issue(
                    "child-center-outside-parent",
                    f"{child_ref} is not centered within {parent_ref}; its center point falls outside the parent boundary.",
                    primary=child_ref,
                    secondary=parent_ref,
                    element_id=row.get("element_id"),
                    parent_element_id=row.get("parent_element_id"),
                )

            if not rect_within_rect(child_bounds, parent_bounds, tolerance=PARENT_BOUNDARY_TOLERANCE):
                add_issue(
                    "child-outside-parent-boundary",
                    f"{child_ref} extends outside {parent_ref}.",
                    primary=child_ref,
                    secondary=parent_ref,
                    element_id=row.get("element_id"),
                    parent_element_id=row.get("parent_element_id"),
                )

        layout_nodes = [
            row
            for row in rows
            if row.get("role") in {"icon", "placeholder", "special-connector"}
            and not is_anchor_record(row)
            and not is_container_record(row)
        ]
        for first, second in combinations(layout_nodes, 2):
            if rectangles_overlap(record_bounds(first), record_bounds(second), padding=NODE_OVERLAP_PADDING):
                first_ref = record_identifier(first)
                second_ref = record_identifier(second)
                add_issue(
                    "node-overlap",
                    f"{first_ref} overlaps {second_ref}.",
                    primary=first_ref,
                    secondary=second_ref,
                    element_id=first.get("element_id"),
                    peer_element_id=second.get("element_id"),
                )

        edge_obstacles = [
            row
            for row in rows
            if row.get("role") in {"icon", "placeholder", "special-connector", "text"}
            and not is_anchor_record(row)
            and not is_container_record(row)
        ]
        border_containers = [
            row
            for row in rows
            if not is_anchor_record(row)
            and (
                (
                    row.get("kind") == "library"
                    and row.get("role") == "grouping"
                    and "Region" not in str(row.get("icon_title") or "")
                )
                or is_container_record(row)
            )
        ]
        edge_segments: list[dict[str, Any]] = []
        edges = [row for row in rows if row.get("kind") == "edge"]

        for edge in edges:
            edge_ref = record_identifier(edge)
            source = nodes_by_id.get(str(edge.get("source_element_id")))
            target = nodes_by_id.get(str(edge.get("target_element_id")))
            if source is None or target is None:
                continue

            points = build_edge_points(edge, nodes_by_id)
            if not points or len(points) < 2:
                continue

            segments: list[tuple[tuple[float, float], tuple[float, float], str]] = []
            for start, end in zip(points, points[1:]):
                orientation = segment_orientation(start, end)
                if orientation == "point":
                    continue
                segments.append((start, end, orientation))
                if orientation == "diagonal":
                    add_issue(
                        "edge-diagonal-segment",
                        f"{edge_ref} contains a diagonal segment instead of an orthogonal route.",
                        primary=edge_ref,
                        element_id=edge.get("element_id"),
                    )

            bend_count = sum(
                1
                for first, second in zip(segments, segments[1:])
                if first[2] != second[2]
            )
            if bend_count > MAX_EDGE_BENDS:
                add_issue(
                    "edge-too-many-bends",
                    f"{edge_ref} uses {bend_count} bends, which is more than the allowed {MAX_EDGE_BENDS}.",
                    primary=edge_ref,
                    element_id=edge.get("element_id"),
                )

            if bend_count > 0:
                source_anchor = str(edge.get("source_anchor") or "").lower()
                target_anchor = str(edge.get("target_anchor") or "").lower()
                source_point = anchor_point(source, edge.get("source_anchor"))
                target_point = anchor_point(target, edge.get("target_anchor"))
                direct_orientation = None
                if (
                    abs(source_point[0] - target_point[0]) <= EDGE_SEGMENT_TOLERANCE
                    and (source_anchor, target_anchor) in {("bottom", "top"), ("top", "bottom")}
                ):
                    direct_orientation = "vertical"
                elif (
                    abs(source_point[1] - target_point[1]) <= EDGE_SEGMENT_TOLERANCE
                    and (source_anchor, target_anchor) in {("right", "left"), ("left", "right")}
                ):
                    direct_orientation = "horizontal"

                if direct_orientation is not None:
                    direct_route_blocked = False
                    for obstacle in edge_obstacles:
                        obstacle_ref = record_identifier(obstacle)
                        if obstacle_ref in {record_identifier(source), record_identifier(target)}:
                            continue
                        if segment_intersects_rect(
                            source_point,
                            target_point,
                            record_bounds(obstacle),
                            padding=NODE_OVERLAP_PADDING,
                        ):
                            direct_route_blocked = True
                            break

                    if not direct_route_blocked:
                        add_issue(
                            "edge-avoidable-elbow",
                            f"{edge_ref} uses a bent route even though a straight {direct_orientation} connector is available.",
                            primary=edge_ref,
                            element_id=edge.get("element_id"),
                        )

            for obstacle in edge_obstacles:
                obstacle_ref = record_identifier(obstacle)
                if obstacle_ref in {record_identifier(source), record_identifier(target)}:
                    continue

                if any(
                    segment_intersects_rect(start, end, record_bounds(obstacle), padding=NODE_OVERLAP_PADDING)
                    for start, end, orientation in segments
                    if orientation in {"horizontal", "vertical"}
                ):
                    add_issue(
                        "edge-through-node",
                        f"{edge_ref} crosses through {obstacle_ref}.",
                        primary=edge_ref,
                        secondary=obstacle_ref,
                        element_id=edge.get("element_id"),
                        obstacle_id=obstacle.get("element_id"),
                    )
                    break

            for container in border_containers:
                container_ref = record_identifier(container)
                if container_ref in {record_identifier(source), record_identifier(target)}:
                    continue

                if any(
                    segment_runs_along_rect_border(start, end, record_bounds(container))
                    for start, end, orientation in segments
                    if orientation in {"horizontal", "vertical"}
                ):
                    add_issue(
                        "edge-on-container-border",
                        f"{edge_ref} runs along the border of {container_ref}.",
                        primary=edge_ref,
                        secondary=container_ref,
                        element_id=edge.get("element_id"),
                        container_id=container.get("element_id"),
                    )
                    break

            for start, end, orientation in segments:
                if orientation not in {"horizontal", "vertical"}:
                    continue
                edge_segments.append(
                    {
                        "edge_ref": edge_ref,
                        "element_id": edge.get("element_id"),
                        "start": start,
                        "end": end,
                        "orientation": orientation,
                    }
                )

        lane_groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for segment in edge_segments:
            if segment["orientation"] == "horizontal":
                lane_coordinate = segment["start"][1]
            else:
                lane_coordinate = segment["start"][0]
            lane_key = (
                str(segment["orientation"]),
                int(round(lane_coordinate / EDGE_LANE_OVERLAP_TOLERANCE)),
            )
            lane_groups[lane_key].append(segment)

        for group_segments in lane_groups.values():
            if len(group_segments) < 2:
                continue

            adjacency: dict[str, set[str]] = defaultdict(set)
            element_ids: dict[str, Any] = {}
            for first, second in combinations(group_segments, 2):
                if first["edge_ref"] == second["edge_ref"]:
                    continue

                if first["orientation"] == "horizontal":
                    if abs(first["start"][1] - second["start"][1]) > EDGE_LANE_OVERLAP_TOLERANCE:
                        continue
                    overlap = overlap_length(first["start"][0], first["end"][0], second["start"][0], second["end"][0])
                else:
                    if abs(first["start"][0] - second["start"][0]) > EDGE_LANE_OVERLAP_TOLERANCE:
                        continue
                    overlap = overlap_length(first["start"][1], first["end"][1], second["start"][1], second["end"][1])

                if overlap <= EDGE_LANE_OVERLAP_MIN_LENGTH:
                    continue

                first_ref = str(first["edge_ref"])
                second_ref = str(second["edge_ref"])
                adjacency[first_ref].add(second_ref)
                adjacency[second_ref].add(first_ref)
                element_ids.setdefault(first_ref, first["element_id"])
                element_ids.setdefault(second_ref, second["element_id"])

            visited_edges: set[str] = set()
            for edge_ref in sorted(adjacency):
                if edge_ref in visited_edges:
                    continue
                stack = [edge_ref]
                component: set[str] = set()
                while stack:
                    current = stack.pop()
                    if current in component:
                        continue
                    component.add(current)
                    stack.extend(sorted(adjacency[current] - component))
                visited_edges.update(component)
                if len(component) < 2:
                    continue
                members = sorted(component)
                if len(members) == 2:
                    message = f"{members[0]} shares a routing lane with {members[1]}."
                    secondary = members[1]
                else:
                    message = f"{', '.join(members[:-1])}, and {members[-1]} share a routing lane."
                    secondary = "|".join(members[1:])
                add_issue(
                    "edge-lane-overlap",
                    message,
                    primary=members[0],
                    secondary=secondary,
                    element_id=element_ids.get(members[0]),
                )

        issues.extend(page_issues)
        pages.append(
            {
                "name": page_name,
                "issue_count": len(page_issues),
                "edge_count": len(edges),
                "icon_count": len(icon_records),
            }
        )

    return {"page_count": len(pages), "pages": pages, "issues": issues}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="Path to the JSON diagram spec.")
    parser.add_argument("--output", type=Path, required=True, help="Output .drawio file path.")
    parser.add_argument("--report-out", type=Path, help="Optional JSON report path.")
    parser.add_argument("--quality-out", type=Path, help="Optional JSON quality review path.")
    parser.add_argument(
        "--fail-on-quality",
        action="store_true",
        help="Exit non-zero when geometry quality issues are detected.",
    )
    args = parser.parse_args()

    report = render_spec_to_file(args.spec, args.output, args.report_out)
    physical = sum(1 for row in report if row["kind"] == "library" and row["resolution"] in {"direct", "alias", "closest"})
    placeholders = sum(1 for row in report if row.get("resolution") == "placeholder")
    anchors = sum(1 for row in report if row.get("resolution") == "anchor")
    quality = review_render_report(report) if args.quality_out or args.fail_on_quality else None
    print(f"Rendered {len({row['page'] for row in report})} page(s) to {args.output}")
    print(f"Official OCI elements: {physical}")
    print(f"Placeholders: {placeholders}")
    if anchors:
        print(f"Routing anchors: {anchors}")
    if args.report_out:
        print(f"Report: {args.report_out}")
    if quality is not None:
        if args.quality_out:
            args.quality_out.parent.mkdir(parents=True, exist_ok=True)
            args.quality_out.write_text(json.dumps(quality, indent=2) + "\n")
            print(f"Quality report: {args.quality_out}")
        print(f"Quality issues: {len(quality['issues'])}")
        if args.fail_on_quality and quality["issues"]:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
