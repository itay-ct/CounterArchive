---
name: omeka-s-detective-agent
description: Orchestrate iterative Counter-Archives investigations by chaining crawler, schema mapper, entity lab, graph forge, story miner, and story packager into incremental or weekly deep runs.
---

# Omeka S Detective Agent

Use this skill to run the full investigation pipeline end-to-end.

## Modes

- `incremental`: crawl + delta extraction + graph update + story generation.
- `weekly`: full recrawl + schema refresh + full graph rebuild + story generation.
- Narrative mode can be local template-only or hybrid with OpenAI refinement.
- Graph reference fan-out is capped by default for scale (`max-doc-ref-*` flags).

## Script

- `scripts/detective_pipeline.py`

## Example (incremental)

```bash
python3 skills/omeka-s-detective-agent/scripts/detective_pipeline.py \
  --mode incremental \
  --url "https://example.org/archive/admin/user/7/edit" \
  --key-identity "$OMEKA_KEY_IDENTITY" \
  --key-credential "$OMEKA_KEY_CREDENTIAL" \
  --workspace "outputs/detective-agent" \
  --story-count 15 \
  --skip-neo4j
```

## Example (hybrid local + API narrative)

```bash
python3 skills/omeka-s-detective-agent/scripts/detective_pipeline.py \
  --mode incremental \
  --url "https://example.org/archive/admin/user/7/edit" \
  --key-identity "$OMEKA_KEY_IDENTITY" \
  --key-credential "$OMEKA_KEY_CREDENTIAL" \
  --workspace "outputs/detective-agent" \
  --llm-provider openai \
  --llm-model gpt-4.1-mini \
  --openai-api-key "$OPENAI_API_KEY"
```

## Example (weekly deep)

```bash
python3 skills/omeka-s-detective-agent/scripts/detective_pipeline.py \
  --mode weekly \
  --url "https://example.org/archive/admin/user/7/edit" \
  --key-identity "$OMEKA_KEY_IDENTITY" \
  --key-credential "$OMEKA_KEY_CREDENTIAL" \
  --workspace "outputs/detective-agent" \
  --story-count 20
```
