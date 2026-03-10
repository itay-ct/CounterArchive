#!/usr/bin/env python3
"""Push packaged Omeka story JSON files to the live story visualizer ingest endpoint."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, List, Optional


def find_latest_manifest(repo_root: Path) -> Optional[Path]:
    candidates: List[Path] = []

    live_runs = repo_root / "outputs" / "detective-agent-live" / "runs"
    if live_runs.exists():
        candidates.extend(live_runs.glob("*/stories/published/story_manifest.json"))

    fallback = repo_root / "outputs" / "detective-smoke" / "stories" / "published" / "story_manifest.json"
    if fallback.exists():
        candidates.append(fallback)

    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_manifest(manifest_path: Path) -> list[dict]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_stories(entries: Iterable[dict], include_candidates: bool) -> list[dict]:
    stories: list[dict] = []
    for row in entries:
        tier = row.get("publication_tier", "candidate")
        if tier != "strong" and not include_candidates:
            continue

        story_path_raw = row.get("json_path")
        if not story_path_raw:
            continue

        story_path = Path(story_path_raw)
        if not story_path.exists():
            continue

        try:
            story = json.loads(story_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        stories.append(story)

    return stories


def chunked(rows: list[dict], chunk_size: int) -> Iterable[list[dict]]:
    for start in range(0, len(rows), chunk_size):
        yield rows[start : start + chunk_size]


def post_batch(endpoint: str, token: str, batch: list[dict], timeout: int) -> dict:
    payload = json.dumps({"stories": batch}, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")

    return json.loads(body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish story_packager outputs to live visualizer ingest API")
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:8787/api/ingest",
        help="Ingest endpoint (for deployed worker, use your public /api/ingest URL)",
    )
    parser.add_argument("--manifest", help="Path to story_manifest.json. If omitted, the newest known manifest is used.")
    parser.add_argument("--token", default=os.getenv("STORY_INGEST_TOKEN", ""), help="Bearer token for ingest auth")
    parser.add_argument("--include-candidates", action="store_true", help="Send candidate-tier stories as well")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(__file__).resolve().parents[3]

    manifest_path = Path(args.manifest) if args.manifest else find_latest_manifest(repo_root)
    if not manifest_path or not manifest_path.exists():
        print("No manifest found. Pass --manifest explicitly.", file=sys.stderr)
        return 2

    entries = load_manifest(manifest_path)
    stories = load_stories(entries, include_candidates=args.include_candidates)

    print(f"manifest={manifest_path}")
    print(f"stories_selected={len(stories)}")

    if not stories:
        print("No stories selected for ingest.")
        return 0

    if args.dry_run:
        print("dry_run=true")
        return 0

    total_upserted = 0
    for batch in chunked(stories, max(1, args.batch_size)):
        try:
            result = post_batch(args.endpoint, args.token, batch, timeout=args.timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            print(f"HTTP error {exc.code}: {body}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"Request failed: {exc}", file=sys.stderr)
            return 1

        upserted = int(result.get("upserted", 0))
        total_upserted += upserted
        print(f"batch_upserted={upserted} metrics={json.dumps(result.get('metrics', {}), ensure_ascii=False)}")

    print(f"total_upserted={total_upserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
