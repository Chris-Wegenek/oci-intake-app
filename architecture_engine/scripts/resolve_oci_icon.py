#!/usr/bin/env python3
"""Resolve workload components to OCI draw.io icons with explicit fallbacks."""

from __future__ import annotations

import argparse
import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from build_icon_catalog import build_catalog, default_paths, normalize, tokenize

COMMON_ALIASES = {
    "adb": "Database - Autonomous DB",
    "autonomous db": "Database - Autonomous DB",
    "autonomous database": "Database - Autonomous DB",
    "adw": "Database - Autonomous Data Warehouse ADW",
    "autonomous data warehouse": "Database - Autonomous Data Warehouse ADW",
    "atp": "Database - Autonomous Transaction Processing ATP",
    "autonomous transaction processing": "Database - Autonomous Transaction Processing ATP",
    "apigw": "Developer Services - API Gateway",
    "api gateway": "Developer Services - API Gateway",
    "ocir": "Developer Services - Container Registry",
    "container registry": "Developer Services - Container Registry",
    "oke": "Developer Services - Container Engine for Kubernetes",
    "container engine for kubernetes": "Developer Services - Container Engine for Kubernetes",
    "kubernetes": "Developer Services - Container Engine for Kubernetes",
    "k8s": "Developer Services - Container Engine for Kubernetes",
    "service mesh": "Developer Services - Service Mesh",
    "functions": "Compute - Functions",
    "vm": "Compute - Virtual Machine VM",
    "virtual machine": "Compute - Virtual Machine VM",
    "flex vm": "Compute - Flex Virtual Machine Flex VM",
    "burstable vm": "Compute - Burstable Virtual Machine Burstable VM",
    "object storage": "Storage - Object Storage",
    "bucket": "Storage - Buckets",
    "buckets": "Storage - Buckets",
    "block storage": "Storage - Block Storage",
    "file storage": "Storage - File Storage",
    "vcn": "Networking - Virtual Cloud Network VCN",
    "lb": "Networking - Load Balancer",
    "load balancer": "Networking - Load Balancer",
    "flexible load balancer": "Networking - Flexible Load Balancer",
    "dns": "Networking - DNS",
    "cpe": "Networking - Customer Premises Equipment CPE",
    "customer premises equipment": "Networking - Customer Premises Equipment CPE",
    "customer premises equipment cpe": "Networking - Customer Premises Equipment CPE",
    "drg": "Networking - Dynamic Routing Gateway DRG",
    "service gateway": "Networking - Service Gateway",
    "internet gateway": "Networking - Internet Gateway",
    "nat gateway": "Networking - NAT Gateway",
    "remote peering gateway": "Networking - Remote Peering Gateway",
    "route table": "Networking - Route Table",
    "route table and security list": "Networking - Route Table and Security List",
    "route table with security list": "Networking - Route Table and Security List",
    "postgres": "Database - OCI Database with PostgreSQL",
    "postgresql": "Database - OCI Database with PostgreSQL",
    "ords": "Database - Oracle REST Data Services",
    "database migration service": "Migration - Oracle Database Migration Service",
    "db migration service": "Migration - Oracle Database Migration Service",
    "oci migrate": "Migration - OCI Migrate",
    "heatwave": "Database - HeatWave",
    "data lake": "Database - Data Lake",
    "lakehouse": "Database - Lakehouse",
    "waf": "Identity and Security - WAF",
    "iam": "Identity and Security - IAM Identity and Access Management",
    "identity and access management": "Identity and Security - IAM Identity and Access Management",
    "vault": "Identity and Security - Vault",
    "key vault": "Identity and Security - Key Vault",
    "bastion": "Identity and Security - Bastion",
    "nsg": "Identity and Security - NSG",
    "security list": "Identity and Security - Security Lists",
    "ddos": "Identity and Security - DDoS Protection",
    "cloud guard": "Identity and Security - Cloud Guard",
    "data safe": "Database - Data Safe",
    "opensearch": "Database - OpenSearch",
    "goldengate": "Database - GoldenGate",
    "oci generative ai": "Analytics and AI - OCI Generative AI",
    "genai": "Analytics and AI - OCI Generative AI",
    "generative ai": "Analytics and AI - Generative AI",
    "oci data flow": "Analytics and AI - Data Flow",
    "language": "Analytics and AI - OCI Language",
    "speech": "Analytics and AI - OCI Speech",
    "vision": "Analytics and AI - OCI Vision",
    "document understanding": "Analytics and AI - Document Understanding",
    "forecasting": "Analytics and AI - Forecasting",
    "fastconnect": "Physical - Special Connectors - FastConnect - Horizontal",
    "site to site vpn": "Physical - Special Connectors - Site-to-site-VPN - Vertical",
    "site-to-site vpn": "Physical - Special Connectors - Site-to-site-VPN - Vertical",
    "s2s vpn": "Physical - Special Connectors - Site-to-site-VPN - Vertical",
    "remote peering": "Physical - Special Connectors - Remote Peering - Horizontal",
}

