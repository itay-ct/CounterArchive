#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from typing import List

YEAR_RE = re.compile(r"(1[0-9]{3}|20[0-9]{2})")


def jsonl_read(path: Path) -> List[dict]:
    rows = []
    if not path.exists():
        return rows
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


def story_contract(candidate: dict, strong: bool) -> dict:
    story_id = candidate.get("story_id")
    cross_source_count = int(candidate.get("cross_source_count", 0))
    evidence = candidate.get("evidence", [])
    relationships = candidate.get("relationships", [])
    entities = candidate.get("entities", [])

    location_scope = [e.get("label") for e in entities if e.get("type") == "PLACE"][:8]
    timestamps = [str(e.get("timestamp", "")).strip() for e in evidence if str(e.get("timestamp", "")).strip()]
    years = []
    for ts in timestamps:
        m = YEAR_RE.search(ts)
        if m:
            years.append(int(m.group(1)))
    time_window = {
        "min": min(years) if years else "",
        "max": max(years) if years else "",
        "raw_min": min(timestamps) if timestamps else "",
        "raw_max": max(timestamps) if timestamps else "",
    }

    return {
        "story_id": story_id,
        "title": candidate.get("title"),
        "theme": candidate.get("theme"),
        "time_window": time_window,
        "location_scope": location_scope,
        "summary_facts": candidate.get("summary_facts", []),
        "hypotheses": candidate.get("hypotheses", []),
        "entities": entities,
        "relationships": relationships,
        "evidence": evidence,
        "graph_paths": candidate.get("graph_paths", []),
        "uncertainty_notes": candidate.get("uncertainty_notes", []),
        "viz_hints": candidate.get("viz_hints", {}),
        "quality_score": candidate.get("quality_score", 0),
        "cross_source_count": cross_source_count,
        "evidence_count": len(evidence),
        "publication_tier": "strong" if strong else "candidate",
        "publishable": True,
    }


def markdown_for_story(story: dict) -> str:
    facts = "\n".join(f"- {x}" for x in story.get("summary_facts", [])) or "- No facts extracted"
    hypotheses = "\n".join(f"- {x}" for x in story.get("hypotheses", [])) or "- No hypotheses generated"
    rel_rows = []
    for r in story.get("relationships", [])[:10]:
        src = r.get("source_label") or r.get("source_entity")
        dst = r.get("target_label") or r.get("target_entity")
        rel_rows.append(
            f"- `{src}` --{r.get('relation')}--> `{dst}` (confidence={round(float(r.get('confidence',0)),3)})"
        )
    relationships = "\n".join(rel_rows) or "- No relationships"
    evidence_rows = []
    for ev in story.get("evidence", [])[:12]:
        uri = ev.get("uri", "")
        title = ev.get("evidence_title") or ev.get("quote_or_field") or "Evidence"
        if uri:
            evidence_rows.append(f"- [{title}]({uri})")
        else:
            evidence_rows.append(f"- {title}")
    evidence_md = "\n".join(evidence_rows) or "- No evidence rows"
    sources = sorted(set(e.get("source_archive", "unknown") for e in story.get("evidence", [])))
    source_line = ", ".join(sources) if sources else "unknown"
    return (
        f"# {story.get('title','Untitled Story')}\n\n"
        f"## Why this matters\n"
        f"This story links entities across {story.get('cross_source_count',0)} source clusters and preserves contested naming context.\n\n"
        f"## Verified facts\n{facts}\n\n"
        f"## Hypotheses to investigate next\n{hypotheses}\n\n"
        f"## Key entities and relationships\n{relationships}\n\n"
        f"## Evidence highlights\n{evidence_md}\n\n"
        f"## Suggested visualization framing\n"
        f"- Theme: `{story.get('theme')}`\n"
        f"- Location anchors: {', '.join(story.get('location_scope',[])[:8]) or 'n/a'}\n"
        f"- Timeline (evidence time): {story.get('time_window',{}).get('min','')} -> {story.get('time_window',{}).get('max','')}\n"
        f"- Source archives: {source_line}\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Package story candidates into JSON + Markdown artifacts")
    parser.add_argument("--input-candidates", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-evidence-links", type=int, default=3)
    parser.add_argument("--min-cross-source", type=int, default=2)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = jsonl_read(Path(args.input_candidates))
    manifest = []
    strong_count = 0
    orphan_evidence = 0
    total_evidence = 0

    for cand in candidates:
        evidence_count = len(cand.get("evidence", []))
        cross_source = int(cand.get("cross_source_count", 0))
        strong = evidence_count >= args.min_evidence_links and cross_source >= args.min_cross_source
        if strong:
            strong_count += 1

        story = story_contract(cand, strong=strong)
        for ev in story.get("evidence", []):
            total_evidence += 1
            if not ev.get("doc_id") or not ev.get("uri"):
                orphan_evidence += 1
        story_id = story["story_id"]
        json_path = output_dir / f"story_{story_id}.json"
        md_path = output_dir / f"story_{story_id}.md"
        json_path.write_text(json.dumps(story, indent=2, ensure_ascii=False), encoding="utf-8")
        md_path.write_text(markdown_for_story(story), encoding="utf-8")

        manifest.append(
            {
                "story_id": story_id,
                "title": story.get("title"),
                "quality_score": story.get("quality_score", 0),
                "evidence_count": story.get("evidence_count", 0),
                "cross_source_count": story.get("cross_source_count", 0),
                "publication_tier": story.get("publication_tier"),
                "json_path": str(json_path),
                "md_path": str(md_path),
            }
        )

    metrics = {
        "stories_total": len(candidates),
        "stories_strong": strong_count,
        "stories_candidate": max(0, len(candidates) - strong_count),
        "evidence_total": total_evidence,
        "evidence_orphan_count": orphan_evidence,
        "evidence_orphan_rate": round(orphan_evidence / max(1, total_evidence), 4),
        "factual_grounding_rate": round(strong_count / max(1, len(candidates)), 4),
        "estimated_hallucination_rate": round(
            max(0.0, 1.0 - (strong_count / max(1, len(candidates)))), 4
        ),
        "promotion_rule": {
            "min_evidence_links": args.min_evidence_links,
            "min_cross_source": args.min_cross_source,
        },
    }
    (output_dir / "story_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "story_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
