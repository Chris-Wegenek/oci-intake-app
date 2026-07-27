#!/usr/bin/env python3
"""Review OCI architecture preview images for visual regressions."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import struct
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SUPPORTED_COLOR_TYPES = {2, 6}
ICON_FOREGROUND_THRESHOLD = 0.012
ICON_VISIBILITY_WARNING_THRESHOLD = 0.02
PAGE_FOREGROUND_WARNING_THRESHOLD = 0.0075
TEXT_CARD_RATIO_THRESHOLD = 1.5
TEXT_EDGE_PADDING = 3.0
BOUNDARY_LANE_PADDING = 3.0
MIN_BOUNDARY_LANE_OVERLAP = 32.0

HTML_BREAK_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
TOKEN_RE = re.compile(r"[a-z0-9]+")


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def quantize_channel(value: int, step: int = 24) -> int:
    return int(clamp(round(value / step) * step, 0, 255))


def quantize_rgb(pixel: tuple[int, int, int, int]) -> tuple[int, int, int]:
    return (
        quantize_channel(pixel[0]),
        quantize_channel(pixel[1]),
        quantize_channel(pixel[2]),
    )


def color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.sqrt(
        ((a[0] - b[0]) ** 2) +
        ((a[1] - b[1]) ** 2) +
        ((a[2] - b[2]) ** 2)
    )


def luminance(pixel: tuple[int, int, int, int]) -> float:
    return (0.2126 * pixel[0]) + (0.7152 * pixel[1]) + (0.0722 * pixel[2])


def saturation(pixel: tuple[int, int, int, int]) -> int:
    return max(pixel[0], pixel[1], pixel[2]) - min(pixel[0], pixel[1], pixel[2])


def plain_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = HTML_BREAK_RE.sub("\n", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = text.replace("\\n", "\n")
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def normalized_text(value: Any) -> str:
    return " ".join(tokens(value))


def tokens(value: Any) -> list[str]:
    return TOKEN_RE.findall(plain_text(value).lower())


def token_set(value: Any) -> set[str]:
    return set(tokens(value))


def bbox_area(bbox: dict[str, float]) -> float:
    return max(float(bbox.get("w", 0.0)), 0.0) * max(float(bbox.get("h", 0.0)), 0.0)


def bbox_center(bbox: dict[str, float]) -> tuple[float, float]:
    return (
        float(bbox.get("x", 0.0)) + (float(bbox.get("w", 0.0)) / 2),
        float(bbox.get("y", 0.0)) + (float(bbox.get("h", 0.0)) / 2),
    )


def bbox_contains_point(bbox: dict[str, float], point: tuple[float, float], padding: float = 0.0) -> bool:
    x, y = point
    return (
        float(bbox.get("x", 0.0)) - padding <= x <= float(bbox.get("x", 0.0)) + float(bbox.get("w", 0.0)) + padding
        and float(bbox.get("y", 0.0)) - padding <= y <= float(bbox.get("y", 0.0)) + float(bbox.get("h", 0.0)) + padding
    )


def bbox_contains_bbox(container: dict[str, float], child: dict[str, float], padding: float = 0.0) -> bool:
    return (
        float(container.get("x", 0.0)) - padding <= float(child.get("x", 0.0))
        and float(container.get("y", 0.0)) - padding <= float(child.get("y", 0.0))
        and float(child.get("x", 0.0)) + float(child.get("w", 0.0)) <= float(container.get("x", 0.0)) + float(container.get("w", 0.0)) + padding
        and float(child.get("y", 0.0)) + float(child.get("h", 0.0)) <= float(container.get("y", 0.0)) + float(container.get("h", 0.0)) + padding
    )


def bbox_intersection_area(first: dict[str, float], second: dict[str, float]) -> float:
    left = max(float(first.get("x", 0.0)), float(second.get("x", 0.0)))
    right = min(
        float(first.get("x", 0.0)) + float(first.get("w", 0.0)),
        float(second.get("x", 0.0)) + float(second.get("w", 0.0)),
    )
    top = max(float(first.get("y", 0.0)), float(second.get("y", 0.0)))
    bottom = min(
        float(first.get("y", 0.0)) + float(first.get("h", 0.0)),
        float(second.get("y", 0.0)) + float(second.get("h", 0.0)),
    )
    return max(right - left, 0.0) * max(bottom - top, 0.0)


def bbox_gap(first: dict[str, float], second: dict[str, float]) -> float:
    first_right = float(first.get("x", 0.0)) + float(first.get("w", 0.0))
    second_right = float(second.get("x", 0.0)) + float(second.get("w", 0.0))
    first_bottom = float(first.get("y", 0.0)) + float(first.get("h", 0.0))
    second_bottom = float(second.get("y", 0.0)) + float(second.get("h", 0.0))
    dx = max(float(second.get("x", 0.0)) - first_right, float(first.get("x", 0.0)) - second_right, 0.0)
    dy = max(float(second.get("y", 0.0)) - first_bottom, float(first.get("y", 0.0)) - second_bottom, 0.0)
    return math.hypot(dx, dy)


class SimplePNG:
    def __init__(self, width: int, height: int, channels: int, rows: list[bytearray]) -> None:
        self.width = width
        self.height = height
        self.channels = channels
        self.rows = rows

    @classmethod
    def load(cls, path: Path) -> "SimplePNG":
        data = path.read_bytes()
        if not data.startswith(PNG_SIGNATURE):
            raise ValueError(f"{path} is not a PNG file.")

        offset = len(PNG_SIGNATURE)
        width = height = bit_depth = color_type = None
        idat_chunks: list[bytes] = []

        while offset < len(data):
            if offset + 8 > len(data):
                raise ValueError("Unexpected end of PNG while reading chunk header.")
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            chunk_type = data[offset + 4:offset + 8]
            chunk_start = offset + 8
            chunk_end = chunk_start + length
            crc_end = chunk_end + 4
            if crc_end > len(data):
                raise ValueError("Unexpected end of PNG while reading chunk body.")

            chunk_data = data[chunk_start:chunk_end]
            if chunk_type == b"IHDR":
                width, height, bit_depth, color_type, compression, png_filter, interlace = struct.unpack(
                    ">IIBBBBB", chunk_data
                )
                if bit_depth != 8:
                    raise ValueError(f"Unsupported PNG bit depth: {bit_depth}.")
                if color_type not in SUPPORTED_COLOR_TYPES:
                    raise ValueError(f"Unsupported PNG color type: {color_type}.")
                if compression != 0 or png_filter != 0 or interlace != 0:
                    raise ValueError("Unsupported PNG compression, filter, or interlace mode.")
            elif chunk_type == b"IDAT":
                idat_chunks.append(chunk_data)
            elif chunk_type == b"IEND":
                break
            offset = crc_end

        if width is None or height is None or color_type is None:
            raise ValueError("PNG is missing IHDR.")
        if not idat_chunks:
            raise ValueError("PNG is missing IDAT data.")

        channels = 3 if color_type == 2 else 4
        stride = width * channels
        raw = zlib.decompress(b"".join(idat_chunks))
        rows: list[bytearray] = []
        cursor = 0
        previous = bytearray(stride)

        for _ in range(height):
            if cursor >= len(raw):
                raise ValueError("PNG scanline data is truncated.")
            filter_type = raw[cursor]
            cursor += 1
            row = bytearray(raw[cursor:cursor + stride])
            cursor += stride
            if len(row) != stride:
                raise ValueError("PNG scanline data is truncated.")

            reconstructed = bytearray(stride)
            if filter_type == 0:
                reconstructed[:] = row
            elif filter_type == 1:
                for index in range(stride):
                    left = reconstructed[index - channels] if index >= channels else 0
                    reconstructed[index] = (row[index] + left) & 0xFF
            elif filter_type == 2:
                for index in range(stride):
                    reconstructed[index] = (row[index] + previous[index]) & 0xFF
            elif filter_type == 3:
                for index in range(stride):
                    left = reconstructed[index - channels] if index >= channels else 0
                    up = previous[index]
                    reconstructed[index] = (row[index] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                for index in range(stride):
                    left = reconstructed[index - channels] if index >= channels else 0
                    up = previous[index]
                    up_left = previous[index - channels] if index >= channels else 0
                    predictor = paeth_predictor(left, up, up_left)
                    reconstructed[index] = (row[index] + predictor) & 0xFF
            else:
                raise ValueError(f"Unsupported PNG filter type: {filter_type}.")

            rows.append(reconstructed)
            previous = reconstructed

        return cls(width=width, height=height, channels=channels, rows=rows)

    def pixel(self, x: int, y: int) -> tuple[int, int, int, int]:
        row = self.rows[y]
        start = x * self.channels
        if self.channels == 3:
            return row[start], row[start + 1], row[start + 2], 255
        return row[start], row[start + 1], row[start + 2], row[start + 3]

    def sample_bbox(self, bbox: dict[str, float], scale_x: float, scale_y: float, max_samples: int = 2600) -> dict[str, Any]:
        x0 = int(clamp(math.floor(bbox["x"] * scale_x), 0, self.width - 1))
        y0 = int(clamp(math.floor(bbox["y"] * scale_y), 0, self.height - 1))
        x1 = int(clamp(math.ceil((bbox["x"] + bbox["w"]) * scale_x), x0 + 1, self.width))
        y1 = int(clamp(math.ceil((bbox["y"] + bbox["h"]) * scale_y), y0 + 1, self.height))

        pixel_area = max((x1 - x0) * (y1 - y0), 1)
        step = max(1, int(math.sqrt(pixel_area / max_samples)))
        samples: list[tuple[int, int, int, int]] = []
        for y in range(y0, y1, step):
            for x in range(x0, x1, step):
                samples.append(self.pixel(x, y))

        return summarize_samples(samples)

    def sample_page(self, max_samples: int = 15000) -> dict[str, Any]:
        pixel_area = max(self.width * self.height, 1)
        step = max(1, int(math.sqrt(pixel_area / max_samples)))
        samples: list[tuple[int, int, int, int]] = []
        for y in range(0, self.height, step):
            for x in range(0, self.width, step):
                samples.append(self.pixel(x, y))
        return summarize_samples(samples)


def paeth_predictor(left: int, up: int, up_left: int) -> int:
    prediction = left + up - up_left
    left_distance = abs(prediction - left)
    up_distance = abs(prediction - up)
    up_left_distance = abs(prediction - up_left)
    if left_distance <= up_distance and left_distance <= up_left_distance:
        return left
    if up_distance <= up_left_distance:
        return up
    return up_left


def summarize_samples(samples: list[tuple[int, int, int, int]]) -> dict[str, Any]:
    visible = [pixel for pixel in samples if pixel[3] > 16]
    if not visible:
        return {
            "sample_count": 0,
            "foreground_ratio": 0.0,
            "dominant_color": (255, 255, 255),
            "dark_ratio": 0.0,
            "colorful_ratio": 0.0,
        }

    buckets = Counter(quantize_rgb(pixel) for pixel in visible)
    dominant_bucket, _ = buckets.most_common(1)[0]
    foreground = 0
    dark_pixels = 0
    colorful_pixels = 0

    for pixel in visible:
        rgb = (pixel[0], pixel[1], pixel[2])
        if color_distance(rgb, dominant_bucket) > 24:
            foreground += 1
        if luminance(pixel) < 232:
            dark_pixels += 1
        if saturation(pixel) > 18:
            colorful_pixels += 1

    foreground_ratio = foreground / len(visible)
    dark_ratio = dark_pixels / len(visible)
    colorful_ratio = colorful_pixels / len(visible)
    return {
        "sample_count": len(visible),
        "foreground_ratio": foreground_ratio,
        "dominant_color": dominant_bucket,
        "dark_ratio": dark_ratio,
        "colorful_ratio": colorful_ratio,
    }


def load_spec_page(spec_path: Path | None, page_name: str | None) -> dict[str, Any] | None:
    if spec_path is None:
        return None
    spec = json.loads(spec_path.read_text())
    pages = spec.get("pages")
    if not isinstance(pages, list) or not pages:
        return None

    selected_page: dict[str, Any] | None = None
    if page_name:
        for page in pages:
            if page.get("name") == page_name:
                selected_page = page
                break
    if selected_page is None:
        selected_page = pages[0]
    return selected_page


def load_spec_page_dimensions(
    spec_path: Path | None,
    page_name: str | None,
    default_width: float,
    default_height: float,
) -> tuple[float, float]:
    selected_page = load_spec_page(spec_path, page_name)
    if selected_page is None:
        return default_width, default_height
    return (
        float(selected_page.get("width", default_width)),
        float(selected_page.get("height", default_height)),
    )


def visible_spec_text(element: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("label", "text", "value", "external_label"):
        value = plain_text(element.get(key))
        if value:
            parts.append(value)
    return "\n".join(parts)


def searchable_spec_text(element: dict[str, Any]) -> str:
    parts = [visible_spec_text(element)]
    for key in ("id", "query", "shape"):
        value = plain_text(element.get(key))
        if value:
            parts.append(value)
    return " ".join(part for part in parts if part)


def flatten_spec_elements(page: dict[str, Any] | None) -> list[dict[str, Any]]:
    if page is None:
        return []
    placed: dict[str, dict[str, float]] = {}
    records: list[dict[str, Any]] = []
    raw_elements = page.get("elements") or []
    if not isinstance(raw_elements, list):
        return records

    for index, element in enumerate(raw_elements):
        if not isinstance(element, dict) or element.get("type") == "edge":
            continue
        parent_id = element.get("parent")
        parent_bbox = placed.get(str(parent_id), {"x": 0.0, "y": 0.0}) if parent_id else {"x": 0.0, "y": 0.0}
        bbox = {
            "x": float(parent_bbox.get("x", 0.0)) + float(element.get("x", 0.0)),
            "y": float(parent_bbox.get("y", 0.0)) + float(element.get("y", 0.0)),
            "w": float(element.get("w", element.get("width", 0.0)) or 0.0),
            "h": float(element.get("h", element.get("height", 0.0)) or 0.0),
        }
        record = {
            "id": str(element["id"]) if element.get("id") else None,
            "index": index,
            "parent": str(parent_id) if parent_id else None,
            "type": element.get("type"),
            "bbox": bbox,
            "raw": element,
            "visible_text": visible_spec_text(element),
            "search_text": searchable_spec_text(element),
        }
        records.append(record)
        if record["id"]:
            placed[record["id"]] = bbox

    return records


def spec_descendant_text_by_parent(spec_records: list[dict[str, Any]]) -> dict[str, str]:
    children_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in spec_records:
        parent_id = record.get("parent")
        if parent_id:
            children_by_parent[parent_id].append(record)

    cache: dict[str, str] = {}

    def collect(parent_id: str) -> str:
        if parent_id in cache:
            return cache[parent_id]
        parts: list[str] = []
        for child in children_by_parent.get(parent_id, []):
            child_text = str(child.get("visible_text") or "")
            if child_text:
                parts.append(child_text)
            child_id = child.get("id")
            if child_id:
                descendant_text = collect(str(child_id))
                if descendant_text:
                    parts.append(descendant_text)
        cache[parent_id] = " ".join(parts)
        return cache[parent_id]

    for record in spec_records:
        record_id = record.get("id")
        if record_id:
            collect(str(record_id))
    return cache


def normalize_report_page(report_path: Path, page_name: str | None) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    raw = json.loads(report_path.read_text())
    if isinstance(raw, dict) and isinstance(raw.get("pages"), list):
        pages = raw["pages"]
        selected = None
        if page_name:
            for page in pages:
                if page.get("page") == page_name:
                    selected = page
                    break
        if selected is None:
            selected = pages[0]
        page_label = str(selected.get("page") or page_name or "page-1")
        return page_label, list(selected.get("elements", [])), list(selected.get("edges", []))

    if isinstance(raw, list):
        by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in raw:
            by_page[str(record.get("page") or "page-1")].append(record)
        if not by_page:
            raise ValueError(f"{report_path} does not contain any report rows.")
        selected_name = page_name if page_name in by_page else sorted(by_page)[0]
        rows = by_page[selected_name]
        elements = [normalize_drawio_element(row) for row in rows if row.get("kind") != "edge"]
        element_by_id = {
            identifier_for_element(element): element
            for element in elements
        }
        edges = [
            normalize_drawio_edge(row, element_by_id)
            for row in rows
            if row.get("kind") == "edge"
        ]
        return selected_name, elements, edges

    raise ValueError(f"Unsupported report structure in {report_path}.")


def normalize_drawio_element(row: dict[str, Any]) -> dict[str, Any]:
    bbox = {
        "x": float(row.get("x", 0.0)),
        "y": float(row.get("y", 0.0)),
        "w": float(row.get("w", 0.0)),
        "h": float(row.get("h", 0.0)),
    }
    resolution = {
        "query": row.get("query"),
        "resolution": row.get("resolution"),
        "icon_title": row.get("icon_title"),
        "category": row.get("icon_title"),
        "source": row.get("source"),
    }
    return {
        "id": row.get("element_id") or row.get("cell_id"),
        "cell_id": row.get("cell_id"),
        "parent": row.get("parent_element_id"),
        "bbox": bbox,
        "kind": row.get("kind"),
        "role": row.get("role"),
        "label": row.get("label"),
        "text": row.get("text"),
        "visible": True,
        "qa_ignore": bool(row.get("qa_ignore")),
        "resolution": resolution,
        "category": row.get("icon_title"),
        "boundary_parent": None,
        "boundary_side": None,
    }


def anchor_point(bbox: dict[str, float], side: str | None) -> tuple[float, float]:
    x = bbox["x"]
    y = bbox["y"]
    w = bbox["w"]
    h = bbox["h"]
    if side == "left":
        return x, y + (h / 2)
    if side == "right":
        return x + w, y + (h / 2)
    if side == "top":
        return x + (w / 2), y
    if side == "bottom":
        return x + (w / 2), y + h
    return x + (w / 2), y + (h / 2)


def normalize_drawio_edge(row: dict[str, Any], element_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_id = row.get("source_element_id")
    target_id = row.get("target_element_id")
    source_bbox = element_by_id.get(str(source_id), {}).get("bbox", {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0})
    target_bbox = element_by_id.get(str(target_id), {}).get("bbox", {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0})
    points = [anchor_point(source_bbox, row.get("source_anchor"))]
    for waypoint in row.get("waypoints", []):
        points.append((float(waypoint.get("x", 0.0)), float(waypoint.get("y", 0.0))))
    points.append(anchor_point(target_bbox, row.get("target_anchor")))
    return {
        "id": row.get("cell_id"),
        "source": source_id,
        "target": target_id,
        "points": points,
        "semantic": row.get("label") or "",
    }


def identifier_for_element(element: dict[str, Any]) -> str:
    return str(element.get("id") or element.get("cell_id") or "unknown")


def apply_spec_metadata(element: dict[str, Any], spec_record: dict[str, Any]) -> None:
    raw = spec_record.get("raw") or {}
    element["spec"] = raw
    element["spec_index"] = spec_record.get("index")
    element["spec_text"] = spec_record.get("visible_text") or ""
    element["spec_search_text"] = spec_record.get("search_text") or ""
    for key in (
        "hide_internal_label",
        "preserve_internal_label",
        "external_label",
        "external_label_offset",
        "external_label_height",
        "qa_ignore",
    ):
        if key in raw:
            element[key] = raw.get(key)
    if raw.get("query") and not element.get("query"):
        element["query"] = raw.get("query")
    if raw.get("label") and not element.get("label"):
        element["label"] = raw.get("label")
    if raw.get("text") and not element.get("text"):
        element["text"] = raw.get("text")


def enrich_elements_with_spec(elements: list[dict[str, Any]], spec_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not spec_records:
        return elements

    spec_by_id = {
        str(record["id"]): record
        for record in spec_records
        if record.get("id")
    }
    descendant_text = spec_descendant_text_by_parent(spec_records)
    text_candidates = [
        record
        for record in spec_records
        if (record.get("type") == "text" or record.get("visible_text")) and bbox_area(record.get("bbox") or {}) > 0
    ]
    used_text_candidates: set[int] = set()

    enriched: list[dict[str, Any]] = []
    for original in elements:
        element = dict(original)
        element_id = element.get("id")
        spec_record = spec_by_id.get(str(element_id)) if element_id else None

        if spec_record is None and element.get("kind") == "text":
            element_bbox = element.get("bbox") or {}
            best_record: dict[str, Any] | None = None
            best_distance = float("inf")
            for candidate in text_candidates:
                candidate_index = int(candidate.get("index", -1))
                if candidate_index in used_text_candidates:
                    continue
                distance = math.hypot(
                    bbox_center(element_bbox)[0] - bbox_center(candidate["bbox"])[0],
                    bbox_center(element_bbox)[1] - bbox_center(candidate["bbox"])[1],
                )
                size_delta = abs(float(element_bbox.get("w", 0.0)) - float(candidate["bbox"].get("w", 0.0)))
                size_delta += abs(float(element_bbox.get("h", 0.0)) - float(candidate["bbox"].get("h", 0.0)))
                score = distance + (size_delta * 0.25)
                if score < best_distance:
                    best_record = candidate
                    best_distance = score
            if best_record is not None and best_distance <= 12.0:
                spec_record = best_record
                used_text_candidates.add(int(best_record.get("index", -1)))

        if spec_record is not None:
            apply_spec_metadata(element, spec_record)
            record_id = spec_record.get("id")
            if record_id:
                child_text = descendant_text.get(str(record_id), "")
                if child_text:
                    element["descendant_text"] = child_text
        enriched.append(element)

    return enriched


def add_virtual_external_label_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_ids = {identifier_for_element(element) for element in elements}
    result = list(elements)
    for element in elements:
        external_label = element.get("external_label")
        if not external_label or not element.get("id"):
            continue
        label_id = f"{element['id']}__external_label"
        if label_id in existing_ids:
            continue
        bbox = element.get("bbox") or {}
        result.append(
            {
                "id": label_id,
                "parent": element.get("id"),
                "kind": "text",
                "role": "text",
                "visible": True,
                "qa_ignore": bool(element.get("qa_ignore")),
                "bbox": {
                    "x": float(bbox.get("x", 0.0)),
                    "y": float(bbox.get("y", 0.0)) + float(bbox.get("h", 0.0)) + float(element.get("external_label_offset", 2.0) or 2.0),
                    "w": float(bbox.get("w", 0.0)),
                    "h": float(element.get("external_label_height", 20.0) or 20.0),
                },
                "text": external_label,
                "spec_text": external_label,
                "virtual": True,
            }
        )
    return result


def element_text(element: dict[str, Any]) -> str:
    parts = [
        element.get("text"),
        element.get("label"),
        element.get("spec_text"),
        element.get("external_label"),
    ]
    unique_parts: list[str] = []
    seen: set[str] = set()
    for part in (plain_text(value) for value in parts):
        if not part or part in seen:
            continue
        seen.add(part)
        unique_parts.append(part)
    return "\n".join(unique_parts)


def element_search_text(element: dict[str, Any]) -> str:
    resolution = element.get("resolution") if isinstance(element.get("resolution"), dict) else {}
    parts = [
        identifier_for_element(element),
        element.get("query"),
        element.get("category"),
        element.get("label"),
        element.get("text"),
        element.get("spec_text"),
        element.get("spec_search_text"),
        resolution.get("icon_title") if isinstance(resolution, dict) else None,
        resolution.get("category") if isinstance(resolution, dict) else None,
    ]
    return " ".join(part for part in (plain_text(value) for value in parts) if part).lower()


def element_deep_search_text(element: dict[str, Any]) -> str:
    parts = [element_search_text(element), element.get("descendant_text")]
    return " ".join(part for part in (plain_text(value) for value in parts) if part).lower()


def element_words(element: dict[str, Any]) -> set[str]:
    return token_set(element_search_text(element))


def element_deep_words(element: dict[str, Any]) -> set[str]:
    return token_set(element_deep_search_text(element))


def is_grouping_element(element: dict[str, Any]) -> bool:
    role = str(element.get("role") or "")
    if role == "grouping":
        return True
    if role == "special-connector":
        return False
    resolution = element.get("resolution")
    if not isinstance(resolution, dict):
        return False
    icon_title = str(resolution.get("icon_title") or "")
    category = str(element.get("category") or resolution.get("category") or "")
    if category == "Physical":
        return True
    return "Grouping -" in icon_title or icon_title.startswith("Physical - Grouping -")


def is_service_icon(element: dict[str, Any]) -> bool:
    if not element.get("visible", True) or element.get("qa_ignore"):
        return False
    if element.get("kind") != "library":
        return False
    resolution = element.get("resolution")
    if not isinstance(resolution, dict):
        return False
    resolution_type = str(resolution.get("resolution") or "")
    if resolution_type not in {"direct", "alias", "closest"}:
        return False
    if is_grouping_element(element):
        return False
    bbox = element.get("bbox") or {}
    return float(bbox.get("w", 0.0)) * float(bbox.get("h", 0.0)) >= 500.0


def is_text_like(element: dict[str, Any]) -> bool:
    element_id = identifier_for_element(element)
    if element.get("kind") == "text":
        return True
    return element_id.endswith("__external_label")


def is_vcn(element: dict[str, Any]) -> bool:
    return is_grouping_element(element) and "vcn" in element_words(element)


def is_subnet(element: dict[str, Any]) -> bool:
    return is_grouping_element(element) and "subnet" in element_words(element)


def is_data_subnet(element: dict[str, Any]) -> bool:
    words = element_words(element)
    return is_subnet(element) and "data" in words


def is_availability_domain(element: dict[str, Any]) -> bool:
    words = element_words(element)
    return is_grouping_element(element) and "availability" in words and "domain" in words


def gateway_kind(element: dict[str, Any]) -> str | None:
    words = element_words(element)
    search_text = normalized_text(element_search_text(element))
    if "gateway" not in words and "igw" not in words:
        return None
    if "internet gateway" in search_text or "igw" in words:
        return "internet"
    if "nat gateway" in search_text or "nat" in words:
        return "nat"
    if "service gateway" in search_text or ("service" in words and "gateway" in words):
        return "service"
    return None


def is_load_balancer(element: dict[str, Any]) -> bool:
    words = element_words(element)
    return "load" in words and "balancer" in words


def is_database(element: dict[str, Any]) -> bool:
    words = element_words(element)
    search_text = normalized_text(element_search_text(element))
    return (
        "database" in words
        or "db" in words
        or "autonomous db" in search_text
        or "autonomous database" in search_text
        or "exadata" in words
        or "mysql" in words
        or "postgresql" in words
    )


def is_public_ingress_source(element: dict[str, Any], element_by_id: dict[str, dict[str, Any]], vcn_ids: set[str]) -> bool:
    words = element_words(element)
    if is_inside_any_container(element, element_by_id, vcn_ids):
        return False
    if {"internet", "clients"} & words:
        return True
    if "dns" in words or "waf" in words:
        return True
    if "api" in words and "gateway" in words:
        return True
    return False


def is_support_or_ops_panel(element: dict[str, Any]) -> bool:
    if element.get("qa_ignore") or is_grouping_element(element) or is_service_icon(element):
        return False
    words = element_deep_words(element)
    support_words = {
        "security",
        "operations",
        "observability",
        "monitoring",
        "logging",
        "management",
        "support",
        "services",
    }
    return bool(words & support_words)


def parent_chain(element: dict[str, Any], element_by_id: dict[str, dict[str, Any]]) -> list[str]:
    chain: list[str] = []
    parent = element.get("parent")
    seen: set[str] = set()
    while parent:
        parent_id = str(parent)
        if parent_id in seen:
            break
        seen.add(parent_id)
        chain.append(parent_id)
        parent_element = element_by_id.get(parent_id)
        if parent_element is None:
            break
        parent = parent_element.get("parent")
    return chain


def is_inside_any_container(element: dict[str, Any], element_by_id: dict[str, dict[str, Any]], container_ids: set[str]) -> bool:
    element_id = identifier_for_element(element)
    return element_id in container_ids or bool(set(parent_chain(element, element_by_id)) & container_ids)


def elements_related(first: dict[str, Any], second: dict[str, Any], element_by_id: dict[str, dict[str, Any]]) -> bool:
    first_id = identifier_for_element(first)
    second_id = identifier_for_element(second)
    if first_id == second_id:
        return True
    return first_id in parent_chain(second, element_by_id) or second_id in parent_chain(first, element_by_id)


def segment_intersects_bbox(
    start: tuple[float, float],
    end: tuple[float, float],
    bbox: dict[str, float],
    padding: float,
) -> bool:
    min_x = bbox["x"] - padding
    max_x = bbox["x"] + bbox["w"] + padding
    min_y = bbox["y"] - padding
    max_y = bbox["y"] + bbox["h"] + padding
    if math.isclose(start[1], end[1]):
        y = start[1]
        segment_start = min(start[0], end[0])
        segment_end = max(start[0], end[0])
        return min_y <= y <= max_y and max(segment_start, min_x) <= min(segment_end, max_x)
    if math.isclose(start[0], end[0]):
        x = start[0]
        segment_start = min(start[1], end[1])
        segment_end = max(start[1], end[1])
        return min_x <= x <= max_x and max(segment_start, min_y) <= min(segment_end, max_y)
    return False


def edge_segments(points: list[tuple[float, float]]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return list(zip(points, points[1:]))


def segment_boundary_overlap(
    start: tuple[float, float],
    end: tuple[float, float],
    bbox: dict[str, float],
    padding: float = BOUNDARY_LANE_PADDING,
) -> float:
    left = float(bbox.get("x", 0.0))
    right = left + float(bbox.get("w", 0.0))
    top = float(bbox.get("y", 0.0))
    bottom = top + float(bbox.get("h", 0.0))
    if math.isclose(start[1], end[1], abs_tol=padding):
        y = (start[1] + end[1]) / 2
        if not (math.isclose(y, top, abs_tol=padding) or math.isclose(y, bottom, abs_tol=padding)):
            return 0.0
        segment_start = min(start[0], end[0])
        segment_end = max(start[0], end[0])
        return max(min(segment_end, right) - max(segment_start, left), 0.0)
    if math.isclose(start[0], end[0], abs_tol=padding):
        x = (start[0] + end[0]) / 2
        if not (math.isclose(x, left, abs_tol=padding) or math.isclose(x, right, abs_tol=padding)):
            return 0.0
        segment_start = min(start[1], end[1])
        segment_end = max(start[1], end[1])
        return max(min(segment_end, bottom) - max(segment_start, top), 0.0)
    return 0.0


def gateway_on_vcn_boundary(gateway: dict[str, Any], vcns: list[dict[str, Any]]) -> bool:
    center_x, center_y = bbox_center(gateway.get("bbox") or {})
    gateway_bbox = gateway.get("bbox") or {}
    tolerance = max(8.0, min(float(gateway_bbox.get("w", 0.0)), float(gateway_bbox.get("h", 0.0))) * 0.18)
    for vcn in vcns:
        bbox = vcn.get("bbox") or {}
        left = float(bbox.get("x", 0.0))
        right = left + float(bbox.get("w", 0.0))
        top = float(bbox.get("y", 0.0))
        bottom = top + float(bbox.get("h", 0.0))
        within_y = top - tolerance <= center_y <= bottom + tolerance
        within_x = left - tolerance <= center_x <= right + tolerance
        if within_y and (math.isclose(center_x, left, abs_tol=tolerance) or math.isclose(center_x, right, abs_tol=tolerance)):
            return True
        if within_x and (math.isclose(center_y, top, abs_tol=tolerance) or math.isclose(center_y, bottom, abs_tol=tolerance)):
            return True
    return False


def service_label_signature(element: dict[str, Any]) -> set[str]:
    words = element_words(element)
    search_text = normalized_text(element_search_text(element))
    if "waf" in words:
        return {"waf"}
    if "flexible load balancer" in search_text or ("load" in words and "balancer" in words):
        return {"load", "balancer"}
    if "internet gateway" in search_text or "igw" in words:
        return {"internet", "gateway"}
    if "nat gateway" in search_text or ("nat" in words and "gateway" in words):
        return {"nat", "gateway"}
    if "service gateway" in search_text or ("service" in words and "gateway" in words):
        return {"service", "gateway"}
    return set()


def internal_icon_label_hidden(element: dict[str, Any]) -> bool:
    if bool(element.get("hide_internal_label")):
        return True
    if element.get("external_label") and not bool(element.get("preserve_internal_label")):
        return True
    return False


def audit_architecture_visual_gates(
    elements: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    element_by_id = {
        identifier_for_element(element): element
        for element in elements
        if identifier_for_element(element) != "unknown"
    }
    vcns = [element for element in elements if is_vcn(element)]
    vcn_ids = {identifier_for_element(element) for element in vcns}
    subnets = [element for element in elements if is_subnet(element)]
    availability_domains = [element for element in elements if is_availability_domain(element)]
    data_subnets = [element for element in subnets if is_data_subnet(element)]
    gateways = [element for element in elements if is_service_icon(element) and gateway_kind(element)]
    internet_gateways = [element for element in gateways if gateway_kind(element) == "internet"]
    text_like_elements = [element for element in elements if is_text_like(element)]
    connected_ids = {
        str(endpoint)
        for edge in edges
        for endpoint in (edge.get("source"), edge.get("target"))
        if endpoint is not None
    }

    for gateway in gateways:
        gateway_id = identifier_for_element(gateway)
        if vcns and not gateway_on_vcn_boundary(gateway, vcns):
            issues.append(
                {
                    "severity": "error",
                    "type": "gateway-not-on-vcn-boundary",
                    "element_id": gateway_id,
                    "message": (
                        f"{gateway_id} is shown away from the VCN boundary. "
                        "Internet, NAT, and Service Gateways should straddle the VCN edge instead of floating as decorative icons."
                    ),
                }
            )

    if internet_gateways:
        igw_ids = {identifier_for_element(element) for element in internet_gateways}
        public_ingress_to_vcn = False
        for edge in edges:
            source = element_by_id.get(str(edge.get("source")))
            target = element_by_id.get(str(edge.get("target")))
            if not source or not target:
                continue
            source_id = identifier_for_element(source)
            target_id = identifier_for_element(target)
            if source_id in igw_ids or target_id in igw_ids:
                continue
            if is_public_ingress_source(source, element_by_id, vcn_ids) and is_inside_any_container(target, element_by_id, vcn_ids):
                public_ingress_to_vcn = True
                issues.append(
                    {
                        "severity": "error",
                        "type": "public-ingress-bypasses-internet-gateway",
                        "edge_id": edge.get("id"),
                        "message": (
                            f"Public ingress edge {edge.get('id')} enters the VCN without traversing the Internet Gateway. "
                            "When an Internet Gateway is shown, the public ingress path must visibly pass through it before the public subnet or load balancer."
                        ),
                    }
                )
        for gateway in internet_gateways:
            gateway_id = identifier_for_element(gateway)
            if gateway_id not in connected_ids and public_ingress_to_vcn:
                issues.append(
                    {
                        "severity": "error",
                        "type": "internet-gateway-decorative",
                        "element_id": gateway_id,
                        "message": (
                            f"{gateway_id} is present but not connected to the public ingress flow. "
                            "Do not leave Internet Gateways as decorative network furniture."
                        ),
                    }
                )

    for panel in [element for element in elements if is_support_or_ops_panel(element)]:
        panel_bbox = panel.get("bbox") or {}
        for container in [*vcns, *subnets, *availability_domains]:
            if elements_related(panel, container, element_by_id):
                continue
            overlap = bbox_intersection_area(panel_bbox, container.get("bbox") or {})
            if overlap <= 0:
                continue
            overlap_ratio = overlap / max(min(bbox_area(panel_bbox), bbox_area(container.get("bbox") or {})), 1.0)
            if overlap_ratio >= 0.03 and overlap >= 500.0:
                issues.append(
                    {
                        "severity": "error",
                        "type": "support-panel-overlaps-network-boundary",
                        "element_id": identifier_for_element(panel),
                        "container_id": identifier_for_element(container),
                        "message": (
                            f"{identifier_for_element(panel)} overlaps {identifier_for_element(container)}. "
                            "Support, security, and operations panels must sit beside network tiers, not on top of VCN, subnet, or AD boundaries."
                        ),
                    }
                )
                break

    for database in [element for element in elements if is_service_icon(element) and is_database(element)]:
        database_center = bbox_center(database.get("bbox") or {})
        containing_data_subnet = next(
            (subnet for subnet in data_subnets if bbox_contains_point(subnet.get("bbox") or {}, database_center, padding=1.0)),
            None,
        )
        for availability_domain in availability_domains:
            if not bbox_contains_point(availability_domain.get("bbox") or {}, database_center, padding=1.0):
                continue
            if containing_data_subnet is None:
                continue
            if not bbox_contains_bbox(availability_domain.get("bbox") or {}, containing_data_subnet.get("bbox") or {}, padding=1.0):
                issues.append(
                    {
                        "severity": "error",
                        "type": "regional-data-tier-inside-ad-lane",
                        "element_id": identifier_for_element(database),
                        "container_id": identifier_for_element(availability_domain),
                        "message": (
                            f"{identifier_for_element(database)} sits inside {identifier_for_element(availability_domain)} while also being in a regional data subnet. "
                            "Keep regional data tiers visually outside AD background lanes unless the database is intentionally AD-scoped."
                        ),
                    }
                )
                break

    for service in [element for element in elements if is_service_icon(element)]:
        signature = service_label_signature(service)
        if not signature or internal_icon_label_hidden(service):
            continue
        service_bbox = service.get("bbox") or {}
        for label in text_like_elements:
            label_text = element_text(label)
            if not label_text:
                continue
            label_words = token_set(label_text)
            if not signature.issubset(label_words):
                continue
            if bbox_gap(service_bbox, label.get("bbox") or {}) > 48.0:
                continue
            issues.append(
                {
                    "severity": "error",
                    "type": "duplicate-native-and-custom-label",
                    "element_id": identifier_for_element(service),
                    "label_id": identifier_for_element(label),
                    "message": (
                        f"{identifier_for_element(service)} appears to have both its native OCI icon label and a nearby custom label. "
                        "Set hide_internal_label: true, preserve only one label, or move the custom label out of the traffic lane."
                    ),
                }
            )
            break

    for label in text_like_elements:
        label_text = element_text(label)
        label_words = token_set(label_text)
        if "gateway" not in label_words:
            continue
        line_count = max(1, len([line for line in label_text.splitlines() if line.strip()]))
        if line_count >= 3:
            issues.append(
                {
                    "severity": "error",
                    "type": "gateway-label-overwrapped",
                    "element_id": identifier_for_element(label),
                    "message": (
                        f"{identifier_for_element(label)} wraps a gateway label into {line_count} lines. "
                        "Use a wider side label or hide the native label instead of letting gateway text stack vertically."
                    ),
                }
            )

    boundary_containers = [
        element
        for element in elements
        if is_vcn(element) or is_subnet(element) or is_availability_domain(element)
    ]
    for edge in edges:
        points = edge.get("points") or []
        if len(points) < 2:
            continue
        for start, end in edge_segments(points):
            for container in boundary_containers:
                overlap = segment_boundary_overlap(start, end, container.get("bbox") or {})
                if overlap < MIN_BOUNDARY_LANE_OVERLAP:
                    continue
                issues.append(
                    {
                        "severity": "error",
                        "type": "connector-on-container-boundary",
                        "edge_id": edge.get("id"),
                        "container_id": identifier_for_element(container),
                        "message": (
                            f"Connector {edge.get('id')} runs along the boundary of {identifier_for_element(container)} for {overlap:.0f}px. "
                            "Move traffic flows onto dedicated lanes instead of sharing VCN, subnet, or AD borders."
                        ),
                    }
                )
                break
            else:
                continue
            break

    return issues


def audit_preview(
    preview_path: Path,
    report_path: Path,
    spec_path: Path | None,
    page_name: str | None,
    page_width: float,
    page_height: float,
) -> dict[str, Any]:
    page_label, elements, edges = normalize_report_page(report_path, page_name)
    spec_page = load_spec_page(spec_path, page_label)
    if spec_page is None:
        logical_width, logical_height = page_width, page_height
        spec_records: list[dict[str, Any]] = []
    else:
        logical_width = float(spec_page.get("width", page_width))
        logical_height = float(spec_page.get("height", page_height))
        spec_records = flatten_spec_elements(spec_page)
    elements = enrich_elements_with_spec(elements, spec_records)
    elements = add_virtual_external_label_elements(elements)
    image = SimplePNG.load(preview_path)
    scale_x = image.width / logical_width
    scale_y = image.height / logical_height

    page_stats = image.sample_page()
    page_foreground_ratio = max(page_stats["foreground_ratio"], page_stats["dark_ratio"] * 0.8)

    service_icons = [element for element in elements if is_service_icon(element)]
    text_like_elements = [element for element in elements if is_text_like(element)]

    issues: list[dict[str, Any]] = []
    icon_metrics: list[dict[str, Any]] = []

    issues.extend(audit_architecture_visual_gates(elements, edges))

    for element in service_icons:
        bbox = element["bbox"]
        stats = image.sample_bbox(bbox, scale_x, scale_y)
        visibility_ratio = max(stats["foreground_ratio"], stats["dark_ratio"], stats["colorful_ratio"])
        metric = {
            "element_id": identifier_for_element(element),
            "icon_title": element.get("resolution", {}).get("icon_title"),
            "foreground_ratio": visibility_ratio,
            "dominant_color": stats["dominant_color"],
        }
        icon_metrics.append(metric)

        if visibility_ratio < ICON_FOREGROUND_THRESHOLD:
            issues.append(
                {
                    "severity": "error",
                    "type": "icon-visibility-low",
                    "element_id": identifier_for_element(element),
                    "message": (
                        f"{identifier_for_element(element)} looks visually blank or clipped in the preview "
                        f"(foreground ratio {visibility_ratio:.3f})."
                    ),
                }
            )
        elif visibility_ratio < ICON_VISIBILITY_WARNING_THRESHOLD:
            issues.append(
                {
                    "severity": "warning",
                    "type": "icon-visibility-weak",
                    "element_id": identifier_for_element(element),
                    "message": (
                        f"{identifier_for_element(element)} is only weakly visible in the preview "
                        f"(foreground ratio {visibility_ratio:.3f})."
                    ),
                }
            )

    for element in text_like_elements:
        bbox = element.get("bbox") or {}
        element_id = identifier_for_element(element)
        for edge in edges:
            points = edge.get("points") or []
            if len(points) < 2:
                continue
            for start, end in edge_segments(points):
                if segment_intersects_bbox(start, end, bbox, TEXT_EDGE_PADDING):
                    issues.append(
                        {
                            "severity": "error",
                            "type": "label-on-connector",
                            "element_id": element_id,
                            "edge_id": edge.get("id"),
                            "message": f"{element_id} sits on top of connector {edge.get('id')}.",
                        }
                    )
                    break
            else:
                continue
            break

    external_label_count = sum(1 for element in text_like_elements if identifier_for_element(element).endswith("__external_label"))
    median_icon_visibility = median([metric["foreground_ratio"] for metric in icon_metrics])
    if service_icons and external_label_count > len(service_icons) * TEXT_CARD_RATIO_THRESHOLD and median_icon_visibility < 0.03:
        issues.append(
            {
                "severity": "warning",
                "type": "text-card-dominance",
                "message": (
                    "The preview is dominated by detached labels relative to visible service icons. "
                    "Consider restoring stronger icon emphasis or reducing external labels."
                ),
            }
        )

    if page_foreground_ratio < PAGE_FOREGROUND_WARNING_THRESHOLD:
        issues.append(
            {
                "severity": "warning",
                "type": "sparse-preview",
                "message": (
                    f"The preview reads as visually sparse (page foreground ratio {page_foreground_ratio:.3f}). "
                    "Consider tightening the layout or increasing meaningful foreground content."
                ),
            }
        )

    return {
        "page": page_label,
        "preview": str(preview_path),
        "report": str(report_path),
        "image_size": {"width": image.width, "height": image.height},
        "logical_page_size": {"width": logical_width, "height": logical_height},
        "metrics": {
            "page_foreground_ratio": page_foreground_ratio,
            "service_icon_count": len(service_icons),
            "text_like_count": len(text_like_elements),
            "external_label_count": external_label_count,
            "median_icon_visibility": median_icon_visibility,
            "icon_metrics": icon_metrics,
        },
        "issue_count": len(issues),
        "issues": issues,
    }


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", type=Path, required=True, help="Preview PNG to audit.")
    parser.add_argument("--report", type=Path, required=True, help="Renderer report JSON.")
    parser.add_argument("--spec", type=Path, help="Renderable spec JSON, used to discover logical page size.")
    parser.add_argument("--page-name", help="Optional page name when the report contains multiple pages.")
    parser.add_argument("--page-width", type=float, default=1600.0, help="Fallback logical page width.")
    parser.add_argument("--page-height", type=float, default=900.0, help="Fallback logical page height.")
    parser.add_argument("--output", type=Path, help="Optional audit JSON path.")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit non-zero if any issues are found.")
    args = parser.parse_args()

    audit = audit_preview(
        preview_path=args.preview.resolve(),
        report_path=args.report.resolve(),
        spec_path=args.spec.resolve() if args.spec else None,
        page_name=args.page_name,
        page_width=args.page_width,
        page_height=args.page_height,
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(audit, indent=2) + "\n")

    print(json.dumps(audit, indent=2))
    if args.fail_on_issues and audit["issue_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
