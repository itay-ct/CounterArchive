---
name: omeka-s-crawler
description: Crawl Omeka S API resources in read-only mode with pagination, retries, and resume checkpoints. Use for full dataset extraction to local JSONL files for heavy research workflows.
---

# Omeka S Crawler

Use this skill for large-scale read-only extraction from Omeka S.

## What it does

- Crawls selected API resources page by page.
- Stores records as newline-delimited JSON (`.jsonl`) per resource.
- Writes a checkpoint state file so interrupted runs can resume.
- Uses only `GET` requests.

## Script

- `scripts/omeka_crawl.py`

## Example

```bash
python3 skills/omeka-s-crawler/scripts/omeka_crawl.py \
  --url "https://example.org/archive/admin/user/7/edit" \
  --key-identity "$OMEKA_KEY_IDENTITY" \
  --key-credential "$OMEKA_KEY_CREDENTIAL" \
  --resources items,media,item_sets,sites,users,resource_templates,resource_classes,vocabularies,properties \
  --per-page 100 \
  --out-dir "outputs/omeka-crawl"
```

## Output

- `outputs/omeka-crawl/state.json`
- `outputs/omeka-crawl/items.jsonl`
- `outputs/omeka-crawl/media.jsonl`
- one file per crawled resource

## Notes

- Resume is enabled by default and starts from `next_page` in state.
- For partial runs, use `--max-pages-per-resource`.
- For fresh recrawl, use `--no-resume`.
