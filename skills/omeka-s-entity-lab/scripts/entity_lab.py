#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from urllib.parse import urlparse


RESOURCE_DEFAULTS = [
    "items",
    "media",
    "item_sets",
    "sites",
    "users",
    "resource_templates",
    "resource_classes",
    "vocabularies",
    "properties",
]

FIELD_HINTS = {
    "dcterms:creator": "PERSON",
    "dcterms:contributor": "PERSON",
    "dcterms:publisher": "ORG",
    "dcterms:source": "ORG",
    "dcterms:relation": "CONCEPT",
    "dcterms:isPartOf": "PLACE",
    "ric-o:location": "PLACE",
    "ric-o:hasOrHadLocation": "PLACE",
    "bibo:shortDescription": "CONCEPT",
}

HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
ALNUM_RE = re.compile(r"\w+", flags=re.UNICODE)
SPACE_RE = re.compile(r"\s+")
IDENTIFIER_CODE_RE = re.compile(r"^[A-Za-z]{1,5}\.[A-Za-z]{1,8}\.\d{2,}$")
YEAR_HINT_RE = re.compile(r"\b(1[7-9]\d{2}|20[0-2]\d)\b")

ADMIN_SEGMENT_MAP = {
    "items": "item",
    "media": "media",
    "item_sets": "item-set",
    "sites": "site",
    "users": "user",
    "resource_templates": "resource-template",
    "resource_classes": "resource-class",
    "vocabularies": "vocabulary",
    "properties": "property",
}


def detect_language(text: str) -> str:
    if HEBREW_RE.search(text):
        return "he"
    if ARABIC_RE.search(text):
        return "ar"
    if any("a" <= c.lower() <= "z" for c in text):
        return "en"
    return "und"


def normalize_surface(text: str) -> str:
    lowered = text.casefold()
    tokens = ALNUM_RE.findall(lowered)
    return SPACE_RE.sub(" ", " ".join(tokens)).strip()


def should_skip_surface(surface: str, field_key: str) -> bool:
    if not surface.strip():
        return True
    # avoid unresolved archive identifiers as first-class entities
    if field_key == "dcterms:identifier" and IDENTIFIER_CODE_RE.match(surface.strip()):
        return True
    return False


def confidence_for_value(value: str, field_key: str, from_resource_ref: bool = False) -> float:
    if from_resource_ref:
        return 0.95
    if field_key in ("o:title", "dcterms:title"):
        return 0.92
    if "alternative" in field_key.lower():
        return 0.86
    if field_key.startswith("dcterms:"):
        return 0.82
    if field_key.startswith("ric-o:"):
        return 0.80
    return 0.74