PHYSICAL_APPROVED_FALLBACKS = {
    "queue": "Analytics and AI - Streaming",
    "oci queue": "Analytics and AI - Streaming",
    "queue service": "Analytics and AI - Streaming",
    "message queue": "Analytics and AI - Streaming",
}

PLACEHOLDER_SHAPES = {
    "app": "rounded-rectangle",
    "data": "cylinder",
    "network": "hexagon",
    "external": "cloud",
    "user": "ellipse",
}

LOGICAL_GENERIC_ICONS = {
    "oci": "Logical - Components - OCI Component",
    "onprem": "Logical - Components - Oracle On-Premises Component",
    "external": "Logical - Components -3rd Party Non- OCI",
}

PAGE_OVERRIDES = {
    "physical": {
        "vcn": "Physical - Grouping - VCN",
        "subnet": "Physical - Grouping - Subnet",
        "compartment": "Physical - Grouping - Compartment",
        "compartments": "Physical - Grouping - Compartment",
        "tenancy": "Physical - Grouping - Tenancy",
        "oci region": "Physical - Grouping - OCI Region",
        "region": "Physical - Grouping - OCI Region",
        "availability domain": "Physical - Grouping - Availability Domain",
        "fault domain": "Physical - Grouping - Fault Domain",
        "user group": "Physical - Grouping - User Group",
        "tier": "Physical - Grouping - Tier",
        "connector": "Physical - Connector",
        "fastconnect": "Physical - Special Connectors - FastConnect - Horizontal",
        "site to site vpn": "Physical - Special Connectors - Site-to-site-VPN - Vertical",
        "site-to-site vpn": "Physical - Special Connectors - Site-to-site-VPN - Vertical",
        "remote peering": "Physical - Special Connectors - Remote Peering - Horizontal",
    },
    "logical": {
        "oracle cloud": "Logical - Grouping - Oracle Cloud",
        "internet": "Logical - Grouping - Internet",
        "on premises": "Logical - Grouping - On-Premises",
        "on-premises": "Logical - Grouping - On-Premises",
        "3rd party cloud": "Logical - Grouping - 3rd Party Cloud",
        "third party cloud": "Logical - Grouping - 3rd Party Cloud",
        "other group": "Logical - Grouping - Other Group",
        "oci component": "Logical - Components - OCI Component",
        "oracle on premises component": "Logical - Components - Oracle On-Premises Component",
        "oracle on-premises component": "Logical - Components - Oracle On-Premises Component",
        "atomic": "Logical - Components - Atomic",
        "collapsed composite": "Logical - Components - Collapsed Composite",
        "expanded composite": "Logical - Components - Expanded Composite",
    },
}

CATEGORY_HINTS = {
    "compute": {"compute", "vm", "machine", "gpu", "instance", "function", "functions", "autoscaling"},
    "storage": {"storage", "object", "bucket", "file", "block", "backup", "restore", "volume"},
    "networking": {
        "network",
        "vcn",
        "subnet",
        "gateway",
        "load",
        "balancer",
        "drg",
        "dns",
        "cdn",
        "cpe",
        "peering",
        "fastconnect",
        "vpn",
        "route",
        "firewall",
        "waf",
    },
    "database": {
        "database",
        "db",
        "warehouse",
        "data",
        "cache",
        "redis",
        "valkey",
        "postgres",
        "postgresql",
        "mysql",
        "nosql",
        "adw",
        "atp",
        "adb",
        "opensearch",
        "goldengate",
        "heatwave",
        "lakehouse",
    },
    "analytics and ai": {
        "analytics",
        "ai",
        "ml",
        "science",
        "vision",
        "speech",
        "language",
        "document",
        "forecasting",
        "generative",
    },
    "developer services": {"oke", "kubernetes", "container", "registry", "mesh", "api", "apex"},
    "identity and security": {
        "iam",
        "security",
        "vault",
        "bastion",
        "nsg",
        "ddos",
        "certificate",
        "threat",
        "cloud",
        "guard",
        "firewall",
    },
    "observability and management": {"logging", "monitoring", "audit", "apm", "alarm", "events", "workflow"},
}

