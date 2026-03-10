const storyListEl = document.getElementById("story-list");
const tierFilterEl = document.getElementById("tier-filter");
const statusDotEl = document.getElementById("live-status");
const statusLabelEl = document.getElementById("live-status-label");
const storyTitleEl = document.getElementById("story-title");
const storySubtitleEl = document.getElementById("story-subtitle");
const factsListEl = document.getElementById("facts-list");
const hypothesesListEl = document.getElementById("hypotheses-list");
const evidenceListEl = document.getElementById("evidence-list");

const metricTotalEl = document.getElementById("metric-total");
const metricStrongEl = document.getElementById("metric-strong");
const metricCandidateEl = document.getElementById("metric-candidate");
const metricLastEl = document.getElementById("metric-last");

const graphChart = echarts.init(document.getElementById("graph-chart"));
const timelineChart = echarts.init(document.getElementById("timeline-chart"));

const state = {
  previews: [],
  selectedStoryId: "",
  selectedStory: null,
  metrics: { total: 0, strong: 0, candidate: 0, last_ingest_at: "" },
};

let socket;
let socketRetryMs = 1000;

function htmlEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setLiveStatus(isOnline, label) {
  statusDotEl.classList.toggle("online", isOnline);
  statusDotEl.classList.toggle("offline", !isOnline);
  statusLabelEl.textContent = label;
}

function formatTimestamp(ts) {
  if (!ts) {
    return "-";
  }
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) {
    return ts;
  }
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function updateMetrics(metrics) {
  state.metrics = { ...state.metrics, ...(metrics ?? {}) };
  metricTotalEl.textContent = String(state.metrics.total ?? 0);
  metricStrongEl.textContent = String(state.metrics.strong ?? 0);
  metricCandidateEl.textContent = String(state.metrics.candidate ?? 0);
  metricLastEl.textContent = formatTimestamp(state.metrics.last_ingest_at);
}

