#!/usr/bin/env python3
"""Select the closest bundled OCI reference architecture for a new request."""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import html
import json
from pathlib import Path
import re
from typing import Any
import urllib.parse
import xml.etree.ElementTree as ET
import zlib

from build_icon_catalog import normalize, tokenize

SKILL_DIR = Path(__file__).resolve().parents[1]
REFERENCE_DIR = SKILL_DIR / "assets" / "reference-architectures" / "oracle"

STOPWORDS = {
    "a",
    "an",
    "and",
    "app",
    "application",
    "applications",
    "architecture",
    "at",
    "by",
    "cloud",
    "data",
    "diagram",
    "flow",
    "for",
    "in",
    "is",
    "of",
    "on",
    "oracle",
    "secure",
    "service",
    "services",
    "the",
    "this",
    "to",
    "use",
    "using",
    "web",
    "with",
}

TAG_RULES = {
    "api-gateway": [{"api", "gateway"}],
    "argocd": [{"argocd"}, {"argo", "cd"}, {"gitops"}],
    "autonomous-database": [{"autonomous", "database"}, {"adb"}],
    "azure": [{"azure"}],
    "bastion": [{"bastion"}],
    "chatbot": [{"chatbot"}, {"bot"}],
    "data-flow": [{"data", "flow"}],
    "dicom": [{"dicom"}, {"dicomweb"}, {"orthanc"}, {"pacs"}, {"vna"}, {"medical", "imaging"}],
    "dr": [{"dr"}, {"disaster", "recovery"}, {"failover"}],
    "exadata": [{"exadata"}, {"exadb"}],
    "genai": [{"genai"}, {"generative", "ai"}, {"llm"}],
    "hub-spoke": [{"hub", "spoke"}, {"hub", "and", "spoke"}, {"lpg"}, {"peering"}],
    "identity": [{"openid"}, {"open", "id"}, {"oauth"}, {"oauth2"}, {"identity"}],
    "integration": [{"integration"}],
    "migration": [{"migration"}, {"migrate"}],
    "multi-region": [{"multi", "region"}, {"multi-region"}, {"secondary", "region"}],
    "multi-tenant": [{"multi", "tenant"}, {"multi-tenant"}, {"tenant"}],
    "mushop": [{"mushop"}],
    "oauth": [{"oauth"}, {"oauth2"}],
    "oke": [{"oke"}, {"kubernetes"}, {"k8s"}],
    "opensearch": [{"opensearch"}],
    "postgresql": [{"postgres"}, {"postgresql"}],
    "redis": [{"redis"}, {"valkey"}],
    "vision": [{"vision"}],
    "weblogic": [{"weblogic"}, {"wls"}],
}

FOCUS_TAG_WEIGHTS = {
    "oke": 32,
    "hub-spoke": 30,
    "api-gateway": 26,
    "multi-tenant": 24,
    "mushop": 24,
    "bastion": 22,
    "genai": 20,
    "argocd": 18,
    "chatbot": 18,
    "dicom": 18,
    "weblogic": 18,
    "vision": 18,
    "integration": 18,
    "autonomous-database": 18,
    "exadata": 18,
    "postgresql": 12,
    "opensearch": 12,
    "redis": 10,
}

CONTEXT_TAG_WEIGHTS = {
    "dr": 12,
    "multi-region": 10,
    "identity": 10,
    "oauth": 8,
    "migration": 8,
    "data-flow": 6,
    "azure": 6,
}

NETWORK_HINT_TOKENS = {
    "cidr",
    "compute",
    "drg",
    "gateway",
    "igw",
    "internet",
    "kubernetes",
    "lb",
    "lpg",
    "nat",
    "network",
    "oke",
    "peering",
    "private",
    "public",
    "route",
    "routing",
    "security",
    "subnet",
    "subnets",
    "vcn",
    "vpn",
}

FLOW_HINT_TOKENS = {"data", "flow", "request", "sequence", "step", "steps", "traffic"}
LOGICAL_HINT_TOKENS = {"conceptual", "logical"}
PHYSICAL_HINT_TOKENS = NETWORK_HINT_TOKENS | {"availability", "domain", "fault", "physical", "region"}

