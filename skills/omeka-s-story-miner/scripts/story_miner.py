#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
import re
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List


SEED_TYPE_WEIGHT = {"PLACE": 1.4, "ORG": 1.2, "PERSON": 1.0, "CONCEPT": 0.9}
THEME_DEFAULT = "spatial-political-relations"
UNRESOLVED_CODE_RE = re.compile(r"^[A-Za-z]{1,5}\.[A-Za-z]{1,8}\.\d{2,}$")
BORING_EXACT = {
    "israel",
    "ישראל",
    "jerusalem",
    "ירושלים",
    "palestine",
    "פלסטין",
    "palestinian authority",
    "הרשות הפלסטינית",
}
ARCHIVE_MARKERS = {"archive", "collection", "fonds", "catalog", "אוסף", "ארכיון"}
TOKEN_RE = re.compile(r"[\w\u0590-\u05FF\u0600-\u06FF]+", flags=re.UNICODE)
NUMERIC_LABEL_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
PLACEHOLDER_LABELS = {"none", "unknown", "n/a", "null", "untitled", "-"}


def fold_text(text: str) -> str:
    return str(text or "").strip().casefold()


def token_set(text: str) -> set:
    return {t for t in TOKEN_RE.findall(fold_text(text)) if t}


def label_is_archive_like(label: str) -> bool:
    folded = fold_text(label)
    if not folded:
        return False
    return any(marker in folded for marker in ARCHIVE_MARKERS)


def boring_penalty(label: str, entity_type: str, mention_count: int, archive_label_tokens: List[set]) -> float:
    folded = fold_text(label)
    tokens = token_set(label)
    if not folded:
        return 0.4
    if folded in PLACEHOLDER_LABELS:
        return 0.1
    if NUMERIC_LABEL_RE.match(folded):
        return 0.2
    if folded in BORING_EXACT:
        return 0.1
    if tokens & BORING_EXACT:
        return 0.1
    if label_is_archive_like(folded):
        return 0.3
    for archive_tokens in archive_label_tokens:
        if not archive_tokens:
            continue
        if tokens == archive_tokens:
            return 0.25
        if len(tokens & archive_tokens) >= max(2, len(archive_tokens)):
            return 0.25
    if entity_type == "PLACE" and mention_count >= 40:
        return 0.55
    return 1.0


def non_trivial_entity_boost(labels: List[str]) -> float:
    if not labels:
        return 0.0
    non_trivial = [
        x
        for x in labels
        if not is_unresolved_label(x) and fold_text(x) not in BORING_EXACT and not label_is_archive_like(x)
    ]
    ratio = len(non_trivial) / max(1, len(labels))
    return round((len(non_trivial) * 0.25) + (ratio * 2.0), 4)