async function fetchJSON(url) {
  const response = await fetch(url, { headers: { accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

function sortPreviews(rows) {
  return [...rows].sort((a, b) => {
    const byPublished = String(b.published_at ?? "").localeCompare(String(a.published_at ?? ""));
    if (byPublished !== 0) {
      return byPublished;
    }
    return Number(b.quality_score ?? 0) - Number(a.quality_score ?? 0);
  });
}

function previewVisible(preview) {
  const filter = tierFilterEl.value;
  if (filter === "all") {
    return true;
  }
  return preview.publication_tier === filter;
}

function renderFeed() {
  const visible = sortPreviews(state.previews).filter(previewVisible);

  if (!visible.length) {
    storyListEl.innerHTML = "<li>No stories available yet.</li>";
    return;
  }

  storyListEl.innerHTML = visible
    .map((row) => {
      const isActive = row.story_id === state.selectedStoryId;
      const badgeClass = row.publication_tier === "strong" ? "strong" : "candidate";
      return `
        <li class="${isActive ? "active" : ""}" data-story-id="${htmlEscape(row.story_id)}">
          <p class="feed-title">${htmlEscape(row.title ?? "Untitled story")}</p>
          <div class="feed-meta">
            <span class="tier-pill ${badgeClass}">${htmlEscape(row.publication_tier)}</span>
            <span> score ${Number(row.quality_score ?? 0).toFixed(1)}</span>
            <span> · evidence ${htmlEscape(row.evidence_count ?? 0)}</span>
          </div>
          <div class="feed-meta">${htmlEscape(formatTimestamp(row.published_at))}</div>
        </li>
      `;
    })
    .join("");
}

function renderList(values, container, fallback) {
  const rows = Array.isArray(values) ? values : [];
  if (!rows.length) {
    container.innerHTML = `<li>${htmlEscape(fallback)}</li>`;
    return;
  }
  container.innerHTML = rows.map((item) => `<li>${htmlEscape(item)}</li>`).join("");
}

function renderEvidence(evidence) {
  const rows = Array.isArray(evidence) ? evidence.slice(0, 18) : [];
  if (!rows.length) {
    evidenceListEl.innerHTML = "<li>No evidence available.</li>";
    return;
  }

  evidenceListEl.innerHTML = rows
    .map((ev) => {
      const source = htmlEscape(ev.source_archive || "unknown source");
      const quote = htmlEscape(ev.quote_or_field || "");
      const timestamp = htmlEscape(formatTimestamp(ev.timestamp));
      const uri = ev.uri ? `<a href="${htmlEscape(ev.uri)}" target="_blank" rel="noreferrer">source</a>` : "";
      return `<li><strong>${source}</strong>: ${quote}<br/><small>${timestamp} ${uri}</small></li>`;
    })
    .join("");
}

function renderGraph(story) {
  if (!story) {
    graphChart.setOption(
      {
        title: { text: "No story selected", left: "center", top: "middle", textStyle: { fontFamily: "Fraunces" } },
        series: [],
      },
      true,
    );
    return;
  }

  const entities = Array.isArray(story.entities) ? story.entities : [];
  const relationships = Array.isArray(story.relationships) ? story.relationships : [];

  const byId = new Map(entities.map((entity) => [entity.id, entity]));
  const colorByType = {
    PLACE: "#1f7a6f",
    ORG: "#b85f2f",
    PERSON: "#3b6797",
    CONCEPT: "#7a5068",
  };

  const nodes = entities.map((entity) => ({
    id: entity.id,
    name: entity.label || entity.id,
    value: Number(entity.confidence ?? 0),
    symbolSize: 26 + Math.round((Number(entity.confidence ?? 0.2) || 0.2) * 22),
    itemStyle: { color: colorByType[entity.type] || "#567" },
    category: entity.type || "CONCEPT",
  }));

  const links = relationships.map((rel) => ({
    source: rel.source_entity,
    target: rel.target_entity,
    value: Number(rel.confidence ?? 0),
    lineStyle: { width: 1 + Number(rel.confidence ?? 0) * 3, opacity: 0.75 },
    label: { show: false },
  }));

  const categories = [...new Set(nodes.map((n) => n.category))].map((name) => ({ name }));

  graphChart.setOption(
    {
      animationDuration: 650,
      tooltip: {
        trigger: "item",
        formatter(params) {
          if (params.dataType === "edge") {
            return `link confidence ${Number(params.data.value ?? 0).toFixed(2)}`;
          }
          const entity = byId.get(params.data.id) || {};
          return `${htmlEscape(entity.label || params.data.name)}<br/>type: ${htmlEscape(entity.type || "unknown")}`;
        },
      },
      legend: [{ top: 4, data: categories.map((c) => c.name) }],
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          draggable: true,
          categories,
          data: nodes,
          links,
          force: {
            edgeLength: [80, 150],
            repulsion: 190,
            gravity: 0.06,
          },
          label: { show: true, fontSize: 11 },
          lineStyle: { color: "source" },
          emphasis: { focus: "adjacency" },
        },
      ],
    },
    true,
  );
}

function renderTimeline(story) {
  if (!story) {
    timelineChart.setOption({ title: { text: "No timeline", left: "center", top: "middle" }, series: [] }, true);
    return;
  }

  const evidence = Array.isArray(story.evidence) ? story.evidence : [];
  const byDay = new Map();
  for (const row of evidence) {
    const raw = row.timestamp;
    if (!raw) {
      continue;
    }
    const day = String(raw).slice(0, 10);
    byDay.set(day, (byDay.get(day) || 0) + 1);
  }

  const sortedDays = [...byDay.keys()].sort();
  const values = sortedDays.map((day) => byDay.get(day));

  timelineChart.setOption(
    {
      animationDuration: 600,
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: sortedDays,
        axisLabel: { rotate: 35 },
      },
      yAxis: { type: "value", minInterval: 1 },
      grid: { left: 52, right: 18, bottom: 44, top: 30 },
      series: [
        {
          type: "bar",
          data: values,
          itemStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "#1f7a6f" },
                { offset: 1, color: "#87c8b8" },
              ],
            },
          },
        },
      ],
    },
    true,
  );
}

function renderStory(story) {
  state.selectedStory = story;
  if (!story) {
    storyTitleEl.textContent = "Select a story";
    storySubtitleEl.textContent = "Choose a story from the feed to inspect entities and evidence.";
    renderList([], factsListEl, "No facts available.");
    renderList([], hypothesesListEl, "No hypotheses available.");
    renderEvidence([]);
    renderGraph(null);
    renderTimeline(null);
    return;
  }

  storyTitleEl.textContent = story.title || "Untitled story";
  storySubtitleEl.textContent = `${story.theme || "unknown"} · ${story.publication_tier || "candidate"} · score ${Number(story.quality_score || 0).toFixed(1)}`;

  renderList(story.summary_facts, factsListEl, "No facts available.");
  renderList(story.hypotheses, hypothesesListEl, "No hypotheses available.");
  renderEvidence(story.evidence);
  renderGraph(story);
  renderTimeline(story);
}

async function loadStoryDetail(storyId) {
  try {
    const payload = await fetchJSON(`/api/stories/${encodeURIComponent(storyId)}`);
    renderStory(payload.story ?? null);
  } catch {
    renderStory(null);
  }
}