REFERENCE_HINTS: dict[str, dict[str, Any]] = {
    "ai-llm-workflow-architecture.drawio": {
        "add_tags": {"genai"},
        "keywords": {
            "agents",
            "apex",
            "assistant",
            "data",
            "science",
            "devops",
            "digital",
            "embedding",
            "genai",
            "gpu",
            "llm",
            "object",
            "storage",
            "rag",
            "search",
            "speech",
            "vector",
            "workflow",
        },
        "traits": {"ai", "architecture"},
        "view_kind": "architecture",
    },
    "architecture-ai-vision.drawio": {
        "add_tags": {"vision"},
        "remove_tags": {"identity"},
        "keywords": {"events", "functions", "image", "object", "storage", "vision"},
        "traits": {"ai", "architecture", "network", "physical"},
        "view_kind": "architecture",
    },
    "architecture-use-bastion-service.drawio": {
        "add_tags": {"bastion"},
        "keywords": {"access", "admin", "bastion", "compute", "jenkins", "jump", "private", "ssh", "weblogic"},
        "traits": {"architecture", "network", "physical", "security"},
        "view_kind": "architecture",
    },
    "autonomous-database-db-at-azure-diagram.drawio": {
        "add_tags": {"autonomous-database", "azure"},
        "keywords": {"adb", "autonomous", "azure", "cross-cloud", "database"},
        "traits": {"architecture", "cross-cloud"},
        "view_kind": "architecture",
    },
    "cloudany-migration-dr-logical-arch.drawio": {
        "add_tags": {"dr", "migration"},
        "keywords": {"cutover", "disaster", "failover", "logical", "migration", "recovery", "standby"},
        "traits": {"dr", "logical", "migration"},
        "view_kind": "logical",
    },
    "deploy-ai-chatbot-arch.drawio": {
        "add_tags": {"chatbot", "genai", "identity"},
        "keywords": {"assistant", "bot", "chat", "chatbot", "genai", "identity", "visual"},
        "traits": {"ai", "architecture"},
        "view_kind": "architecture",
    },
    "exadb-dr-on-db-at-azure.drawio": {
        "add_tags": {"azure", "dr", "exadata"},
        "remove_tags": {"autonomous-database", "hub-spoke"},
        "keywords": {
            "active",
            "aks",
            "azure",
            "backup",
            "database",
            "data",
            "guard",
            "disaster",
            "exadata",
            "failover",
            "hub",
            "recovery",
            "standby",
            "vault",
        },
        "traits": {"architecture", "cross-cloud", "dr"},
        "view_kind": "architecture",
    },
    "hub-spoke-oci.drawio": {
        "add_tags": {"hub-spoke"},
        "keywords": {
            "azure",
            "drg",
            "edge",
            "fastconnect",
            "hospital",
            "hub",
            "hybrid",
            "internet",
            "lpg",
            "medical",
            "on-premises",
            "peering",
            "spoke",
            "transit",
            "vpn",
        },
        "traits": {"architecture", "hybrid", "network", "physical"},
        "view_kind": "architecture",
    },
    "multi-tenant-app-oci.drawio": {
        "add_tags": {"multi-tenant"},
        "keywords": {"isolation", "saas", "shared", "tenant", "tenancy"},
        "traits": {"application-platform", "architecture", "platform"},
        "view_kind": "architecture",
    },
    "mushop-infrastructure.drawio": {
        "add_tags": {"mushop", "oke"},
        "keywords": {
            "argocd",
            "cart",
            "commerce",
            "ecommerce",
            "gitops",
            "ingress",
            "marketplace",
            "microservice",
            "mushop",
            "oke",
            "opensearch",
            "payment",
            "postgresql",
            "redis",
            "search",
            "valkey",
            "weblogic",
        },
        "traits": {"application-platform", "architecture", "network", "oke", "physical"},
        "view_kind": "architecture",
    },
    "oke-architecture-diagram.drawio": {
        "add_tags": {"oke"},
        "keywords": {
            "argocd",
            "dicom",
            "fastconnect",
            "frontend",
            "gitops",
            "ingress",
            "jenkins",
            "kubernetes",
            "lb",
            "marketplace",
            "microservice",
            "oke",
            "opensearch",
            "orthanc",
            "pacs",
            "postgresql",
            "private",
            "public",
            "redis",
            "registry",
            "subnet",
            "valkey",
            "vcn",
            "weblogic",
            "wls",
        },
        "traits": {"application-platform", "architecture", "network", "oke", "physical"},
        "view_kind": "architecture",
    },
    "oracle-integration-rest-oauth-diagram.drawio": {
        "add_tags": {"identity", "integration", "oauth"},
        "keywords": {"api", "integration", "oauth", "rest", "token"},
        "traits": {"architecture", "integration"},
        "view_kind": "architecture",
    },
    "secure-web-applications-oci-api-gateway-open-id-architecture.drawio": {
        "add_tags": {"api-gateway", "identity", "oauth"},
        "keywords": {"api", "gateway", "idp", "oauth", "oidc", "openid", "waf", "web"},
        "traits": {"architecture", "network", "physical", "security"},
        "view_kind": "architecture",
    },
    "secure-web-applications-oci-api-gateway-open-id-data-flow.drawio": {
        "add_tags": {"api-gateway", "data-flow", "identity", "oauth"},
        "keywords": {"api", "flow", "gateway", "oauth", "oidc", "openid", "sequence", "traffic"},
        "traits": {"data-flow", "security"},
        "view_kind": "data-flow",
    },
}

