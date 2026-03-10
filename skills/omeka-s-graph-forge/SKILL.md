---
name: omeka-s-graph-forge
description: Build and incrementally update an investigation graph from entity-lab outputs, persist snapshots, and (optionally) mirror into Neo4j for graph queries.
---

# Omeka S Graph Forge

Use this skill to turn entity mentions into a queryable relationship graph.

## What it does

- Ingests `entities.jsonl`, `mentions.jsonl`, and `docs.jsonl`.
- Supports incremental graph updates by replacing changed-doc mention slices.
- Produces graph snapshots (`graph_entities.jsonl`, `graph_docs.jsonl`, `graph_mentions.jsonl`, `graph_cooccurs.jsonl`, `graph_doc_refs.jsonl`).
- Optionally writes the graph into Neo4j (`bolt://...`) with provenance-rich edges.

## Script

- `scripts/graph_forge.py`

## Example

```bash
python3 skills/omeka-s-graph-forge/scripts/graph_forge.py \
  --entity-dir "outputs/detective/entity" \
  --graph-dir "outputs/detective/graph" \
  --mode incremental \
  --neo4j-uri "bolt://localhost:7687" \
  --neo4j-user "neo4j" \
  --neo4j-password "$NEO4J_PASSWORD"
```

## Notes

- Neo4j is optional at runtime (`--skip-neo4j`) but snapshots are always written.
- Graph edges keep provenance (`doc_id`, field/source metadata) for traceability.
- Scaling guards are available:
  - `--max-doc-ref-targets-per-surface` (default `25`)
  - `--max-doc-refs-total` (default `500000`)
