---
name: omeka-s-story-packager
description: Enforce evidence gates and package story candidates into visualization-ready JSON plus Markdown briefs, with explicit facts vs hypotheses structure.
---

# Omeka S Story Packager

Use this skill to transform candidate stories into final publication artifacts.

## What it does

- Reads `story_candidates.jsonl`.
- Applies promotion gate (`>=3` evidence links and cross-source support).
- Writes one `story_<id>.json` and one `story_<id>.md` per candidate.
- Produces run manifest and evaluation metrics.

## Script

- `scripts/story_packager.py`

## Example

```bash
python3 skills/omeka-s-story-packager/scripts/story_packager.py \
  --input-candidates "outputs/detective/stories/story_candidates.jsonl" \
  --output-dir "outputs/detective/published-stories"
```

## Outputs

- `story_*.json`
- `story_*.md`
- `story_manifest.json`
- `story_metrics.json`
