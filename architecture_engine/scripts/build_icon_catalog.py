#!/usr/bin/env python3
"""Build a normalized OCI icon catalog from the bundled draw.io assets."""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

SUPPLEMENTAL_ICONS = [
    {"title": "Networking - Route Table and Security List", "source": "toolkit-v24.2-icons-page"},
    {"title": "Database - Oracle Base Database", "source": "toolkit-v24.2-icons-page"},
    {"title": "Database - Management Data Guard", "source": "toolkit-v24.2-icons-page"},
    {"title": "Database - Recovery", "source": "toolkit-v24.2-icons-page"},
    {"title": "Database - HeatWave", "source": "toolkit-v24.2-icons-page"},
    {"title": "Database - Lakehouse", "source": "toolkit-v24.2-icons-page"},
    {"title": "Database - Data Lake", "source": "toolkit-v24.2-icons-page"},
    {"title": "Database - Oracle REST Data Services", "source": "toolkit-v24.2-icons-page"},
    {"title": "Database - Flashback", "source": "toolkit-v24.2-icons-page"},
    {"title": "Database - OCI Database with PostgreSQL", "source": "toolkit-v24.2-icons-page"},
    {"title": "Migration - OCI Migrate", "source": "toolkit-v24.2-icons-page"},
    {"title": "Migration - Migration Workbench", "source": "toolkit-v24.2-icons-page"},
    {"title": "Migration - Estate Explorer", "source": "toolkit-v24.2-icons-page"},
    {"title": "Migration - Oracle Database Migration Service", "source": "toolkit-v24.2-icons-page"},
    {"title": "Analytics and AI - Document Understanding", "source": "toolkit-v24.2-icons-page"},
    {"title": "Analytics and AI - Data Flow", "source": "toolkit-v24.2-icons-page"},
    {"title": "Analytics and AI - Forecasting", "source": "toolkit-v24.2-icons-page"},
    {"title": "Analytics and AI - Generative AI", "source": "toolkit-v24.2-icons-page"},
    {"title": "Analytics and AI - OCI Language", "source": "toolkit-v24.2-icons-page"},
    {"title": "Analytics and AI - OCI Generative AI", "source": "toolkit-v24.2-icons-page"},
    {"title": "Analytics and AI - OCI Speech", "source": "toolkit-v24.2-icons-page"},
    {"title": "Analytics and AI - OCI Vision", "source": "toolkit-v24.2-icons-page"},
    {"title": "Identity and Security - Key Vault", "source": "toolkit-v24.2-icons-page"},
]

NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
ACRONYM_RE = re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)?\b")


def normalize(text: str) -> str:
    text = html.unescape(text).replace("\xa0", " ")
    text = text.lower().strip()
    text = NORMALIZE_RE.sub(" ", text)
    return " ".join(text.split())


def tokenize(text: str) -> list[str]:
    return [token for token in normalize(text).split() if token]


def split_title(title: str) -> tuple[str, str]:
    if " - " in title:
        category, name = title.split(" - ", 1)
        return category, name
    return title, title


def extract_acronyms(text: str) -> list[str]:
    return sorted({match.group(0).lower() for match in ACRONYM_RE.finditer(text)})


def build_entry(title: str, source: str) -> dict[str, Any]:
    clean_title = " ".join(html.unescape(title).replace("\xa0", " ").split())
    category, name = split_title(clean_title)
    return {
        "title": clean_title,
        "category": category,
        "name": name,
        "normalized_title": normalize(clean_title),
        "normalized_name": normalize(name),
        "tokens": tokenize(name),
        "acronyms": extract_acronyms(clean_title),
        "source": source,
    }


def parse_library(library_path: Path) -> list[dict[str, Any]]:
    content = library_path.read_text()
    match = re.search(r"<mxlibrary>(.*)</mxlibrary>", content, re.DOTALL)
    if not match:
        raise ValueError(f"Could not find <mxlibrary> payload in {library_path}")

    raw_items = json.loads(match.group(1))
    seen_titles: set[str] = set()
    catalog: list[dict[str, Any]] = []

    for raw_item in raw_items:
        title = " ".join(html.unescape(raw_item.get("title", "")).replace("\xa0", " ").split())
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        catalog.append(build_entry(title, "oci-library.xml"))

    return catalog


def add_supplements(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_titles = {entry["title"] for entry in catalog}
    merged = list(catalog)

    for supplemental in SUPPLEMENTAL_ICONS:
        if supplemental["title"] in seen_titles:
            continue
        seen_titles.add(supplemental["title"])
        merged.append(build_entry(supplemental["title"], supplemental["source"]))

    merged.sort(key=lambda entry: (entry["category"], entry["name"], entry["title"]))
    return merged


def build_catalog(library_path: Path) -> list[dict[str, Any]]:
    return add_supplements(parse_library(library_path))


def write_json(path: Path, catalog: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2, sort_keys=False) + "\n")


def write_markdown(path: Path, catalog: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in catalog:
        grouped[entry["category"]].append(entry)

    lines = [
        "# OCI Icon Catalog",
        "",
        "This catalog merges the older machine-readable `oci-library.xml` with a curated supplement of newer toolkit-only icons observed in `oci-architecture-toolkit-v24.2.drawio`.",
        "",
        f"Total entries: {len(catalog)}",
        "",
        "## Category Counts",
        "",
    ]

    for category in sorted(grouped):
        lines.append(f"- {category}: {len(grouped[category])}")

    lines.extend(["", "## Titles", ""])

    for category in sorted(grouped):
        lines.append(f"### {category}")
        lines.append("")
        for entry in grouped[category]:
            suffix = " _(toolkit supplement)_" if entry["source"] != "oci-library.xml" else ""
            lines.append(f"- {entry['title']}{suffix}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def default_paths() -> tuple[Path, Path, Path]:
    skill_dir = Path(__file__).resolve().parents[1]
    library_path = skill_dir / "assets" / "drawio" / "oci-library.xml"
    json_path = skill_dir / "references" / "icon-catalog.json"
    md_path = skill_dir / "references" / "icon-catalog.md"
    return library_path, json_path, md_path


def main() -> None:
    default_library, default_json, default_md = default_paths()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=default_library, help="Path to oci-library.xml")
    parser.add_argument("--json-out", type=Path, default=default_json, help="Output JSON catalog path")
    parser.add_argument("--md-out", type=Path, default=default_md, help="Output Markdown catalog path")
    args = parser.parse_args()

    catalog = build_catalog(args.library)
    write_json(args.json_out, catalog)
    write_markdown(args.md_out, catalog)

    category_count = len({entry["category"] for entry in catalog})
    supplement_count = sum(1 for entry in catalog if entry["source"] != "oci-library.xml")
    print(f"Wrote {len(catalog)} icon entries across {category_count} categories.")
    print(f"Included {supplement_count} curated toolkit-only additions.")
    print(f"JSON: {args.json_out}")
    print(f"Markdown: {args.md_out}")


if __name__ == "__main__":
    main()
