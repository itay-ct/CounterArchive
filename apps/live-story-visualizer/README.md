# Live Story Visualizer

MVP for human-readable live story monitoring using the `story_*.json` artifacts produced by the Omeka story pipeline.

## What this includes

- Cloudflare Worker API with Durable Object fanout and storage:
  - `GET /api/stories?limit=...&tier=...`
  - `GET /api/stories/:id`
  - `GET /api/metrics`
  - `POST /api/ingest` (Bearer token support)
  - `GET /ws` (live update stream)
- Static frontend:
  - live feed cards
  - entity relationship graph
  - evidence timeline
  - facts / hypotheses / source evidence panel
- Publisher utility to push packaged stories into the live service.

## Files

- Worker: `/Users/itay.tevel/omeka/apps/live-story-visualizer/worker/src/index.js`
- Wrangler config: `/Users/itay.tevel/omeka/apps/live-story-visualizer/worker/wrangler.toml`
- Frontend: `/Users/itay.tevel/omeka/apps/live-story-visualizer/web/index.html`
- Publisher script: `/Users/itay.tevel/omeka/apps/live-story-visualizer/scripts/publish_stories.py`
- Bootstrap demo data: `/Users/itay.tevel/omeka/apps/live-story-visualizer/web/data/bootstrap_stories.json`

## Local dev

1. Start the app locally:

```bash
npx wrangler dev --config apps/live-story-visualizer/worker/wrangler.toml
```

2. Open the local URL reported by Wrangler.

3. Ingest stories from your latest manifest:

```bash
python3 apps/live-story-visualizer/scripts/publish_stories.py \
  --endpoint http://127.0.0.1:8787/api/ingest
```

## Deploy

1. Deploy worker + static assets:

```bash
npx wrangler deploy --config apps/live-story-visualizer/worker/wrangler.toml
```

2. Configure ingest auth token (recommended):

```bash
npx wrangler secret put INGEST_TOKEN --config apps/live-story-visualizer/worker/wrangler.toml
```

3. Publish stories to the deployed endpoint:

```bash
python3 apps/live-story-visualizer/scripts/publish_stories.py \
  --endpoint https://<your-worker-domain>/api/ingest \
  --token "<INGEST_TOKEN>"
```

## Pipeline handoff

Recommended handoff point is after `story_packager` writes `story_manifest.json` and `story_*.json`.

You can call the publisher script from that stage to make stories visible live within seconds.