def jsonl_read(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def jsonl_write(path: Path, rows: List[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_history(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_history(path: Path, history: Dict[str, dict]) -> None:
    path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def top_entities(entities: List[dict], cooccurs: List[dict], mentions: List[dict]) -> List[dict]:
    mention_count = Counter(m.get("entity_id") for m in mentions if m.get("entity_id"))
    total_docs = max(1, len({m.get("doc_id") for m in mentions if m.get("doc_id")}))
    source_diversity = defaultdict(set)
    doc_diversity = defaultdict(set)
    for m in mentions:
        eid = m.get("entity_id")
        if not eid:
            continue
        source_diversity[eid].add(m.get("source_archive", "unknown"))
        doc_diversity[eid].add(m.get("doc_id"))
    archive_labels = set()
    for m in mentions:
        src = str(m.get("source_archive", "")).strip()
        if not src or src == "unknown":
            continue
        for part in src.split("|"):
            val = part.strip()
            if val:
                archive_labels.add(val)
    archive_label_tokens = [token_set(x) for x in archive_labels]
    degree = Counter()
    for c in cooccurs:
        a = c.get("source_entity_id")
        b = c.get("target_entity_id")
        w = float(c.get("weight", 0))
        if a:
            degree[a] += w
        if b:
            degree[b] += w
    scored = []
    for e in entities:
        eid = e.get("entity_id")
        if not eid:
            continue
        t = e.get("entity_type", "CONCEPT")
        mentions_n = int(mention_count.get(eid, 0))
        degree_n = float(degree.get(eid, 0))
        src_n = len([s for s in source_diversity.get(eid, set()) if s and s != "unknown"])
        doc_n = len(doc_diversity.get(eid, set()))
        mention_term = math.log1p(mentions_n)
        degree_term = math.log1p(degree_n)
        doc_term = math.log1p(doc_n)
        doc_coverage = doc_n / total_docs
        base = (
            degree_term * 2.3
            + doc_term * 1.8
            + mention_term * 0.5
            + float(src_n) * 0.9
            + float(SEED_TYPE_WEIGHT.get(t, 1.0)) * 2.2
        )
        label = str(e.get("label", "")).strip()
        penalty = boring_penalty(
            label=label,
            entity_type=t,
            mention_count=mentions_n,
            archive_label_tokens=archive_label_tokens,
        )
        ubiquity_penalty = 1.0
        rarity_boost = 1.0
        if doc_coverage >= 0.20:
            ubiquity_penalty = 0.35
        elif doc_coverage >= 0.10:
            ubiquity_penalty = 0.55
        elif doc_coverage >= 0.05:
            ubiquity_penalty = 0.75
        elif doc_coverage <= 0.01 and doc_n >= 2:
            rarity_boost = 1.15
        score = base * penalty * ubiquity_penalty * rarity_boost
        e = dict(e)
        e["_seed_score"] = round(score, 5)
        e["_seed_penalty"] = penalty
        e["_seed_mentions"] = mentions_n
        e["_seed_docs"] = doc_n
        e["_seed_doc_coverage"] = round(doc_coverage, 6)
        e["_seed_ubiquity_penalty"] = ubiquity_penalty
        scored.append((score, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored]


def build_cluster(seed: dict, mentions_by_entity: Dict[str, List[dict]], co_by_entity: Dict[str, List[dict]], docs: Dict[str, dict]) -> dict:
    seed_id = seed["entity_id"]
    neighbors = []
    for edge in co_by_entity.get(seed_id, []):
        src = edge.get("source_entity_id")
        dst = edge.get("target_entity_id")
        other = dst if src == seed_id else src
        neighbors.append((float(edge.get("weight", 0)), other, edge))
    neighbors.sort(key=lambda x: x[0], reverse=True)
    top_neighbors = neighbors[:8]

    entity_ids = {seed_id}
    graph_paths = []
    for weight, other, edge in top_neighbors:
        if other:
            entity_ids.add(other)
            graph_paths.append(
                {
                    "from": seed_id,
                    "to": other,
                    "weight": weight,
                    "doc_count": edge.get("doc_count", 0),
                }
            )

    evidence = []
    source_archives = set()
    doc_ids = set()
    for entity_id in entity_ids:
        for mention in mentions_by_entity.get(entity_id, [])[:20]:
            doc_id = mention.get("doc_id")
            doc = docs.get(doc_id, {})
            source_archive = mention.get("source_archive") or doc.get("source_archive", "unknown")
            source_archives.add(source_archive)
            doc_ids.add(doc_id)
            evidence.append(
                {
                    "doc_id": doc_id,
                    "quote_or_field": (
                        f"Document '{doc.get('title','')}' links '{mention.get('surface','')}' "
                        f"via {mention.get('field_key','')}."
                    ).strip(),
                    "evidence_title": (
                        f"{doc.get('title','Untitled')} -> {mention.get('field_key','field')} -> "
                        f"{mention.get('surface','value')}"
                    ),
                    "endpoint": mention.get("resource"),
                    "uri": mention.get("admin_url") or doc.get("admin_url") or mention.get("uri") or doc.get("uri", ""),
                    "timestamp": mention.get("evidence_time") or doc.get("evidence_time") or "",
                    "source_archive": source_archive,
                }
            )

    evidence = evidence[:40]
    return {
        "seed_entity_id": seed_id,
        "cluster_entity_ids": sorted(entity_ids),
        "doc_ids": sorted(d for d in doc_ids if d),
        "graph_paths": graph_paths,
        "evidence": evidence,
        "cross_source_count": len([s for s in source_archives if s and s != "unknown"]),
    }


def novelty_score(cluster: dict, history: Dict[str, dict]) -> float:
    signature = "|".join(cluster["cluster_entity_ids"][:10]) + "|" + "|".join(cluster["doc_ids"][:10])
    sig_hash = hashlib.sha1(signature.encode("utf-8")).hexdigest()
    cluster["signature_hash"] = sig_hash
    if sig_hash not in history:
        return 1.0
    prev = history[sig_hash]
    prev_docs = set(prev.get("doc_ids", []))
    curr_docs = set(cluster.get("doc_ids", []))
    if not prev_docs:
        return 0.5
    overlap = len(prev_docs & curr_docs) / max(1, len(prev_docs | curr_docs))
    return round(1.0 - overlap, 4)


def quality_score(cluster: dict, novelty: float) -> float:
    evidence_links = len(cluster.get("evidence", []))
    cross_source = int(cluster.get("cross_source_count", 0))
    path_strength = sum(float(p.get("weight", 0)) for p in cluster.get("graph_paths", []))
    seed_penalty = float(cluster.get("seed_penalty", 1.0))
    labels = cluster.get("resolved_entity_labels", [])
    non_trivial_boost = non_trivial_entity_boost(labels)
    score = (
        evidence_links * 0.3
        + cross_source * 2.0
        + path_strength * 0.2
        + novelty * 3.0
        + non_trivial_boost
    ) * seed_penalty
    return round(score, 4)


def build_story_candidate(
    cluster: dict,
    seed: dict,
    entities_by_id: Dict[str, dict],
    mentions_by_entity: Dict[str, List[dict]],
    docs_by_id: Dict[str, dict],
    theme: str,
    history: Dict[str, dict],
) -> dict:
    novelty = novelty_score(cluster, history)
    score = quality_score(cluster, novelty)
    entity_rows = []
    resolved_labels = {}
    resolved_label_list = []
    for eid in cluster["cluster_entity_ids"]:
        e = entities_by_id.get(eid, {})
        label = resolve_entity_label(e, mentions_by_entity, docs_by_id)
        if not label:
            continue
        resolved_labels[eid] = label
        resolved_label_list.append(label)
        entity_rows.append(
            {
                "id": eid,
                "label": label,
                "type": e.get("entity_type", "CONCEPT"),
                "aliases": e.get("aliases", []),
                "language": e.get("primary_language", "und"),
                "confidence": e.get("confidence", 0.0),
            }
        )

    resolved_seed_label = resolve_entity_label(seed, mentions_by_entity, docs_by_id) or ""
    if not resolved_seed_label:
        return None

    resolved_seed_penalty = boring_penalty(
        label=resolved_seed_label,
        entity_type=seed.get("entity_type", "CONCEPT"),
        mention_count=int(seed.get("_seed_mentions", 0)),
        archive_label_tokens=[],
    )
    score = round(score * resolved_seed_penalty, 4)

    title = f"{resolved_seed_label} and cross-archive spatial-political links"
    summary_facts = [
        f"The cluster contains {len(cluster['cluster_entity_ids'])} linked entities around seed '{seed.get('label','')}'.",
        f"Evidence was found in {len(cluster.get('evidence', []))} mentions across {cluster.get('cross_source_count', 0)} source archives.",
        f"The strongest co-occurrence path count is {len(cluster.get('graph_paths', []))} between place/actor nodes.",
    ]
    hypotheses = [
        "This cluster may reveal planning relations crossing communal or institutional boundaries.",
        "Contested or parallel naming patterns may indicate narrative divergence rather than data duplication.",
    ]
    cluster["resolved_entity_labels"] = resolved_label_list

    return {
        "story_id": "cand_" + cluster["signature_hash"][:12],
        "signature_hash": cluster["signature_hash"],
        "title": title,
        "theme": theme,
        "seed_entity_id": seed.get("entity_id"),
        "seed_label": resolved_seed_label,
        "quality_score": score,
        "novelty_score": novelty,
        "seed_score": seed.get("_seed_score", 0.0),
        "seed_penalty": round(float(seed.get("_seed_penalty", 1.0)) * float(resolved_seed_penalty), 4),
        "summary_facts": summary_facts,
        "hypotheses": hypotheses,
        "entities": entity_rows,
        "relationships": [
            {
                "source_entity": p.get("from"),
                "relation": "CO_OCCURS",
                "target_entity": p.get("to"),
                "source_label": resolved_labels.get(p.get("from"), ""),
                "target_label": resolved_labels.get(p.get("to"), ""),
                "confidence": min(1.0, 0.55 + (float(p.get("weight", 0)) * 0.05)),
            }
            for p in cluster.get("graph_paths", [])
        ],
        "evidence": cluster.get("evidence", []),
        "graph_paths": cluster.get("graph_paths", []),
        "uncertainty_notes": [
            "Entity alignment preserves multilingual aliases and contested names.",
            "Hypotheses are exploratory and require archival validation.",
        ],
        "viz_hints": {
            "recommended_seed": seed.get("entity_id"),
            "timeline_bins": "decade",
            "map_anchor_entities": [e["id"] for e in entity_rows if e.get("type") == "PLACE"][:5],
            "edge_focus": "cross_source_bridges",
        },
        "doc_ids": cluster.get("doc_ids", []),
        "cross_source_count": cluster.get("cross_source_count", 0),
    }


def is_unresolved_label(label: str) -> bool:
    if not label:
        return True
    txt = str(label).strip()
    if not txt:
        return True
    if txt.casefold() in PLACEHOLDER_LABELS:
        return True
    if NUMERIC_LABEL_RE.match(txt):
        return True
    if UNRESOLVED_CODE_RE.match(txt):
        return True
    return False


def resolve_entity_label(entity: dict, mentions_by_entity: Dict[str, List[dict]], docs_by_id: Dict[str, dict]) -> str:
    label = str(entity.get("label", "")).strip()
    aliases = [str(a).strip() for a in (entity.get("aliases") or []) if str(a).strip()]

    if not is_unresolved_label(label):
        return label

    for alias in aliases:
        if not is_unresolved_label(alias):
            return alias

    entity_id = entity.get("entity_id")
    for m in mentions_by_entity.get(entity_id, []):
        doc = docs_by_id.get(m.get("doc_id"), {})
        title = str(doc.get("title", "")).strip()
        if title and not is_unresolved_label(title):
            return title
    return ""


def parse_response_text(resp: dict) -> str:
    try:
        out = resp.get("output", [])
        parts = []
        for item in out:
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    parts.append(text)
        if parts:
            return "\n".join(parts).strip()
    except Exception:
        pass
    return ""


def refine_with_openai(candidate: dict, api_key: str, model: str) -> dict:
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a historical research assistant. Return JSON only with keys "
                    "`summary_facts` (array of 3 concise evidence-grounded facts) and "
                    "`hypotheses` (array of 2 clearly speculative hypotheses). "
                    "Never invent uncited sources."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "title": candidate.get("title"),
                        "theme": candidate.get("theme"),
                        "evidence": candidate.get("evidence", [])[:15],
                        "graph_paths": candidate.get("graph_paths", [])[:10],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        body = r.read().decode("utf-8")
    resp = json.loads(body)
    text = parse_response_text(resp)
    if not text:
        return candidate
    try:
        parsed = json.loads(text)
        if isinstance(parsed.get("summary_facts"), list) and parsed.get("summary_facts"):
            candidate["summary_facts"] = [str(x) for x in parsed["summary_facts"][:5]]
        if isinstance(parsed.get("hypotheses"), list) and parsed.get("hypotheses"):
            candidate["hypotheses"] = [str(x) for x in parsed["hypotheses"][:5]]
    except Exception:
        return candidate
    candidate.setdefault("uncertainty_notes", []).append("Narrative phrasing refined by external LLM.")
    return candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover story candidates from graph snapshots")
    parser.add_argument("--graph-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--story-count", type=int, default=15)
    parser.add_argument("--theme", default=THEME_DEFAULT)
    parser.add_argument("--history-path", default="")
    parser.add_argument("--llm-provider", choices=["template", "openai"], default="template")
    parser.add_argument("--llm-model", default="gpt-4.1-mini")
    parser.add_argument("--openai-api-key", default=os.getenv("OPENAI_API_KEY", ""))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    graph_dir = Path(args.graph_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    entities = jsonl_read(graph_dir / "graph_entities.jsonl")
    docs = jsonl_read(graph_dir / "graph_docs.jsonl")
    mentions = jsonl_read(graph_dir / "graph_mentions.jsonl")
    cooccurs = jsonl_read(graph_dir / "graph_cooccurs.jsonl")

    entities_by_id = {e.get("entity_id"): e for e in entities if e.get("entity_id")}
    docs_by_id = {d.get("doc_id"): d for d in docs if d.get("doc_id")}
    mentions_by_entity = defaultdict(list)
    for m in mentions:
        mentions_by_entity[m.get("entity_id")].append(m)
    co_by_entity = defaultdict(list)
    for c in cooccurs:
        co_by_entity[c.get("source_entity_id")].append(c)
        co_by_entity[c.get("target_entity_id")].append(c)

    history_path = Path(args.history_path) if args.history_path else (output_dir / "story_history.json")
    history = load_history(history_path)

    ranked_entities = top_entities(entities, cooccurs, mentions)
    candidates = []
    used_signatures = set()
    for seed in ranked_entities:
        cluster = build_cluster(seed, mentions_by_entity, co_by_entity, docs_by_id)
        cluster["seed_penalty"] = float(seed.get("_seed_penalty", 1.0))
        candidate = build_story_candidate(
            cluster,
            seed,
            entities_by_id,
            mentions_by_entity,
            docs_by_id,
            args.theme,
            history,
        )
        if not candidate:
            continue
        if args.llm_provider == "openai" and args.openai_api_key:
            try:
                candidate = refine_with_openai(candidate, api_key=args.openai_api_key, model=args.llm_model)
            except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError):
                candidate.setdefault("uncertainty_notes", []).append("External LLM refinement failed; kept template narrative.")
        seed_label = candidate.get("seed_label", "")
        if is_unresolved_label(seed_label):
            continue
        sig = candidate["story_id"]
        if sig in used_signatures:
            continue
        used_signatures.add(sig)
        candidates.append(candidate)
        if len(candidates) >= args.story_count:
            break

    candidates.sort(key=lambda x: (x["quality_score"], x["novelty_score"]), reverse=True)
    jsonl_write(output_dir / "story_candidates.jsonl", candidates)

    for c in candidates:
        history[c["signature_hash"]] = {"doc_ids": c.get("doc_ids", []), "title": c.get("title")}
    save_history(history_path, history)

    summary = {
        "graph_dir": str(graph_dir),
        "stories_emitted": len(candidates),
        "story_count_target": args.story_count,
        "theme": args.theme,
        "history_path": str(history_path),
        "ranking_note": "boring entities (Israel/Jerusalem/archive-like labels) are penalized",
    }
    (output_dir / "story_miner_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
