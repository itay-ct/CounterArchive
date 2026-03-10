# CounterArchive

Read-only Omeka S investigation toolkit for high-volume archival research.

This repository contains a modular pipeline that crawls Omeka S APIs, extracts multilingual entities, builds an investigation graph, mines cross-archive story candidates, and packages publishable story briefs.

## What This Repo Does

- Uses Omeka S API keys in read-only `GET` flows only.
- Runs iterative investigations:
  - `incremental`: process deltas and emit fresh stories quickly.
  - `weekly`: full recrawl + full rebuild for drift correction.
- Produces evidence-first outputs for each story:
  - JSON contract for downstream visualization.
  - Markdown brief with facts, hypotheses, relationships, and evidence links.
- Supports optional Neo4j graph writing.
- Includes a live story visualizer app (Cloudflare Worker + static web UI).

## Repository Layout

```text
skills/
  omeka-s-operations/        # Read-only Omeka API operations CLI
  omeka-s-connectivity/      # Connectivity verification utility
  omeka-s-crawler/           # Read-only crawler (JSONL snapshots)
  omeka-s-schema-mapper/     # Ontology/template/property mapping
  omeka-s-entity-lab/        # Multilingual entity extraction + provenance
  omeka-s-graph-forge/       # Graph build/update + optional Neo4j sync
  omeka-s-story-miner/       # Story candidate discovery + ranking
  omeka-s-story-packager/    # Story JSON/MD packaging + quality gates
  omeka-s-detective-agent/   # End-to-end orchestration pipeline

apps/live-story-visualizer/  # Live monitoring UI + ingest API
test_omeka.py                # Local utility test script
```

## Prerequisites

- Python 3.9+
- `curl`
- Optional: Neo4j (if not using `--skip-neo4j`)
- Optional: OpenAI API key (for narrative refinement mode)
- Optional: Node/npm + Wrangler (for live visualizer app)

## Authentication

Set credentials as environment variables or pass flags:

```bash
export OMEKA_KEY_IDENTITY="..."
export OMEKA_KEY_CREDENTIAL="..."
```

## Quick Start

1. Verify connectivity:

```bash
python3 skills/omeka-s-operations/scripts/omeka_ops.py verify \
  --url "https://<your-omeka>/archive/admin/user/7/edit"
```

2. Run incremental detective pipeline:

```bash
python3 skills/omeka-s-detective-agent/scripts/detective_pipeline.py \
  --mode incremental \
  --url "https://<your-omeka>/archive/admin/user/7/edit" \
  --key-identity "$OMEKA_KEY_IDENTITY" \
  --key-credential "$OMEKA_KEY_CREDENTIAL" \
  --workspace "outputs/detective-agent-live" \
  --story-count 20 \
  --skip-neo4j
```

3. Run weekly deep recompute:

```bash
python3 skills/omeka-s-detective-agent/scripts/detective_pipeline.py \
  --mode weekly \
  --url "https://<your-omeka>/archive/admin/user/7/edit" \
  --key-identity "$OMEKA_KEY_IDENTITY" \
  --key-credential "$OMEKA_KEY_CREDENTIAL" \
  --workspace "outputs/detective-agent-live" \
  --story-count 20
```

## End-to-End Pipeline

`detective_pipeline.py` orchestrates:

1. `omeka_crawl.py` -> resource JSONL crawl snapshots
2. `omeka_schema_map.py` -> weekly schema/ontology artifacts (weekly mode only)
3. `entity_lab.py` -> delta-aware entity/mention/doc extraction
4. `graph_forge.py` -> graph JSONL build/update + optional Neo4j write
5. `story_miner.py` -> ranked story candidates
6. `story_packager.py` -> publishable story contracts and markdown briefs

## Output Artifacts

Under `outputs/detective-agent-live/`:

- `runs/<timestamp>/crawl/` -> raw API JSONL per resource
- `runs/<timestamp>/entity/` -> `entities.jsonl`, `mentions.jsonl`, `docs.jsonl`
- `graph/` -> `graph_entities.jsonl`, `graph_docs.jsonl`, `graph_mentions.jsonl`, `graph_cooccurs.jsonl`, `graph_doc_refs.jsonl`
- `runs/<timestamp>/stories/candidate/story_candidates.jsonl`
- `runs/<timestamp>/stories/published/story_<id>.json`
- `runs/<timestamp>/stories/published/story_<id>.md`
- `runs/<timestamp>/stories/published/story_manifest.json`
- `runs/<timestamp>/run_summary.json`
- `state/doc_manifest.json` and `state/story_history.json`

## Story Ranking Logic

Story ranking prioritizes meaningful, non-trivial entities and relationships:

- Penalizes generic/over-broad entities (for example country/city-level anchors and archive-like labels).
- Penalizes placeholder/unresolved labels.
- Penalizes highly ubiquitous entities (high corpus coverage).
- Applies non-triviality boost for richer entity sets.
- Drops unresolved seed labels from final story candidates.

This keeps top-ranked stories focused on specific places, actors, and relationships rather than generic hubs.

## Read-Only Guarantee

All Omeka-facing scripts in this repo are read-only:

- API operations are `GET`-based.
- No create/update/delete operations are exposed.
- No request bodies are sent to Omeka endpoints.

## Live Story Visualizer (Optional)

See:

- `apps/live-story-visualizer/README.md`

Local flow:

```bash
npx wrangler dev --config apps/live-story-visualizer/worker/wrangler.toml
python3 apps/live-story-visualizer/scripts/publish_stories.py \
  --endpoint http://127.0.0.1:8787/api/ingest
```

## Notes

- `outputs/` and local runtime artifacts are ignored by `.gitignore`.
- Keep credentials in environment variables; never hardcode keys in committed files.
