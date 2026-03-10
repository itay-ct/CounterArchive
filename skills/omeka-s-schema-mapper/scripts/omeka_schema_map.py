#!/usr/bin/env python3
import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlencode, urlparse


def derive_api_base(admin_or_site_url: str) -> str:
    parsed = urlparse(admin_or_site_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL: {admin_or_site_url}")
    path = parsed.path.rstrip("/")
    if path.endswith("/api"):
        api_path = path
    elif "/admin/" in path:
        api_path = path.split("/admin/", 1)[0] + "/api"
    elif path.endswith("/admin"):
        api_path = path[: -len("/admin")] + "/api"
    else:
        api_path = f"{path}/api" if path else "/api"
    return f"{parsed.scheme}://{parsed.netloc}{api_path}"


def parse_headers(path: str) -> Tuple[int, Dict[str, str]]:
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    blocks = []
    cur = []
    for line in lines:
        if line.startswith("HTTP/"):
            if cur:
                blocks.append(cur)
            cur = [line.rstrip("\r")]
        elif cur and not line.strip():
            blocks.append(cur)
            cur = []
        elif cur:
            cur.append(line.rstrip("\r"))
    if cur:
        blocks.append(cur)
    if not blocks:
        raise RuntimeError("No HTTP headers found")
    last = blocks[-1]
    status = int(last[0].split()[1])
    headers: Dict[str, str] = {}
    for line in last[1:]:
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        headers[k.strip().lower()] = v.strip()
    return status, headers


def http_get_json(url: str, timeout: int) -> Tuple[int, Dict[str, str], object]:
    hdr_file = tempfile.NamedTemporaryFile(delete=False)
    hdr_file.close()
    try:
        proc = subprocess.run(
            [
                "curl",
                "-sS",
                "-L",
                "--max-time",
                str(timeout),
                "-H",
                "Accept: application/ld+json, application/json",
                "-D",
                hdr_file.name,
                url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        status, headers = parse_headers(hdr_file.name)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"curl exit {proc.returncode}")
        if status >= 400:
            snippet = proc.stdout.strip()[:500]
            raise RuntimeError(f"HTTP {status}: {snippet}")
        payload = json.loads(proc.stdout) if proc.stdout.strip() else []
        return status, headers, payload
    finally:
        try:
            os.unlink(hdr_file.name)
        except OSError:
            pass


def fetch_all(api_base: str, endpoint: str, key_identity: str, key_credential: str, per_page: int, timeout: int):
    page = 1
    records: List[dict] = []
    while True:
        query = urlencode(
            {
                "page": page,
                "per_page": per_page,
                "key_identity": key_identity,
                "key_credential": key_credential,
            }
        )
        url = f"{api_base}/{endpoint}?{query}"
        _, headers, payload = http_get_json(url, timeout=timeout)
        if not isinstance(payload, list):
            raise RuntimeError(f"Expected list from /{endpoint}, got {type(payload).__name__}")
        if not payload:
            break
        records.extend(payload)
        total = int(headers.get("omeka-s-total-results", "0") or 0)
        if total and len(records) >= total:
            break
        page += 1
    return records


def write_properties_csv(path: Path, properties: List[dict], vocab_by_id: Dict[int, str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["property_id", "term", "label", "vocabulary_id", "vocabulary_prefix", "comment"])
        for p in properties:
            vocab = p.get("o:vocabulary", {}) or {}
            writer.writerow(
                [
                    p.get("o:id"),
                    p.get("o:term"),
                    p.get("o:label"),
                    vocab.get("o:id"),
                    vocab_by_id.get(vocab.get("o:id"), ""),
                    p.get("o:comment"),
                ]
            )


def write_template_properties_csv(path: Path, templates: List[dict], property_by_id: Dict[int, dict]) -> Counter:
    usage = Counter()
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "template_id",
                "template_label",
                "resource_class_id",
                "property_id",
                "property_term",
                "property_label",
                "is_required",
                "is_private",
                "alternate_label",
                "data_types",
            ]
        )
        for t in templates:
            template_id = t.get("o:id")
            template_label = t.get("o:label")
            class_id = (t.get("o:resource_class") or {}).get("o:id")
            for tp in t.get("o:resource_template_property", []) or []:
                p_ref = tp.get("o:property") or {}
                property_id = p_ref.get("o:id")
                p = property_by_id.get(property_id, {})
                term = p.get("o:term", "")
                label = p.get("o:label", "")
                usage[property_id] += 1
                writer.writerow(
                    [
                        template_id,
                        template_label,
                        class_id,
                        property_id,
                        term,
                        label,
                        bool(tp.get("o:is_required", False)),
                        bool(tp.get("o:is_private", False)),
                        tp.get("o:alternate_label"),
                        ";".join(tp.get("o:data_type", []) or []),
                    ]
                )
    return usage


def write_report(
    path: Path,
    api_base: str,
    vocabularies: List[dict],
    properties: List[dict],
    resource_classes: List[dict],
    resource_templates: List[dict],
    usage: Counter,
    property_by_id: Dict[int, dict],
) -> None:
    top = usage.most_common(25)
    lines = [
        "# Omeka S Schema Report",
        "",
        f"- API base: `{api_base}`",
        f"- Vocabularies: **{len(vocabularies)}**",
        f"- Properties: **{len(properties)}**",
        f"- Resource classes: **{len(resource_classes)}**",
        f"- Resource templates: **{len(resource_templates)}**",
        "",
        "## Most Used Properties In Templates",
        "",
        "| property_id | term | label | template_count |",
        "|---:|---|---|---:|",
    ]
    for property_id, count in top:
        p = property_by_id.get(property_id, {})
        lines.append(f"| {property_id} | {p.get('o:term','')} | {p.get('o:label','')} | {count} |")
    lines.append("")
    lines.append("## Template Coverage")
    lines.append("")
    for t in resource_templates:
        template_id = t.get("o:id")
        template_label = t.get("o:label")
        class_id = (t.get("o:resource_class") or {}).get("o:id")
        prop_count = len(t.get("o:resource_template_property", []) or [])
        lines.append(
            f"- template `{template_id}`: {template_label} (resource_class_id={class_id}, properties={prop_count})"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Omeka S schema map artifacts")
    parser.add_argument("--url", required=True)
    parser.add_argument("--key-identity", default=os.getenv("OMEKA_KEY_IDENTITY"))
    parser.add_argument("--key-credential", default=os.getenv("OMEKA_KEY_CREDENTIAL"))
    parser.add_argument("--out-dir", default="outputs/omeka-schema")
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    if not args.key_identity or not args.key_credential:
        print("Missing credentials. Use --key-identity/--key-credential or env vars.", file=sys.stderr)
        return 2

    api_base = derive_api_base(args.url)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    vocabularies = fetch_all(
        api_base, "vocabularies", args.key_identity, args.key_credential, args.per_page, args.timeout
    )
    properties = fetch_all(
        api_base, "properties", args.key_identity, args.key_credential, args.per_page, args.timeout
    )
    resource_classes = fetch_all(
        api_base, "resource_classes", args.key_identity, args.key_credential, args.per_page, args.timeout
    )
    resource_templates = fetch_all(
        api_base, "resource_templates", args.key_identity, args.key_credential, args.per_page, args.timeout
    )

    vocab_by_id = {v.get("o:id"): v.get("o:prefix", "") for v in vocabularies}
    property_by_id = {p.get("o:id"): p for p in properties}

    write_properties_csv(out_dir / "properties.csv", properties, vocab_by_id)
    usage = write_template_properties_csv(out_dir / "template_properties.csv", resource_templates, property_by_id)

    summary = {
        "api_base": api_base,
        "counts": {
            "vocabularies": len(vocabularies),
            "properties": len(properties),
            "resource_classes": len(resource_classes),
            "resource_templates": len(resource_templates),
        },
        "top_property_usage_in_templates": [
            {
                "property_id": pid,
                "term": property_by_id.get(pid, {}).get("o:term"),
                "label": property_by_id.get(pid, {}).get("o:label"),
                "template_count": count,
            }
            for pid, count in usage.most_common(50)
        ],
    }
    (out_dir / "schema_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_report(
        out_dir / "schema_report.md",
        api_base,
        vocabularies,
        properties,
        resource_classes,
        resource_templates,
        usage,
        property_by_id,
    )

    print(f"Schema map complete: {out_dir}")
    print(
        json.dumps(
            {
                "vocabularies": len(vocabularies),
                "properties": len(properties),
                "resource_classes": len(resource_classes),
                "resource_templates": len(resource_templates),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