def guess_entity_type(field_key: str, resource_name: str) -> str:
    if field_key in FIELD_HINTS:
        return FIELD_HINTS[field_key]
    if resource_name == "users":
        return "PERSON"
    if field_key.endswith("location") or "location" in field_key:
        return "PLACE"
    if "organization" in field_key.lower() or "org" in field_key.lower():
        return "ORG"
    if "person" in field_key.lower() or "creator" in field_key.lower():
        return "PERSON"
    return "CONCEPT"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_manifest(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def jsonl_records(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def values_from_property_values(field_key: str, values: list) -> Iterable[Tuple[str, bool]]:
    for val in values:
        if not isinstance(val, dict):
            continue
        if val.get("type") == "literal":
            text = str(val.get("@value", "")).strip()
            if text:
                yield text, False
        elif val.get("type") == "resource":
            text = str(val.get("display_title", "")).strip()
            if text:
                yield text, True


def collect_field_values(record: dict) -> Iterable[Tuple[str, str, bool]]:
    title = str(record.get("o:title", "")).strip()
    if title:
        yield "o:title", title, False

    for key, value in record.items():
        if key.startswith("@") or key.startswith("o:"):
            continue
        if isinstance(value, list):
            for surface, from_ref in values_from_property_values(key, value):
                yield key, surface, from_ref


def stable_entity_id(language: str, normalized: str, entity_type: str) -> str:
    raw = f"{language}|{entity_type}|{normalized}"
    return "ent_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def doc_key(resource: str, record: dict) -> str:
    rid = record.get("o:id")
    return f"{resource}:{rid}"


def doc_modified(record: dict) -> str:
    modified = record.get("o:modified")
    if isinstance(modified, dict):
        value = modified.get("@value")
        if value:
            return str(value)
    created = record.get("o:created")
    if isinstance(created, dict):
        value = created.get("@value")
        if value:
            return str(value)
    return ""


def doc_source_archive(record: dict) -> str:
    sources = record.get("dcterms:source")
    if isinstance(sources, list):
        labels = []
        for s in sources:
            if isinstance(s, dict):
                title = s.get("display_title")
                if title:
                    labels.append(str(title))
        if labels:
            return " | ".join(sorted(set(labels)))
    return "unknown"


def first_uri(record: dict) -> str:
    return str(record.get("@id", ""))


def record_evidence_time(record: dict) -> str:
    # Prefer historical evidence dates from metadata fields, never ingest dates.
    for key, value in record.items():
        if key.startswith("o:") or key.startswith("@"):
            continue
        if "date" not in key.lower():
            continue
        if isinstance(value, list):
            for row in value:
                if isinstance(row, dict) and row.get("type") == "literal":
                    text = str(row.get("@value", "")).strip()
                    if text:
                        return text
    # Secondary heuristic: extract plausible historical year hints from textual literals.
    year_hints = []
    for key, value in record.items():
        if key.startswith("o:") or key.startswith("@"):
            continue
        if not isinstance(value, list):
            continue
        for row in value:
            if not isinstance(row, dict) or row.get("type") != "literal":
                continue
            text = str(row.get("@value", "")).strip()
            if not text:
                continue
            for match in YEAR_HINT_RE.findall(text):
                year_hints.append(int(match))
    if year_hints:
        year = min(year_hints)
        return str(year)
    return ""


def api_uri_to_admin_url(uri: str, resource: str, o_id) -> str:
    if not uri:
        return ""
    parsed = urlparse(uri)
    if not parsed.scheme or not parsed.netloc:
        return uri
    base_path = parsed.path
    marker = "/api/"
    idx = base_path.find(marker)
    if idx < 0:
        return uri
    prefix = base_path[:idx]
    admin_seg = ADMIN_SEGMENT_MAP.get(resource, resource.rstrip("s"))
    return f"{parsed.scheme}://{parsed.netloc}{prefix}/admin/{admin_seg}/{o_id}"


def run(args: argparse.Namespace) -> int:
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)
    ensure_dir(Path(args.manifest_path).parent)

    resources = [r.strip() for r in args.resources.split(",") if r.strip()]
    previous_manifest = load_manifest(Path(args.manifest_path))
    new_manifest: Dict[str, Dict[str, str]] = {}

    entities: Dict[str, dict] = {}
    mentions: List[dict] = []
    docs: List[dict] = []

    total_docs = 0
    changed_docs = 0

    for resource in resources:
        path = input_dir / f"{resource}.jsonl"
        for record in jsonl_records(path):
            if not isinstance(record, dict):
                continue
            total_docs += 1
            key = doc_key(resource, record)
            modified = doc_modified(record)
            title = str(record.get("o:title", "")).strip()
            uri = first_uri(record)
            admin_url = api_uri_to_admin_url(uri, resource, record.get("o:id"))
            evidence_time = record_evidence_time(record)
            source_archive = doc_source_archive(record)

            manifest_entry = {
                "modified": modified,
                "title": title,
                "uri": uri,
                "admin_url": admin_url,
                "source_archive": source_archive,
                "evidence_time": evidence_time,
            }
            new_manifest[key] = manifest_entry

            old = previous_manifest.get(key)
            should_process = args.mode == "full" or old is None or old.get("modified") != modified
            if not should_process:
                continue
            changed_docs += 1

            docs.append(
                {
                    "doc_id": key,
                    "resource": resource,
                    "o_id": record.get("o:id"),
                    "title": title,
                    "uri": uri,
                    "admin_url": admin_url,
                    "modified": modified,
                    "evidence_time": evidence_time,
                    "source_archive": source_archive,
                }
            )

            for field_key, surface, from_ref in collect_field_values(record):
                normalized = normalize_surface(surface)
                if not normalized:
                    continue
                if should_skip_surface(surface, field_key):
                    continue
                language = detect_language(surface)
                entity_type = guess_entity_type(field_key, resource)
                entity_id = stable_entity_id(language, normalized, entity_type)
                confidence = confidence_for_value(surface, field_key, from_resource_ref=from_ref)

                if entity_id not in entities:
                    entities[entity_id] = {
                        "entity_id": entity_id,
                        "label": surface,
                        "entity_type": entity_type,
                        "primary_language": language,
                        "normalized": normalized,
                        "aliases": {},
                        "languages": set(),
                        "contested_name": False,
                        "provenance_docs": set(),
                        "confidence_sum": 0.0,
                        "confidence_count": 0,
                    }
                ent = entities[entity_id]
                ent["aliases"][surface] = ent["aliases"].get(surface, 0) + 1
                ent["languages"].add(language)
                ent["provenance_docs"].add(key)
                ent["confidence_sum"] += confidence
                ent["confidence_count"] += 1
                if len(ent["aliases"]) > 1:
                    ent["contested_name"] = True

                mention_id = "m_" + hashlib.sha1(
                    f"{key}|{field_key}|{surface}|{entity_id}".encode("utf-8")
                ).hexdigest()[:16]
                mentions.append(
                    {
                        "mention_id": mention_id,
                        "doc_id": key,
                        "resource": resource,
                        "entity_id": entity_id,
                        "surface": surface,
                        "normalized": normalized,
                        "language": language,
                        "entity_type": entity_type,
                        "field_key": field_key,
                        "confidence": round(confidence, 4),
                        "uri": uri,
                        "admin_url": admin_url,
                        "modified": modified,
                        "evidence_time": evidence_time,
                        "source_archive": source_archive,
                    }
                )

    entities_out = []
    for ent in entities.values():
        confidence = ent["confidence_sum"] / max(1, ent["confidence_count"])
        entities_out.append(
            {
                "entity_id": ent["entity_id"],
                "label": ent["label"],
                "entity_type": ent["entity_type"],
                "primary_language": ent["primary_language"],
                "aliases": sorted(ent["aliases"].keys()),
                "language_set": sorted(ent["languages"]),
                "contested_name": ent["contested_name"],
                "confidence": round(confidence, 4),
                "provenance_doc_count": len(ent["provenance_docs"]),
            }
        )

    with (output_dir / "entities.jsonl").open("w", encoding="utf-8") as f:
        for row in sorted(entities_out, key=lambda x: x["entity_id"]):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (output_dir / "mentions.jsonl").open("w", encoding="utf-8") as f:
        for row in mentions:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (output_dir / "docs.jsonl").open("w", encoding="utf-8") as f:
        for row in docs:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    write_json(Path(args.manifest_path), new_manifest)
    summary = {
        "mode": args.mode,
        "resources": resources,
        "total_docs_seen": total_docs,
        "changed_docs_processed": changed_docs,
        "entities_emitted": len(entities_out),
        "mentions_emitted": len(mentions),
        "docs_emitted": len(docs),
        "manifest_path": str(Path(args.manifest_path)),
    }
    write_json(output_dir / "entity_lab_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Delta-aware multilingual entity extraction from Omeka crawl JSONL")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--manifest-path", required=True)
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    parser.add_argument("--resources", default=",".join(RESOURCE_DEFAULTS))
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
