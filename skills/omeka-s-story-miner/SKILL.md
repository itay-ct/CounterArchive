---
name: omeka-s-story-miner
description: Discover and rank entity-cluster story candidates from graph snapshots, emphasizing spatial-political relationships and cross-source evidence.
---

# Omeka S Story Miner

Use this skill to generate evidence-scored story candidates from the investigation graph.

## What it does

- Reads graph snapshots from Graph Forge.
- Builds entity clusters (seeded by place/institution-heavy nodes).
- Scores candidates by novelty and evidence strength.
- Emits facts + hypotheses narrative layers with quality metadata.
- Targets 10-20 candidates per incremental run by default.
- Supports optional OpenAI refinement for narrative phrasing (`--llm-provider openai`).

## Script

- `scripts/story_miner.py`

## Example

```bash
python3 skills/omeka-s-story-miner/scripts/story_miner.py \
  --graph-dir "outputs/detective/graph" \
  --output-dir "outputs/detective/stories" \
  --story-count 15 \
  --theme "spatial-political-relations"
```

Optional hybrid mode:

```bash
python3 skills/omeka-s-story-miner/scripts/story_miner.py \
  --graph-dir "outputs/detective/graph" \
  --output-dir "outputs/detective/stories" \
  --story-count 15 \
  --llm-provider openai \
  --llm-model gpt-4.1-mini \
  --openai-api-key "$OPENAI_API_KEY"
```

## Output

- `story_candidates.jsonl`
- `story_miner_summary.json`
