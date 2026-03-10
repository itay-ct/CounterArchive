const HUB_NAME = "live-story-hub";
const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

function jsonResponse(payload, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { ...JSON_HEADERS, ...extraHeaders },
  });
}

function clampInt(value, fallback, min, max) {
  const parsed = Number.parseInt(value ?? "", 10);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, parsed));
}

function normalizeStory(raw, ingestedAt) {
  if (!raw || typeof raw !== "object") {
    return null;
  }

  const storyId = String(raw.story_id ?? "").trim();
  if (!storyId) {
    return null;
  }

  const publicationTier = raw.publication_tier === "strong" ? "strong" : "candidate";
  const publishedAt =
    raw?.time_window?.max || raw?.time_window?.min || raw.published_at || raw.ingested_at || ingestedAt;

  return {
    ...raw,
    story_id: storyId,
    publication_tier: publicationTier,
    quality_score: Number(raw.quality_score ?? 0),
    cross_source_count: Number(raw.cross_source_count ?? 0),
    evidence_count: Number(raw.evidence_count ?? (Array.isArray(raw.evidence) ? raw.evidence.length : 0)),
    published_at: String(publishedAt),
    ingested_at: ingestedAt,
  };
}

function toPreview(story) {
  return {
    story_id: story.story_id,
    title: story.title ?? "Untitled story",
    theme: story.theme ?? "unknown",
    publication_tier: story.publication_tier,
    quality_score: story.quality_score,
    cross_source_count: story.cross_source_count,
    evidence_count: story.evidence_count,
    published_at: story.published_at,
    ingested_at: story.ingested_at,
    location_scope: Array.isArray(story.location_scope) ? story.location_scope.slice(0, 8) : [],
    time_window: story.time_window ?? { min: "", max: "" },
  };
}

function requireBearerToken(request, env) {
  const expected = String(env.INGEST_TOKEN ?? "").trim();
  if (!expected) {
    return true;
  }

  const auth = request.headers.get("authorization") ?? "";
  if (!auth.startsWith("Bearer ")) {
    return false;
  }

  return auth.slice(7).trim() === expected;
}

function routeNotFound() {
  return jsonResponse({ error: "Not found" }, 404);
}

function sortPreviews(previews) {
  return previews.sort((a, b) => {
    const byPublished = String(b.published_at).localeCompare(String(a.published_at));
    if (byPublished !== 0) {
      return byPublished;
    }
    return Number(b.quality_score) - Number(a.quality_score);
  });
}

export class StoryHub {
  constructor(state, env) {
    this.state = state;
    this.env = env;
    this.sockets = new Set();
    this.index = {};
    this.metrics = { total: 0, strong: 0, candidate: 0, last_ingest_at: "" };

    this.ready = this.state.blockConcurrencyWhile(async () => {
      this.index = (await this.state.storage.get("index")) ?? {};
      this.metrics =
        (await this.state.storage.get("metrics")) ?? { total: 0, strong: 0, candidate: 0, last_ingest_at: "" };
    });
  }

