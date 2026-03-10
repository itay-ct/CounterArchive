#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import tempfile
from typing import Dict, List, Tuple
from urllib.parse import urlencode, urlparse


RESOURCE_MAP = {
    "item": "items",
    "items": "items",
    "item_set": "item_sets",
    "item_sets": "item_sets",
    "media": "media",
    "site": "sites",
    "sites": "sites",
    "user": "users",
    "users": "users",
    "resource_template": "resource_templates",
    "resource_templates": "resource_templates",
    "resource_class": "resource_classes",
    "resource_classes": "resource_classes",
    "vocabulary": "vocabularies",
    "vocabularies": "vocabularies",
    "property": "properties",
    "properties": "properties",
}


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


def normalize_resource(resource: str) -> str:
    key = resource.strip().lower()
    if key not in RESOURCE_MAP:
        supported = ", ".join(sorted(set(RESOURCE_MAP.values())))
        raise ValueError(f"Unsupported resource '{resource}'. Supported: {supported}")
    return RESOURCE_MAP[key]


def parse_query_list(raw_pairs: List[str]) -> Dict[str, str]:
    query = {}
    for pair in raw_pairs:
        if "=" not in pair:
            raise ValueError(f"Invalid --query value '{pair}'. Expected key=value")
        k, v = pair.split("=", 1)
        query[k] = v
    return query


def parse_headers_file(path: str) -> Tuple[int, Dict[str, str], str]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    lines = [line.rstrip("\r") for line in text.splitlines()]
    blocks = []
    current = []
    for line in lines:
        if line.startswith("HTTP/"):
            if current:
                blocks.append(current)
            current = [line]
            continue
        if not current:
            continue
        if line == "":
            blocks.append(current)
            current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)

    if not blocks:
        raise RuntimeError("Could not parse response headers from curl output")

    last = blocks[-1]
    status_line = last[0]
    try:
        status_code = int(status_line.split()[1])
    except Exception as exc:
        raise RuntimeError(f"Unable to parse status line: {status_line}") from exc

    headers: Dict[str, str] = {}
    for line in last[1:]:
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        headers[k.strip().lower()] = v.strip()
    return status_code, headers, status_line


