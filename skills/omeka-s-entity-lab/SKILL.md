---
name: omeka-s-entity-lab
description: Extract multilingual entities (Hebrew/Arabic/English) from Omeka crawl JSONL, preserve contested aliases, and produce delta-aware entity mentions with provenance for graph ingestion.
---

# Omeka S Entity Lab

Use this skill to transform crawled Omeka records into entity/mention artifacts.

## What it does

- Reads crawl JSONL files (items/media/item_sets/sites/users/...).
- Performs lightweight multilingual entity extraction from linked-data fields.
- Preserves alternative names and contested aliases (no forced canonical collapse).
- Supports incremental mode using a `doc_manifest.json` (`o:id` + `o:modified`).
- Outputs normalized entities, mentions, and changed-doc records with provenance.

## Script

- `scripts/entity_lab.py`

## Example

```bash
python3 skills/omeka-s-entity-lab/scripts/entity_lab.py \
  --input-dir "outputs/omeka-crawl" \
  --output-dir "outputs/detective/entity" \
  --manifest-path "outputs/detective/state/doc_manifest.json" \
  --mode incremental
```

## Outputs

- `entities.jsonl`
- `mentions.jsonl`
- `docs.jsonl`
- `entity_lab_summary.json`
