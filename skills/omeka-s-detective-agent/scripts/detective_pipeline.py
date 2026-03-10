#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run_cmd(cmd, env=None):
    print("RUN:", " ".join(cmd))
    proc = subprocess.run(cmd, env=env, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.returncode != 0:
        if proc.stderr:
            print(proc.stderr.rstrip(), file=sys.stderr)
        raise RuntimeError(f"Command failed with exit {proc.returncode}: {' '.join(cmd)}")


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Counter-Archives detective pipeline orchestrator")
    parser.add_argument("--mode", choices=["incremental", "weekly"], default="incremental")
    parser.add_argument("--url", required=True)
    parser.add_argument("--key-identity", default=os.getenv("OMEKA_KEY_IDENTITY"))
    parser.add_argument("--key-credential", default=os.getenv("OMEKA_KEY_CREDENTIAL"))
    parser.add_argument("--workspace", default="outputs/detective-agent")
    parser.add_argument(
        "--resources",
        default="items,media,item_sets,sites,users,resource_templates,resource_classes,vocabularies,properties",
    )
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--crawler-max-pages-per-resource", type=int, default=0)
    parser.add_argument("--story-count", type=int, default=15)
    parser.add_argument("--theme", default="spatial-political-relations")
    parser.add_argument("--llm-provider", choices=["template", "openai"], default="template")
    parser.add_argument("--llm-model", default="gpt-4.1-mini")
    parser.add_argument("--openai-api-key", default=os.getenv("OPENAI_API_KEY", ""))
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default=os.getenv("NEO4J_PASSWORD", ""))
    parser.add_argument("--max-doc-ref-targets-per-surface", type=int, default=25)
    parser.add_argument("--max-doc-refs-total", type=int, default=500000)
    parser.add_argument("--skip-neo4j", action="store_true")
    parser.add_argument("--input-crawl-dir", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.key_identity or not args.key_credential:
        print("Missing credentials. Use --key-identity/--key-credential or env vars.", file=sys.stderr)
        return 2

    root = Path(__file__).resolve().parents[3]
    workspace = Path(args.workspace)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = workspace / "runs" / run_id
    crawl_dir = run_dir / "crawl"
    entity_dir = run_dir / "entity"
    stories_dir = run_dir / "stories"
    graph_dir = workspace / "graph"
    state_dir = workspace / "state"
    schema_dir = run_dir / "schema"
    manifest_path = state_dir / "doc_manifest.json"
    history_path = state_dir / "story_history.json"

    for p in [run_dir, state_dir, graph_dir, stories_dir]:
        ensure_dir(p)

    env = os.environ.copy()
    env["OMEKA_KEY_IDENTITY"] = args.key_identity
    env["OMEKA_KEY_CREDENTIAL"] = args.key_credential
    if args.neo4j_password:
        env["NEO4J_PASSWORD"] = args.neo4j_password
    if args.openai_api_key:
        env["OPENAI_API_KEY"] = args.openai_api_key

    if args.input_crawl_dir:
        source = Path(args.input_crawl_dir)
        if not source.exists():
            raise RuntimeError(f"--input-crawl-dir does not exist: {source}")
        shutil.copytree(source, crawl_dir, dirs_exist_ok=True)
    else:
        crawler = root / "skills" / "omeka-s-crawler" / "scripts" / "omeka_crawl.py"
        crawl_cmd = [
            "python3",
            str(crawler),
            "--url",
            args.url,
            "--key-identity",
            args.key_identity,
            "--key-credential",
            args.key_credential,
            "--resources",
            args.resources,
            "--per-page",
            str(args.per_page),
            "--out-dir",
            str(crawl_dir),
            "--no-resume",
        ]
        if args.crawler_max_pages_per_resource > 0:
            crawl_cmd.extend(["--max-pages-per-resource", str(args.crawler_max_pages_per_resource)])
        run_cmd(crawl_cmd, env=env)

    if args.mode == "weekly":
        schema_mapper = root / "skills" / "omeka-s-schema-mapper" / "scripts" / "omeka_schema_map.py"
        schema_cmd = [
            "python3",
            str(schema_mapper),
            "--url",
            args.url,
            "--key-identity",
            args.key_identity,
            "--key-credential",
            args.key_credential,
            "--out-dir",
            str(schema_dir),
            "--per-page",
            "200",
        ]
        run_cmd(schema_cmd, env=env)

    entity_lab = root / "skills" / "omeka-s-entity-lab" / "scripts" / "entity_lab.py"
    entity_cmd = [
        "python3",
        str(entity_lab),
        "--input-dir",
        str(crawl_dir),
        "--output-dir",
        str(entity_dir),
        "--manifest-path",
        str(manifest_path),
        "--mode",
        "full" if args.mode == "weekly" else "incremental",
        "--resources",
        args.resources,
    ]
    run_cmd(entity_cmd, env=env)

    graph_forge = root / "skills" / "omeka-s-graph-forge" / "scripts" / "graph_forge.py"
    graph_cmd = [
        "python3",
        str(graph_forge),
        "--entity-dir",
        str(entity_dir),
        "--graph-dir",
        str(graph_dir),
        "--mode",
        "full" if args.mode == "weekly" else "incremental",
        "--neo4j-uri",
        args.neo4j_uri,
        "--neo4j-user",
        args.neo4j_user,
        "--neo4j-password",
        args.neo4j_password,
        "--max-doc-ref-targets-per-surface",
        str(args.max_doc_ref_targets_per_surface),
        "--max-doc-refs-total",
        str(args.max_doc_refs_total),
    ]
    if args.skip_neo4j:
        graph_cmd.append("--skip-neo4j")
    run_cmd(graph_cmd, env=env)

    story_miner = root / "skills" / "omeka-s-story-miner" / "scripts" / "story_miner.py"
    stories_work_dir = stories_dir / "candidate"
    ensure_dir(stories_work_dir)
    miner_cmd = [
        "python3",
        str(story_miner),
        "--graph-dir",
        str(graph_dir),
        "--output-dir",
        str(stories_work_dir),
        "--story-count",
        str(args.story_count),
        "--theme",
        args.theme,
        "--history-path",
        str(history_path),
        "--llm-provider",
        args.llm_provider,
        "--llm-model",
        args.llm_model,
    ]
    if args.openai_api_key:
        miner_cmd.extend(["--openai-api-key", args.openai_api_key])
    run_cmd(miner_cmd, env=env)

    packager = root / "skills" / "omeka-s-story-packager" / "scripts" / "story_packager.py"
    published_dir = stories_dir / "published"
    ensure_dir(published_dir)
    pack_cmd = [
        "python3",
        str(packager),
        "--input-candidates",
        str(stories_work_dir / "story_candidates.jsonl"),
        "--output-dir",
        str(published_dir),
        "--min-evidence-links",
        "3",
        "--min-cross-source",
        "2",
    ]
    run_cmd(pack_cmd, env=env)

    latest_link = workspace / "latest"
    if latest_link.exists() or latest_link.is_symlink():
        if latest_link.is_symlink() or latest_link.is_file():
            latest_link.unlink()
        elif latest_link.is_dir():
            shutil.rmtree(latest_link)
    latest_link.symlink_to(run_dir, target_is_directory=True)

    summary = {
        "run_id": run_id,
        "mode": args.mode,
        "workspace": str(workspace),
        "run_dir": str(run_dir),
        "crawl_dir": str(crawl_dir),
        "entity_dir": str(entity_dir),
        "graph_dir": str(graph_dir),
        "stories_dir": str(published_dir),
        "story_count_target": args.story_count,
        "theme": args.theme,
        "llm_provider": args.llm_provider,
        "llm_model": args.llm_model if args.llm_provider == "openai" else "",
        "neo4j_enabled": not args.skip_neo4j,
        "max_doc_ref_targets_per_surface": args.max_doc_ref_targets_per_surface,
        "max_doc_refs_total": args.max_doc_refs_total,
        "crawler_max_pages_per_resource": args.crawler_max_pages_per_resource,
        "timestamp_utc": run_id,
    }
    (run_dir / "run_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