  async fetch(request) {
    await this.ready;

    const url = new URL(request.url);
    const path = url.pathname;

    if (path === "/health" && request.method === "GET") {
      return jsonResponse({ ok: true, metrics: this.metrics });
    }

    if (path === "/stories" && request.method === "GET") {
      const limit = clampInt(url.searchParams.get("limit"), 50, 1, 500);
      const tier = url.searchParams.get("tier");
      const stories = sortPreviews(Object.values(this.index)).filter((row) => {
        if (tier === "strong") {
          return row.publication_tier === "strong";
        }
        if (tier === "candidate") {
          return row.publication_tier === "candidate";
        }
        return true;
      });
      return jsonResponse({ stories: stories.slice(0, limit), metrics: this.metrics });
    }

    if (path.startsWith("/story/") && request.method === "GET") {
      const storyId = decodeURIComponent(path.slice("/story/".length));
      const story = await this.state.storage.get(`story:${storyId}`);
      if (!story) {
        return jsonResponse({ error: "Story not found", story_id: storyId }, 404);
      }
      return jsonResponse({ story });
    }

    if (path === "/metrics" && request.method === "GET") {
      return jsonResponse({ metrics: this.metrics });
    }

    if (path === "/ingest" && request.method === "POST") {
      let payload;
      try {
        payload = await request.json();
      } catch {
        return jsonResponse({ error: "Body must be valid JSON" }, 400);
      }

      const rows = Array.isArray(payload?.stories)
        ? payload.stories
        : payload?.story
          ? [payload.story]
          : Array.isArray(payload)
            ? payload
            : [];

      if (!rows.length) {
        return jsonResponse({ error: "No stories to ingest" }, 400);
      }

      const now = new Date().toISOString();
      const upserted = [];
      for (const raw of rows) {
        const story = normalizeStory(raw, now);
        if (!story) {
          continue;
        }
        await this.state.storage.put(`story:${story.story_id}`, story);
        this.index[story.story_id] = toPreview(story);
        upserted.push(this.index[story.story_id]);
      }

      if (!upserted.length) {
        return jsonResponse({ error: "All stories were invalid" }, 400);
      }

      const previews = Object.values(this.index);
      const strong = previews.filter((x) => x.publication_tier === "strong").length;
      const candidate = previews.length - strong;
      this.metrics = {
        total: previews.length,
        strong,
        candidate,
        last_ingest_at: now,
      };

      await this.state.storage.put("index", this.index);
      await this.state.storage.put("metrics", this.metrics);

      this.broadcast({
        type: "stories.upsert",
        stories: upserted,
        metrics: this.metrics,
      });

      return jsonResponse({ upserted: upserted.length, metrics: this.metrics });
    }

    if (path === "/subscribe" && request.method === "GET") {
      if ((request.headers.get("upgrade") ?? "").toLowerCase() !== "websocket") {
        return new Response("Expected WebSocket", { status: 426 });
      }

      const pair = new WebSocketPair();
      const client = pair[0];
      const server = pair[1];
      server.accept();

      const socketRecord = { socket: server };
      this.sockets.add(socketRecord);

      server.send(
        JSON.stringify({
          type: "hello",
          metrics: this.metrics,
        }),
      );

      server.addEventListener("message", (event) => {
        if (event.data === "ping") {
          try {
            server.send("pong");
          } catch {
            this.sockets.delete(socketRecord);
          }
        }
      });

      const cleanup = () => {
        this.sockets.delete(socketRecord);
      };

      server.addEventListener("close", cleanup);
      server.addEventListener("error", cleanup);

      return new Response(null, { status: 101, webSocket: client });
    }

    return routeNotFound();
  }

  broadcast(payload) {
    const encoded = JSON.stringify(payload);
    for (const entry of this.sockets) {
      try {
        entry.socket.send(encoded);
      } catch {
        this.sockets.delete(entry);
      }
    }
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/healthz") {
      return jsonResponse({ ok: true, service: "live-story-visualizer" });
    }

    const hubId = env.STORY_HUB.idFromName(HUB_NAME);
    const hub = env.STORY_HUB.get(hubId);

    if (url.pathname === "/api/stories" && request.method === "GET") {
      return hub.fetch(`https://story-hub/stories${url.search}`);
    }

    if (url.pathname.startsWith("/api/stories/") && request.method === "GET") {
      const storyId = url.pathname.slice("/api/stories/".length);
      return hub.fetch(`https://story-hub/story/${encodeURIComponent(storyId)}`);
    }

    if (url.pathname === "/api/metrics" && request.method === "GET") {
      return hub.fetch("https://story-hub/metrics");
    }

    if (url.pathname === "/api/ingest" && request.method === "POST") {
      if (!requireBearerToken(request, env)) {
        return jsonResponse({ error: "Unauthorized" }, 401);
      }
      return hub.fetch(new Request("https://story-hub/ingest", request));
    }

    if (url.pathname === "/ws" && request.method === "GET") {
      return hub.fetch(new Request("https://story-hub/subscribe", request));
    }

    if (url.pathname.startsWith("/api/")) {
      return routeNotFound();
    }

    return env.ASSETS.fetch(request);
  },
};