SOURCE_ARCHIVES = {
    "ai-llm-workflow-architecture.drawio": ["ai-llm-workflow-architecture-oracle.zip"],
    "architecture-ai-vision.drawio": ["architecture-ai-vision-oracle.zip"],
    "architecture-use-bastion-service.drawio": ["architecture-use-bastion-service-oracle.zip"],
    "autonomous-database-db-at-azure-diagram.drawio": ["autonomous-database-db-azure-diagram-oracle.zip"],
    "cloudany-migration-dr-logical-arch.drawio": ["cloudany-migration-dr-logical-arch-oracle.zip"],
    "deploy-ai-chatbot-arch.drawio": ["deploy-ai-chatbot-arch.zip"],
    "exadb-dr-on-db-at-azure.drawio": ["exadb-dr-db-azure-oracle.zip"],
    "hub-spoke-oci.drawio": ["hub-and-spoke-oci.zip"],
    "multi-tenant-app-oci.drawio": ["multi-tenant-app-oci-oracle.zip"],
    "mushop-infrastructure.drawio": ["mushop-infrastructure-oracle.zip"],
    "oke-architecture-diagram.drawio": ["oke-architecture-diagram-oracle.zip"],
    "oracle-integration-rest-oauth-diagram.drawio": ["oracle-integration-rest-oauth-diagram-oracle.zip"],
    "secure-web-applications-oci-api-gateway-open-id-architecture.drawio": [
        "secure-web-applications-oci-api-gateway-open-id-architecture.zip",
        "secure-web-applications-oci-api-gateway-open-id-architecture (1).zip",
    ],
    "secure-web-applications-oci-api-gateway-open-id-data-flow.drawio": [
        "secure-web-applications-oci-api-gateway-open-id-data-flow.zip"
    ],
}


@dataclass
class QueryProfile:
    text: str
    normalized: str
    tokens: set[str]
    tags: set[str]
    view_kind: str
    needs_network: bool
    wants_physical: bool


@dataclass
class ReferenceArchitecture:
    title: str
    path: Path
    page_names: list[str]
    sample_labels: list[str]
    filename_tokens: set[str]
    page_tokens: set[str]
    label_tokens: set[str]
    hint_tokens: set[str]
    tags: set[str]
    traits: set[str]
    view_kind: str
    source_archives: list[str]


def decode_diagram(payload: str) -> str:
    text = (payload or "").strip()
    if text.startswith("<mxGraphModel"):
        return text
    return urllib.parse.unquote(zlib.decompress(base64.b64decode(text), -15).decode("utf-8"))