EXTERNAL_TOKENS = {"external", "third", "3rd", "saas", "vendor", "partner", "non", "oci"}
ONPREM_TOKENS = {"onprem", "on", "prem", "datacenter", "data", "center", "legacy"}
USER_TOKENS = {"user", "users", "admin", "operator", "developer"}


def load_catalog(catalog_path: Path | None = None) -> list[dict[str, Any]]:
    default_library, default_json, _ = default_paths()
    catalog_path = catalog_path or default_json

    if catalog_path.exists():
        return json.loads(catalog_path.read_text())

    return build_catalog(default_library)


def build_indexes(catalog: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    title_index: dict[str, dict[str, Any]] = {}
    variant_index: dict[str, dict[str, Any]] = {}

    for entry in catalog:
        title_index[entry["title"]] = entry
        variants = {
            entry["normalized_title"],
            entry["normalized_name"],
            *entry.get("acronyms", []),
        }
        for variant in variants:
            if variant and variant not in variant_index:
                variant_index[variant] = entry

    return title_index, variant_index


def infer_category_hint(query_tokens: set[str]) -> str | None:
    for category, hints in CATEGORY_HINTS.items():
        if query_tokens & hints:
            return category
    return None


def infer_logical_generic_icon(query_tokens: set[str]) -> str:
    if query_tokens & EXTERNAL_TOKENS:
        return LOGICAL_GENERIC_ICONS["external"]
    if query_tokens & ONPREM_TOKENS:
        return LOGICAL_GENERIC_ICONS["onprem"]
    return LOGICAL_GENERIC_ICONS["oci"]


def infer_placeholder_shape(
    query_tokens: set[str],
    category_hint: str | None = None,
    closest_entry: dict[str, Any] | None = None,
) -> str:
    normalized_category = category_hint
    if not normalized_category and closest_entry:
        normalized_category = normalize(str(closest_entry.get("category", "")))

    if query_tokens & USER_TOKENS:
        return PLACEHOLDER_SHAPES["user"]
    if normalized_category in {"networking", "identity and security"}:
        return PLACEHOLDER_SHAPES["network"]
    if normalized_category in {"database", "storage"}:
        return PLACEHOLDER_SHAPES["data"]
    if query_tokens & (CATEGORY_HINTS["networking"] | CATEGORY_HINTS["identity and security"]):
        return PLACEHOLDER_SHAPES["network"]
    if query_tokens & (CATEGORY_HINTS["database"] | CATEGORY_HINTS["storage"]):
        return PLACEHOLDER_SHAPES["data"]
    if query_tokens & EXTERNAL_TOKENS:
        return PLACEHOLDER_SHAPES["external"]
    return PLACEHOLDER_SHAPES["app"]


def score_candidate(query_norm: str, query_tokens: set[str], entry: dict[str, Any], category_hint: str | None) -> float:
    title_tokens = set(entry.get("tokens", []))
    overlap = len(query_tokens & title_tokens) / max(len(query_tokens), 1)
    containment = 1.0 if query_norm in entry["normalized_title"] or entry["normalized_name"] in query_norm else 0.0
    sequence = SequenceMatcher(None, query_norm, entry["normalized_name"]).ratio()
    category_bonus = 0.10 if category_hint and normalize(entry["category"]) == category_hint else 0.0
    source_bonus = 0.03 if entry["source"] != "oci-library.xml" else 0.0
    return min(1.0, (0.42 * overlap) + (0.38 * sequence) + (0.10 * containment) + category_bonus + source_bonus)


def resolve_icon(query: str, page: str = "physical", catalog_path: Path | None = None) -> dict[str, Any]:
    catalog = load_catalog(catalog_path)
    title_index, variant_index = build_indexes(catalog)

    query_norm = normalize(query)
    query_tokens = set(tokenize(query))
    category_hint = infer_category_hint(query_tokens)

    page_override_title = PAGE_OVERRIDES.get(page, {}).get(query_norm)
    if page_override_title and page_override_title in title_index:
        entry = title_index[page_override_title]
        return {
            "query": query,
            "page": page,
            "resolution": "alias",
            "icon_title": entry["title"],
            "category": entry["category"],
            "source": entry["source"],
            "confidence": 1.0,
            "reason": f"Mapped the query to the page-specific Oracle grouping or connector shape for {page} diagrams.",
        }

    direct_match = variant_index.get(query_norm)
    if direct_match:
        return {
            "query": query,
            "page": page,
            "resolution": "direct",
            "icon_title": direct_match["title"],
            "category": direct_match["category"],
            "source": direct_match["source"],
            "confidence": 1.0,
            "reason": "Matched the query directly to an official icon title, name, or acronym.",
        }

    alias_target = COMMON_ALIASES.get(query_norm)
    if alias_target and alias_target in title_index:
        entry = title_index[alias_target]
        return {
            "query": query,
            "page": page,
            "resolution": "alias",
            "icon_title": entry["title"],
            "category": entry["category"],
            "source": entry["source"],
            "confidence": 1.0,
            "reason": f"Mapped the query through a trusted alias: {query_norm}.",
        }

    if page == "physical":
        fallback_target = PHYSICAL_APPROVED_FALLBACKS.get(query_norm)
        if fallback_target and fallback_target in title_index:
            entry = title_index[fallback_target]
            return {
                "query": query,
                "page": page,
                "resolution": "closest-official-fallback",
                "icon_title": entry["title"],
                "category": entry["category"],
                "source": entry["source"],
                "confidence": 0.82,
                "reason": (
                    "No direct official icon exists in the bundled physical catalog for this service. "
                    "Used the approved closest official fallback icon and disclose it as a fallback in the mapping table."
                ),
            }

    scored = [
        (score_candidate(query_norm, query_tokens, entry, category_hint), entry)
        for entry in catalog
    ]
    best_score, best_entry = max(scored, key=lambda item: item[0])

    if best_score >= 0.72 and page != "physical":
        return {
            "query": query,
            "page": page,
            "resolution": "closest",
            "icon_title": best_entry["title"],
            "category": best_entry["category"],
            "source": best_entry["source"],
            "confidence": round(best_score, 3),
            "reason": "No direct icon match was found. This is the closest official icon with acceptable similarity.",
        }

    if page == "logical":
        generic_title = infer_logical_generic_icon(query_tokens)
        entry = title_index[generic_title]
        return {
            "query": query,
            "page": page,
            "resolution": "generic",
            "icon_title": entry["title"],
            "category": entry["category"],
            "source": entry["source"],
            "confidence": round(best_score, 3),
            "reason": "No direct or honest closest icon was found. Used an official generic logical component instead.",
        }

    placeholder_shape = infer_placeholder_shape(
        query_tokens,
        category_hint=category_hint,
        closest_entry=best_entry if best_score >= 0.45 else None,
    )
    closest_official_icon = best_entry["title"] if best_score >= 0.45 else None
    reason = "No direct OCI icon was found. Use the closest similar placeholder shape and document it in the mapping table."
    if best_score >= 0.72:
        reason = (
            "No direct OCI icon was found for this physical component. "
            "Use the closest similar placeholder shape instead of rendering a potentially misleading OCI service icon."
        )
    return {
        "query": query,
        "page": page,
        "resolution": "placeholder",
        "icon_title": None,
        "category": None,
        "source": None,
        "confidence": round(best_score, 3),
        "placeholder_shape": placeholder_shape,
        "label_template": f"PLACEHOLDER: {query}",
        "closest_official_icon": closest_official_icon,
        "reason": reason,
    }


def search_catalog(term: str, catalog_path: Path | None = None) -> list[dict[str, Any]]:
    catalog = load_catalog(catalog_path)
    needle = normalize(term)
    matches = [
        entry
        for entry in catalog
        if needle in entry["normalized_title"] or needle in entry["normalized_name"]
    ]
    return sorted(matches, key=lambda entry: (entry["category"], entry["name"], entry["title"]))


def main() -> None:
    _, default_json, _ = default_paths()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", default=[], help="Component name to resolve. Repeat as needed.")
    parser.add_argument("--page", choices=["logical", "physical"], default="physical", help="Diagram page type.")
    parser.add_argument("--catalog", type=Path, default=default_json, help="Path to icon-catalog.json")
    parser.add_argument("--search", help="Browse the catalog instead of resolving a component.")
    parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")
    args = parser.parse_args()

    if args.search:
        matches = search_catalog(args.search, args.catalog)
        payload: Any = matches
    else:
        if not args.query:
            parser.error("Provide at least one --query or use --search.")
        payload = [resolve_icon(query, page=args.page, catalog_path=args.catalog) for query in args.query]

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return

    if args.search:
        for entry in payload:
            print(f"{entry['title']} [{entry['source']}]")
        return

    for result in payload:
        print(f"Query: {result['query']}")
        print(f"Resolution: {result['resolution']}")
        if result["icon_title"]:
            print(f"Icon: {result['icon_title']}")
        if result.get("placeholder_shape"):
            print(f"Placeholder: {result['placeholder_shape']}")
        print(f"Reason: {result['reason']}")
        print()


if __name__ == "__main__":
    main()