def request(
    method: str,
    url: str,
    timeout: int,
) -> Tuple[int, Dict[str, str], str]:
    with tempfile.NamedTemporaryFile(delete=False) as header_tmp:
        header_path = header_tmp.name

    cmd = [
        "curl",
        "-sS",
        "--max-time",
        str(timeout),
        "-X",
        method.upper(),
        "-H",
        "Accept: application/ld+json, application/json",
        "-D",
        header_path,
        url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        status_code, headers, status_line = parse_headers_file(header_path)
    finally:
        try:
            os.unlink(header_path)
        except OSError:
            pass

    if result.returncode != 0:
        stderr = result.stderr.strip() or "curl failed"
        raise RuntimeError(stderr)

    body = result.stdout
    if status_code >= 400:
        snippet = body.strip()[:800]
        raise RuntimeError(f"{status_line}. Body: {snippet}")
    return status_code, headers, body


def build_url(api_base: str, path: str, query: Dict[str, str], key_identity: str, key_credential: str) -> str:
    q = dict(query)
    q["key_identity"] = key_identity
    q["key_credential"] = key_credential
    qs = urlencode(q)
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{api_base}{path}?{qs}" if qs else f"{api_base}{path}"


def print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def parse_json_or_error(body: str) -> object:
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        snippet = body[:600]
        raise RuntimeError(f"Response is not valid JSON. Body starts with: {snippet}") from exc


def add_common_auth_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", required=True, help="Omeka admin URL, site URL, or API base URL")
    parser.add_argument("--key-identity", default=os.getenv("OMEKA_KEY_IDENTITY"))
    parser.add_argument("--key-credential", default=os.getenv("OMEKA_KEY_CREDENTIAL"))
    parser.add_argument("--timeout", type=int, default=30)


def ensure_auth(args: argparse.Namespace) -> None:
    if not args.key_identity or not args.key_credential:
        raise ValueError("Missing credentials. Use --key-identity/--key-credential or env vars.")


def cmd_verify(args: argparse.Namespace) -> int:
    api_base = derive_api_base(args.url)
    url = build_url(
        api_base,
        "/items",
        {"page": "1", "per_page": "1"},
        args.key_identity,
        args.key_credential,
    )
    status, headers, body = request("GET", url, args.timeout)
    payload = parse_json_or_error(body)
    total = headers.get("omeka-s-total-results", "unknown")
    version = headers.get("omeka-s-version", "unknown")
    first = payload[0] if isinstance(payload, list) and payload else {}
    first_id = first.get("o:id") if isinstance(first, dict) else None
    first_title = first.get("o:title") if isinstance(first, dict) else None

    print("SUCCESS")
    print(f"api_base={api_base}")
    print(f"http_status={status}")
    print(f"omeka_s_version={version}")
    print(f"total_results={total}")
    if first_id is not None:
        print(f"first_item_id={first_id}")
    if first_title:
        print(f"first_item_title={first_title}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    api_base = derive_api_base(args.url)
    resource = normalize_resource(args.resource)
    query = parse_query_list(args.query or [])
    query["page"] = str(args.page)
    query["per_page"] = str(args.per_page)
    url = build_url(api_base, f"/{resource}", query, args.key_identity, args.key_credential)
    status, headers, body = request("GET", url, args.timeout)
    payload = parse_json_or_error(body)
    print(f"http_status={status}")
    if "omeka-s-total-results" in headers:
        print(f"total_results={headers['omeka-s-total-results']}")
    print_json(payload)
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    api_base = derive_api_base(args.url)
    resource = normalize_resource(args.resource)
    query = parse_query_list(args.query or [])
    url = build_url(api_base, f"/{resource}/{args.id}", query, args.key_identity, args.key_credential)
    status, _, body = request("GET", url, args.timeout)
    payload = parse_json_or_error(body)
    print(f"http_status={status}")
    print_json(payload)
    return 0


def cmd_meta(args: argparse.Namespace) -> int:
    api_base = derive_api_base(args.url)
    query = parse_query_list(args.query or [])
    url = build_url(api_base, args.path, query, args.key_identity, args.key_credential)
    status, headers, body = request("GET", url, args.timeout)
    print(f"http_status={status}")
    print(f"request_url={url}")
    print("headers:")
    for k in sorted(headers):
        print(f"  {k}: {headers[k]}")
    print(f"body_bytes={len(body.encode('utf-8'))}")
    return 0


def cmd_fetch_json(args: argparse.Namespace) -> int:
    api_base = derive_api_base(args.url)
    query = parse_query_list(args.query or [])
    url = build_url(api_base, args.path, query, args.key_identity, args.key_credential)
    status, _, body = request("GET", url, args.timeout)
    payload = parse_json_or_error(body)
    print(f"http_status={status}")
    print_json(payload)
    return 0


def cmd_fetch_raw(args: argparse.Namespace) -> int:
    api_base = derive_api_base(args.url)
    query = parse_query_list(args.query or [])
    url = build_url(api_base, args.path, query, args.key_identity, args.key_credential)
    status, _, body = request("GET", url, args.timeout)
    print(f"http_status={status}")
    print(body)
    return 0


def cmd_resources(args: argparse.Namespace) -> int:
    resources = sorted(set(RESOURCE_MAP.values()))
    print_json({"supported_resources": resources})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Common Omeka S API operations")
    sub = parser.add_subparsers(dest="command", required=True)

    p_verify = sub.add_parser("verify", help="Verify API connectivity and credentials")
    add_common_auth_args(p_verify)
    p_verify.set_defaults(func=cmd_verify)

    p_list = sub.add_parser("list", help="List resources")
    add_common_auth_args(p_list)
    p_list.add_argument("--resource", required=True, help="e.g. items, item_sets, media, users")
    p_list.add_argument("--page", type=int, default=1)
    p_list.add_argument("--per-page", type=int, default=10)
    p_list.add_argument("--query", action="append", default=[], help="Extra query key=value (repeatable)")
    p_list.set_defaults(func=cmd_list)

    p_get = sub.add_parser("get", help="Get one resource by id")
    add_common_auth_args(p_get)
    p_get.add_argument("--resource", required=True)
    p_get.add_argument("--id", type=int, required=True)
    p_get.add_argument("--query", action="append", default=[], help="Extra query key=value (repeatable)")
    p_get.set_defaults(func=cmd_get)

    p_meta = sub.add_parser("meta", help="Read endpoint metadata (status + headers + size)")
    add_common_auth_args(p_meta)
    p_meta.add_argument("--path", required=True, help="API path, e.g. /resource_templates")
    p_meta.add_argument("--query", action="append", default=[], help="Extra query key=value (repeatable)")
    p_meta.set_defaults(func=cmd_meta)

    p_fetch_json = sub.add_parser("fetch-json", help="Read any API path and parse JSON response")
    add_common_auth_args(p_fetch_json)
    p_fetch_json.add_argument("--path", required=True, help="API path, e.g. /resource_templates")
    p_fetch_json.add_argument("--query", action="append", default=[], help="Extra query key=value (repeatable)")
    p_fetch_json.set_defaults(func=cmd_fetch_json)

    p_fetch_raw = sub.add_parser("fetch-raw", help="Read any API path and print raw response body")
    add_common_auth_args(p_fetch_raw)
    p_fetch_raw.add_argument("--path", required=True, help="API path, e.g. /resource_templates")
    p_fetch_raw.add_argument("--query", action="append", default=[], help="Extra query key=value (repeatable)")
    p_fetch_raw.set_defaults(func=cmd_fetch_raw)

    p_resources = sub.add_parser("resources", help="List supported resource names/aliases for list/get")
    p_resources.set_defaults(func=cmd_resources)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command != "resources":
            ensure_auth(args)
        return args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
