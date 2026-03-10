#!/usr/bin/env python3
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlencode, urlparse


DEFAULT_RESOURCES = [
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


def http_get_json(url: str, timeout: int, retries: int) -> Tuple[int, Dict[str, str], object]:
    last_err = None
    for attempt in range(retries + 1):
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
                last_err = proc.stderr.strip() or f"curl exit {proc.returncode}"
                raise RuntimeError(last_err)
            if status >= 400:
                snippet = proc.stdout.strip()[:500]
                last_err = f"HTTP {status}: {snippet}"
                raise RuntimeError(last_err)
            body = proc.stdout.strip()
            payload = json.loads(body) if body else []
            return status, headers, payload
        except Exception as exc:
            last_err = str(exc)
            if attempt < retries:
                time.sleep(min(4, 1 + attempt))
            else:
                raise RuntimeError(last_err) from exc
        finally:
            try:
                os.unlink(hdr_file.name)
            except OSError:
                pass
    raise RuntimeError(last_err or "request failed")


def load_state(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"resources": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: Dict[str, object]) -> None:
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def crawl_resource(
    api_base: str,
    resource: str,
    key_identity: str,
    key_credential: str,
    per_page: int,
    timeout: int,
    retries: int,
    sleep_ms: int,
    max_pages: int,
    out_file: Path,
    state: Dict[str, object],
) -> None:
    resources_state = state.setdefault("resources", {})
    resource_state = resources_state.setdefault(resource, {})
    next_page = int(resource_state.get("next_page", 1))
    pages_done = int(resource_state.get("pages_done", 0))

    print(f"[{resource}] start page={next_page}")
    with out_file.open("a", encoding="utf-8") as f:
        page = next_page
        while True:
            if max_pages > 0 and pages_done >= max_pages:
                print(f"[{resource}] reached max-pages-per-resource={max_pages}")
                break

            query = urlencode(
                {
                    "page": page,
                    "per_page": per_page,
                    "key_identity": key_identity,
                    "key_credential": key_credential,
                }
            )
            url = f"{api_base}/{resource}?{query}"
            status, headers, payload = http_get_json(url, timeout=timeout, retries=retries)
            if not isinstance(payload, list):
                raise RuntimeError(f"[{resource}] expected list payload, got {type(payload).__name__}")

            total_results = int(headers.get("omeka-s-total-results", "0") or 0)
            total_pages = math.ceil(total_results / per_page) if per_page else 0

            for record in payload:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            pages_done += 1
            resource_state["next_page"] = page + 1
            resource_state["pages_done"] = pages_done
            resource_state["last_status"] = status
            resource_state["last_count"] = len(payload)
            resource_state["total_results"] = total_results
            resource_state["total_pages"] = total_pages
            resource_state["updated_at"] = int(time.time())

            if len(payload) == 0:
                resource_state["done"] = True
                print(f"[{resource}] done (empty page at {page})")
                break

            if total_pages and page >= total_pages:
                resource_state["done"] = True
                print(f"[{resource}] done ({page}/{total_pages})")
                break

            print(f"[{resource}] page={page} records={len(payload)} total={total_results}")
            page += 1
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Omeka S crawler with resume")
    parser.add_argument("--url", required=True, help="Omeka admin URL, site URL, or API base URL")
    parser.add_argument("--key-identity", default=os.getenv("OMEKA_KEY_IDENTITY"))
    parser.add_argument("--key-credential", default=os.getenv("OMEKA_KEY_CREDENTIAL"))
    parser.add_argument("--resources", default=",".join(DEFAULT_RESOURCES))
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--sleep-ms", type=int, default=0)
    parser.add_argument("--max-pages-per-resource", type=int, default=0)
    parser.add_argument("--out-dir", default="outputs/omeka-crawl")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    if not args.key_identity or not args.key_credential:
        print("Missing credentials. Use --key-identity/--key-credential or env vars.", file=sys.stderr)
        return 2
    if args.per_page <= 0:
        print("--per-page must be > 0", file=sys.stderr)
        return 2

    api_base = derive_api_base(args.url)
    resources = [r.strip() for r in args.resources.split(",") if r.strip()]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "state.json"

    state = {"api_base": api_base, "resources": {}}
    if not args.no_resume:
        state = load_state(state_path)
        state["api_base"] = api_base

    for resource in resources:
        out_file = out_dir / f"{resource}.jsonl"
        try:
            crawl_resource(
                api_base=api_base,
                resource=resource,
                key_identity=args.key_identity,
                key_credential=args.key_credential,
                per_page=args.per_page,
                timeout=args.timeout,
                retries=args.retries,
                sleep_ms=args.sleep_ms,
                max_pages=args.max_pages_per_resource,
                out_file=out_file,
                state=state,
            )
            save_state(state_path, state)
        except Exception as exc:
            save_state(state_path, state)
            print(f"[{resource}] failed: {exc}", file=sys.stderr)
            return 1

    print(f"Crawl complete. state={state_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
