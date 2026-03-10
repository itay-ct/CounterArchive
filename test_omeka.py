#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from urllib.parse import urlencode, urlparse


def derive_api_base(admin_or_site_url: str) -> str:
    """
    Accepts an Omeka admin URL, site URL, or API base URL and returns /api base.
    """
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


def curl_get_json(url: str, timeout: int = 30):
    cmd = [
        "curl",
        "-sS",
        "--max-time",
        str(timeout),
        "-H",
        "Accept: application/ld+json, application/json",
        "-D",
        "-",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "curl failed")

    raw = result.stdout
    sep = "\r\n\r\n" if "\r\n\r\n" in raw else "\n\n"
    if sep not in raw:
        raise RuntimeError("Unable to parse HTTP response from curl output")

    headers_text, body = raw.split(sep, 1)
    header_lines = [line.strip() for line in headers_text.splitlines() if line.strip()]
    status_line = header_lines[0] if header_lines else "HTTP/1.1 000"
    try:
        status_code = int(status_line.split()[1])
    except Exception as exc:
        raise RuntimeError(f"Unable to parse status line: {status_line}") from exc

    headers = {}
    for line in header_lines[1:]:
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        headers[k.strip().lower()] = v.strip()

    if status_code >= 400:
        snippet = body.strip()[:500]
        raise RuntimeError(f"HTTP {status_code} from server. Body: {snippet}")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        snippet = body.strip()[:500]
        raise RuntimeError(f"Response is not valid JSON. Body starts with: {snippet}") from exc

    return status_code, headers, payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Omeka S API connectivity")
    parser.add_argument(
        "--url",
        default="https://jmurbanhist.dh.huji.ac.il/archive/admin/user/7/edit",
        help="Omeka admin URL, site URL, or API base URL",
    )
    parser.add_argument(
        "--key-identity",
        default=os.getenv("OMEKA_KEY_IDENTITY"),
        help="Omeka API key identity (or env OMEKA_KEY_IDENTITY)",
    )
    parser.add_argument(
        "--key-credential",
        default=os.getenv("OMEKA_KEY_CREDENTIAL"),
        help="Omeka API key credential (or env OMEKA_KEY_CREDENTIAL)",
    )
    parser.add_argument("--per-page", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    if not args.key_identity or not args.key_credential:
        print("Missing credentials. Set --key-identity/--key-credential or env vars.", file=sys.stderr)
        return 2

    api_base = derive_api_base(args.url)
    query = urlencode(
        {
            "page": 1,
            "per_page": args.per_page,
            "key_identity": args.key_identity,
            "key_credential": args.key_credential,
        }
    )
    request_url = f"{api_base}/items?{query}"

    try:
        status, headers, payload = curl_get_json(request_url, timeout=args.timeout)
    except Exception as exc:
        print(f"Connection check failed: {exc}", file=sys.stderr)
        print(
            "Tip: run this curl command manually to compare behavior:\n"
            f"curl -i \"{request_url}\"",
            file=sys.stderr,
        )
        return 1

    total = headers.get("omeka-s-total-results", "unknown")
    version = headers.get("omeka-s-version", "unknown")
    count = len(payload) if isinstance(payload, list) else 1

    first_id = None
    first_title = None
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            first_id = first.get("o:id")
            first_title = first.get("o:title")

    print("Omeka connectivity check: SUCCESS")
    print(f"api_base={api_base}")
    print(f"http_status={status}")
    print(f"omeka_s_version={version}")
    print(f"total_results={total}")
    print(f"returned_items={count}")
    if first_id is not None:
        print(f"first_item_id={first_id}")
    if first_title:
        print(f"first_item_title={first_title}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