async function ensureSelectedStory() {
  const visible = sortPreviews(state.previews).filter(previewVisible);
  if (!visible.length) {
    state.selectedStoryId = "";
    renderStory(null);
    return;
  }

  const stillVisible = visible.find((item) => item.story_id === state.selectedStoryId);
  const next = stillVisible ?? visible[0];
  if (next.story_id !== state.selectedStoryId) {
    state.selectedStoryId = next.story_id;
    await loadStoryDetail(next.story_id);
  }
}

function mergePreviews(nextRows) {
  const map = new Map(state.previews.map((row) => [row.story_id, row]));
  for (const row of nextRows) {
    map.set(row.story_id, { ...map.get(row.story_id), ...row });
  }
  state.previews = [...map.values()];
}

async function loadFeed() {
  const query = tierFilterEl.value === "all" ? "" : `&tier=${encodeURIComponent(tierFilterEl.value)}`;
  const payload = await fetchJSON(`/api/stories?limit=250${query}`);

  state.previews = Array.isArray(payload.stories) ? payload.stories : [];
  updateMetrics(payload.metrics);
  renderFeed();
  await ensureSelectedStory();
}

async function tryBootstrapFallback() {
  try {
    const payload = await fetchJSON("/data/bootstrap_stories.json");
    if (!Array.isArray(payload?.stories) || !payload.stories.length) {
      return false;
    }

    const stories = payload.stories;
    state.previews = stories.map((story) => ({
      story_id: story.story_id,
      title: story.title,
      theme: story.theme,
      publication_tier: story.publication_tier,
      quality_score: story.quality_score,
      cross_source_count: story.cross_source_count,
      evidence_count: story.evidence_count,
      published_at: story.published_at || story?.time_window?.max || "",
      ingested_at: story.ingested_at || "",
      location_scope: story.location_scope || [],
      time_window: story.time_window || { min: "", max: "" },
    }));

    updateMetrics(payload.metrics ?? { total: stories.length, strong: stories.length, candidate: 0 });
    renderFeed();

    if (!state.selectedStoryId && state.previews.length) {
      state.selectedStoryId = state.previews[0].story_id;
    }

    const selected = stories.find((s) => s.story_id === state.selectedStoryId) || stories[0];
    renderStory(selected);
    setLiveStatus(false, "Demo mode (bootstrap data)");
    return true;
  } catch {
    return false;
  }
}

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const endpoint = `${protocol}://${window.location.host}/ws`;
  socket = new WebSocket(endpoint);

  socket.addEventListener("open", () => {
    setLiveStatus(true, "Live");
    socketRetryMs = 1000;
  });

  socket.addEventListener("message", async (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }

    if (payload.type === "hello") {
      updateMetrics(payload.metrics);
      return;
    }

    if (payload.type === "stories.upsert") {
      const upserts = Array.isArray(payload.stories) ? payload.stories : [];
      if (upserts.length) {
        mergePreviews(upserts);
        renderFeed();

        if (!state.selectedStoryId) {
          state.selectedStoryId = upserts[0].story_id;
          await loadStoryDetail(state.selectedStoryId);
        }

        if (upserts.some((s) => s.story_id === state.selectedStoryId)) {
          await loadStoryDetail(state.selectedStoryId);
        }
      }
      updateMetrics(payload.metrics);
    }
  });

  socket.addEventListener("close", () => {
    setLiveStatus(false, "Reconnecting…");
    setTimeout(connectWebSocket, socketRetryMs);
    socketRetryMs = Math.min(Math.round(socketRetryMs * 1.8), 16000);
  });

  socket.addEventListener("error", () => {
    socket.close();
  });
}

async function boot() {
  window.addEventListener("resize", () => {
    graphChart.resize();
    timelineChart.resize();
  });

  tierFilterEl.addEventListener("change", async () => {
    try {
      await loadFeed();
    } catch {
      renderFeed();
    }
  });

  storyListEl.addEventListener("click", async (event) => {
    const row = event.target.closest("li[data-story-id]");
    if (!row) {
      return;
    }
    state.selectedStoryId = row.getAttribute("data-story-id") || "";
    renderFeed();

    const maybeCached = state.selectedStory;
    if (maybeCached?.story_id === state.selectedStoryId) {
      return;
    }

    try {
      await loadStoryDetail(state.selectedStoryId);
    } catch {
      renderStory(null);
    }
  });

  try {
    await loadFeed();
    connectWebSocket();
    setInterval(async () => {
      try {
        await loadFeed();
      } catch {
        // polling fallback keeps UI fresh if websocket disconnects.
      }
    }, 30000);
  } catch {
    const loaded = await tryBootstrapFallback();
    if (!loaded) {
      setLiveStatus(false, "Unavailable");
      renderStory(null);
    }
  }
}

boot();