def strip_html(value: str) -> str:
    cleaned = html.unescape(value or "").replace("\xa0", " ")
    cleaned = re.sub(r"<br\s*/?>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return " ".join(cleaned.split())


def significant_tokens(text: str) -> set[str]:
    return {token for token in tokenize(text) if token not in STOPWORDS and len(token) > 1}


def canonical_tag(tag: str) -> str:
    return normalize(tag).replace(" ", "-")


def infer_tags(*text_parts: str) -> set[str]:
    joined = normalize(" ".join(text_parts))
    tokens = significant_tokens(joined)
    tags: set[str] = set()

    for tag, alternatives in TAG_RULES.items():
        for alternative in alternatives:
            normalized_alternative = {normalize(term) for term in alternative if normalize(term)}
            if normalized_alternative <= tokens:
                tags.add(tag)
                break

    if "dr" in tokens and "multi" in tokens and "region" in tokens:
        tags.add("multi-region")
    if "api" in tokens and "gateway" in tokens and "oauth" in tokens:
        tags.add("identity")
        tags.add("oauth")
    if "chat" in tokens and "bot" in tokens:
        tags.add("chatbot")
    return tags


def infer_view_kind(*text_parts: str) -> str:
    joined = normalize(" ".join(text_parts))
    tokens = significant_tokens(joined)
    if "logical" in tokens:
        return "logical"
    if "data flow" in joined or {"data", "flow"} <= tokens or {"traffic", "flow"} <= tokens:
        return "data-flow"
    return "architecture"


def read_drawio_pages(drawio_path: Path) -> list[tuple[str, ET.Element]]:
    mxfile = ET.fromstring(drawio_path.read_text())
    pages: list[tuple[str, ET.Element]] = []
    for diagram in mxfile.findall("diagram"):
        page_name = diagram.attrib.get("name", "")
        inline_model = diagram.find("mxGraphModel")
        if inline_model is not None:
            page_model = ET.fromstring(ET.tostring(inline_model, encoding="unicode"))
        else:
            page_model = ET.fromstring(decode_diagram(diagram.text or ""))
        pages.append((page_name, page_model))
    return pages


def summarize_reference(drawio_path: Path) -> ReferenceArchitecture:
    page_names: list[str] = []
    labels: list[str] = []
    seen_labels: set[str] = set()

    for page_name, model in read_drawio_pages(drawio_path):
        if page_name:
            page_names.append(page_name)
        for cell in model.iterfind(".//mxCell"):
            plain = strip_html(cell.attrib.get("value", ""))
            if not plain or plain in seen_labels:
                continue
            seen_labels.add(plain)
            labels.append(plain)

    hint = REFERENCE_HINTS.get(drawio_path.name, {})
    title = drawio_path.stem.replace("-", " ")
    filename_tokens = significant_tokens(drawio_path.stem)
    page_tokens = significant_tokens(" ".join(page_names))
    label_tokens = significant_tokens(" ".join(labels[:200]))
    tags = infer_tags(drawio_path.stem, " ".join(page_names), " ".join(labels[:200]))
    tags |= {canonical_tag(tag) for tag in hint.get("add_tags", set()) if canonical_tag(tag)}
    tags -= {canonical_tag(tag) for tag in hint.get("remove_tags", set()) if canonical_tag(tag)}
    hint_tokens = significant_tokens(" ".join(hint.get("keywords", [])))
    traits = {normalize(trait).replace(" ", "-") for trait in hint.get("traits", set()) if normalize(trait)}
    view_kind = hint.get("view_kind") or infer_view_kind(drawio_path.stem, " ".join(page_names))

    return ReferenceArchitecture(
        title=title,
        path=drawio_path,
        page_names=page_names,
        sample_labels=labels[:12],
        filename_tokens=filename_tokens,
        page_tokens=page_tokens,
        label_tokens=label_tokens,
        hint_tokens=hint_tokens,
        tags=tags,
        traits=traits,
        view_kind=view_kind,
        source_archives=SOURCE_ARCHIVES.get(drawio_path.name, []),
    )


def build_reference_catalog(reference_dir: Path | None = None) -> list[ReferenceArchitecture]:
    root = reference_dir or REFERENCE_DIR
    references = [summarize_reference(path) for path in sorted(root.glob("*.drawio"))]
    return sorted(references, key=lambda ref: ref.title)


def expand_query_tags(query: str) -> tuple[set[str], set[str]]:
    tokens = significant_tokens(query)
    tags = infer_tags(query)

    if "kubernetes" in tokens or "k8s" in tokens:
        tokens.add("oke")
        tags.add("oke")
    if {"argo", "cd"} <= tokens or "argocd" in tokens or "gitops" in tokens:
        tokens.update({"argocd", "gitops", "oke"})
        tags.update({"argocd", "oke"})
    if "weblogic" in tokens or "wls" in tokens:
        tokens.update({"weblogic", "wls", "oke"})
        tags.update({"weblogic", "oke"})
    if {"dicom", "orthanc", "pacs", "vna"} & tokens or "dicomweb" in tokens:
        tokens.update({"dicom", "medical", "imaging", "oke"})
        tags.update({"dicom", "oke"})
    if "openid" in tokens or ("open" in tokens and "id" in tokens) or "oidc" in tokens:
        tokens.update({"oauth", "identity"})
        tags.update({"identity", "oauth"})
    if "dr" in tokens or ("disaster" in tokens and "recovery" in tokens):
        tokens.update({"failover", "secondary", "region"})
        tags.add("dr")
    if "hub" in tokens and "spoke" in tokens:
        tags.add("hub-spoke")
    if "tenant" in tokens:
        tags.add("multi-tenant")
    if "chatbot" in tokens or ("chat" in tokens and "bot" in tokens):
        tags.add("chatbot")
    if "vision" in tokens:
        tags.add("vision")
    if "azure" in tokens:
        tags.add("azure")
    if "aks" in tokens:
        tokens.add("azure")
        tags.update({"azure", "dr"})
    if "postgres" in tokens or "postgresql" in tokens:
        tokens.update({"postgres", "postgresql"})
        tags.add("postgresql")
    if "redis" in tokens or "valkey" in tokens:
        tokens.update({"redis", "valkey"})
        tags.add("redis")
    if "opensearch" in tokens:
        tags.add("opensearch")
    if "marketplace" in tokens:
        tokens.add("oke")
        tags.add("oke")
    if {"postgres", "redis", "opensearch"} <= tokens or {"postgresql", "redis", "opensearch"} <= tokens:
        tokens.add("oke")
        tags.add("oke")
    if "saas" in tokens:
        tokens.add("tenant")
    return tokens, tags


def build_query_profile(query: str) -> QueryProfile:
    tokens, tags = expand_query_tags(query)
    normalized = normalize(query)

    if "logical" in tokens:
        view_kind = "logical"
    elif "data flow" in normalized or {"data", "flow"} <= tokens or {"traffic", "flow"} <= tokens:
        view_kind = "data-flow"
    else:
        view_kind = "architecture"

    needs_network = bool(tokens & NETWORK_HINT_TOKENS) or bool(tags & {"hub-spoke", "oke"})
    wants_physical = bool(tokens & PHYSICAL_HINT_TOKENS) or view_kind == "architecture"

    return QueryProfile(
        text=query,
        normalized=normalized,
        tokens=tokens,
        tags=tags,
        view_kind=view_kind,
        needs_network=needs_network,
        wants_physical=wants_physical,
    )


def score_view(reference: ReferenceArchitecture, profile: QueryProfile) -> int:
    if profile.view_kind == reference.view_kind:
        return 8
    if profile.view_kind == "architecture" and reference.view_kind == "logical":
        return -10
    if profile.view_kind == "architecture" and reference.view_kind == "data-flow":
        return -6
    if profile.view_kind == "logical" and reference.view_kind != "logical":
        return -4
    if profile.view_kind == "data-flow" and reference.view_kind != "data-flow":
        return -4
    return 0


def score_reference(reference: ReferenceArchitecture, query: str | QueryProfile) -> dict[str, Any]:
    profile = query if isinstance(query, QueryProfile) else build_query_profile(query)

    matched_focus_tags = sorted(tag for tag in profile.tags & reference.tags if tag in FOCUS_TAG_WEIGHTS)
    matched_context_tags = sorted(tag for tag in profile.tags & reference.tags if tag in CONTEXT_TAG_WEIGHTS)
    matched_filename = sorted(profile.tokens & reference.filename_tokens)
    matched_pages = sorted(profile.tokens & reference.page_tokens)
    matched_labels = sorted(profile.tokens & reference.label_tokens)
    matched_hints = sorted(profile.tokens & reference.hint_tokens)

    focus_score = sum(FOCUS_TAG_WEIGHTS[tag] for tag in matched_focus_tags)
    context_score = sum(CONTEXT_TAG_WEIGHTS[tag] for tag in matched_context_tags)
    token_score = (
        len(matched_filename) * 4
        + len(matched_pages) * 3
        + min(len(matched_labels), 10)
        + min(len(matched_hints) * 2, 14)
    )

    fit_score = 0
    if profile.needs_network and "network" in reference.traits:
        fit_score += 8
    if profile.wants_physical and "physical" in reference.traits:
        fit_score += 4
    if "genai" in profile.tags and "ai" in reference.traits:
        fit_score += 14
    if {"argocd", "dicom", "opensearch", "postgresql", "redis", "weblogic"} & profile.tags and "oke" in reference.traits:
        fit_score += 6
    if "dicom" in profile.tags and "hybrid" in reference.traits:
        fit_score += 4
    if "saas" in profile.tokens and {"application-platform", "platform"} & reference.traits:
        fit_score += 3
    if matched_focus_tags and matched_context_tags:
        fit_score += 4
    if len(matched_focus_tags) > 1:
        fit_score += 4 * (len(matched_focus_tags) - 1)

    view_score = score_view(reference, profile)
    penalty_score = 0
    if "azure" in reference.tags and "azure" not in profile.tags:
        penalty_score -= 6
    if "cross-cloud" in reference.traits and not ({"aws", "azure", "cross", "gcp", "hybrid"} & profile.tokens):
        penalty_score -= 4
    if "exadata" in reference.tags and not ({"database", "db", "exadata"} & profile.tokens):
        penalty_score -= 4
    if "autonomous-database" in reference.tags and not ({"adb", "autonomous", "database", "db"} & profile.tokens):
        penalty_score -= 4

    score = focus_score + context_score + token_score + fit_score + view_score + penalty_score

    return {
        "title": reference.title,
        "path": str(reference.path),
        "page_names": reference.page_names,
        "sample_labels": reference.sample_labels,
        "tags": sorted(reference.tags),
        "traits": sorted(reference.traits),
        "view_kind": reference.view_kind,
        "source_archives": reference.source_archives,
        "score": score,
        "score_breakdown": {
            "focus": focus_score,
            "context": context_score,
            "tokens": token_score,
            "fit": fit_score,
            "view": view_score,
            "penalty": penalty_score,
        },
        "matched_tags": matched_focus_tags + matched_context_tags,
        "matched_focus_tags": matched_focus_tags,
        "matched_context_tags": matched_context_tags,
        "matched_filename_tokens": matched_filename,
        "matched_page_tokens": matched_pages,
        "matched_label_tokens": matched_labels,
        "matched_hint_tokens": matched_hints,
        "query_view_kind": profile.view_kind,
    }


def rank_references(query: str, reference_dir: Path | None = None) -> list[dict[str, Any]]:
    profile = build_query_profile(query)
    scored = [score_reference(reference, profile) for reference in build_reference_catalog(reference_dir)]
    ranked = sorted(
        scored,
        key=lambda item: (
            -item["score"],
            -len(item["matched_focus_tags"]),
            -len(item["matched_context_tags"]),
            -len(item["matched_hint_tokens"]),
            item["title"],
        ),
    )
    return ranked


def select_reference_bundle(
    query: str,
    reference_dir: Path | None = None,
    max_supporting: int = 2,
) -> dict[str, Any]:
    ranked = rank_references(query, reference_dir)
    if not ranked:
        return {
            "query": query,
            "query_view_kind": build_query_profile(query).view_kind,
            "primary": None,
            "supplemental": [],
            "uncovered_tags": [],
        }

    profile = build_query_profile(query)
    primary = ranked[0]
    covered_tags = set(primary["matched_tags"])
    covered_hints = set(primary["matched_hint_tokens"])
    remaining = ranked[1:]
    supplemental: list[dict[str, Any]] = []

    while remaining and len(supplemental) < max_supporting:
        best_index: int | None = None
        best_gain = 0
        best_candidate: dict[str, Any] | None = None
        best_new_tags: set[str] = set()
        best_new_hints: set[str] = set()

        for index, candidate in enumerate(remaining):
            new_tags = set(candidate["matched_tags"]) - covered_tags
            new_hints = set(candidate["matched_hint_tokens"]) - covered_hints
            gain = sum(FOCUS_TAG_WEIGHTS.get(tag, CONTEXT_TAG_WEIGHTS.get(tag, 0)) for tag in new_tags)
            gain += min(len(new_hints) * 2, 6)
            if candidate["view_kind"] == "logical" and profile.view_kind == "architecture" and not new_tags:
                gain -= 2
            if "azure" in candidate["tags"] and "azure" not in profile.tags:
                gain -= 6
            if "cross-cloud" in candidate["traits"] and not ({"aws", "azure", "cross", "gcp", "hybrid"} & profile.tokens):
                gain -= 4
            if "exadata" in candidate["tags"] and not ({"database", "db", "exadata"} & profile.tokens):
                gain -= 4
            if "autonomous-database" in candidate["tags"] and not ({"adb", "autonomous", "database", "db"} & profile.tokens):
                gain -= 4

            if gain > best_gain or (
                gain == best_gain
                and best_candidate is not None
                and candidate["score"] > best_candidate["score"]
            ):
                best_index = index
                best_gain = gain
                best_candidate = candidate
                best_new_tags = new_tags
                best_new_hints = new_hints

        if best_index is None or best_candidate is None or best_gain <= 0:
            break

        enriched = dict(best_candidate)
        enriched["coverage_gain"] = best_gain
        enriched["new_tag_coverage"] = sorted(best_new_tags)
        enriched["new_hint_coverage"] = sorted(best_new_hints)
        supplemental.append(enriched)
        covered_tags |= best_new_tags
        covered_hints |= best_new_hints
        remaining.pop(best_index)

    uncovered_tags = sorted(profile.tags - covered_tags)
    return {
        "query": query,
        "query_view_kind": profile.view_kind,
        "primary": primary,
        "supplemental": supplemental,
        "uncovered_tags": uncovered_tags,
    }


def to_jsonable_catalog(references: list[ReferenceArchitecture]) -> list[dict[str, Any]]:
    return [
        {
            "title": reference.title,
            "path": str(reference.path),
            "page_names": reference.page_names,
            "sample_labels": reference.sample_labels,
            "tags": sorted(reference.tags),
            "traits": sorted(reference.traits),
            "view_kind": reference.view_kind,
            "source_archives": reference.source_archives,
        }
        for reference in references
    ]


def print_ranked_item(index: int, item: dict[str, Any]) -> None:
    print(f"{index}. {Path(item['path']).name}")
    print(f"   score: {item['score']}")
    print(f"   path: {item['path']}")
    print(f"   view: {item['view_kind']}")
    if item["tags"]:
        print(f"   tags: {', '.join(item['tags'])}")
    if item["traits"]:
        print(f"   traits: {', '.join(item['traits'])}")
    matched = (
        item["matched_focus_tags"]
        + item["matched_context_tags"]
        + item["matched_filename_tokens"]
        + item["matched_page_tokens"]
    )
    if matched:
        print(f"   matched: {', '.join(dict.fromkeys(matched))}")
    if item["matched_hint_tokens"]:
        print(f"   hint matches: {', '.join(item['matched_hint_tokens'])}")
    if item["page_names"]:
        print(f"   pages: {', '.join(item['page_names'][:4])}")
    if item["sample_labels"]:
        print(f"   sample labels: {', '.join(item['sample_labels'][:4])}")
    if item["source_archives"]:
        print(f"   source archives: {', '.join(item['source_archives'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", help="Architecture description to match against the bundled references.")
    parser.add_argument("--top", type=int, default=5, help="How many matches to print.")
    parser.add_argument("--reference-dir", type=Path, default=REFERENCE_DIR, help="Reference draw.io directory.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable text.")
    parser.add_argument(
        "--bundle",
        action="store_true",
        help="Recommend one primary reference plus supporting references for mixed requests.",
    )
    parser.add_argument(
        "--catalog",
        action="store_true",
        help="Print the discovered reference catalog instead of ranking a query.",
    )
    args = parser.parse_args()

    if args.catalog:
        catalog = to_jsonable_catalog(build_reference_catalog(args.reference_dir))
        print(json.dumps(catalog, indent=2))
        return

    if not args.query:
        raise SystemExit("--query is required unless --catalog is used.")

    if args.bundle:
        bundle = select_reference_bundle(args.query, args.reference_dir)
        if args.json:
            print(json.dumps(bundle, indent=2))
            return

        print("Primary reference:")
        if bundle["primary"] is not None:
            print_ranked_item(1, bundle["primary"])
        if bundle["supplemental"]:
            print("")
            print("Supporting references:")
            for index, item in enumerate(bundle["supplemental"], start=1):
                print_ranked_item(index, item)
                if item["new_tag_coverage"] or item["new_hint_coverage"]:
                    coverage_notes = item["new_tag_coverage"] + item["new_hint_coverage"]
                    print(f"   coverage gain: {', '.join(coverage_notes)}")
                if index != len(bundle["supplemental"]):
                    print("")
        if bundle["uncovered_tags"]:
            print("")
            print(f"Uncovered query tags: {', '.join(bundle['uncovered_tags'])}")
        return

    ranked = rank_references(args.query, args.reference_dir)[: max(args.top, 1)]
    if args.json:
        print(json.dumps(ranked, indent=2))
        return

    for index, item in enumerate(ranked, start=1):
        print_ranked_item(index, item)


if __name__ == "__main__":
    main()
