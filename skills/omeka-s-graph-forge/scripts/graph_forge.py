#!/usr/bin/env python3
import argparse
import importlib
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


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


def jsonl_write(path: Path, rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_doc_refs(
    docs_by_id: Dict[str, dict],
    mentions: List[dict],
    max_targets_per_surface: int,
    max_total_refs: int,
) -> List[dict]:
    refs = []
    title_index = defaultdict(list)
    for doc_id, doc in docs_by_id.items():
        title = str(doc.get("title", "")).strip()
        if title:
            title_index[title].append(doc_id)

    for mention in mentions:
        if max_total_refs > 0 and len(refs) >= max_total_refs:
            break
        source_doc = mention.get("doc_id")
        surface = str(mention.get("surface", "")).strip()
        if not surface:
            continue
        candidates = title_index.get(surface, [])
        if max_targets_per_surface > 0:
            candidates = candidates[:max_targets_per_surface]
        for doc_id in candidates:
            if source_doc == doc_id:
                continue
            refs.append(
                {
                    "source_doc_id": source_doc,
                    "target_doc_id": doc_id,
                    "relation": "title_match_reference",
                    "surface": surface,
                    "confidence": 0.75,
                }
            )
    dedup = {}
    for r in refs:
        key = (r["source_doc_id"], r["target_doc_id"], r["relation"], r["surface"])
        dedup[key] = r
    return list(dedup.values())


def merge_incremental(
    mode: str,
    graph_dir: Path,
    new_entities: List[dict],
    new_docs: List[dict],
    new_mentions: List[dict],
) -> Tuple[List[dict], List[dict], List[dict]]:
    if mode == "full":
        return new_entities, new_docs, new_mentions

    old_entities = jsonl_read(graph_dir / "graph_entities.jsonl")
    old_docs = jsonl_read(graph_dir / "graph_docs.jsonl")
    old_mentions = jsonl_read(graph_dir / "graph_mentions.jsonl")

    changed_doc_ids = {d.get("doc_id") for d in new_docs if d.get("doc_id")}

    docs_map = {d.get("doc_id"): d for d in old_docs if d.get("doc_id")}
    for d in new_docs:
        docs_map[d.get("doc_id")] = d

    mentions_kept = [m for m in old_mentions if m.get("doc_id") not in changed_doc_ids]
    mentions = mentions_kept + new_mentions

    entities_map = {e.get("entity_id"): e for e in old_entities if e.get("entity_id")}
    for e in new_entities:
        eid = e.get("entity_id")
        if not eid:
            continue
        old = entities_map.get(eid)
        if not old:
            entities_map[eid] = e
            continue
        aliases = sorted(set((old.get("aliases") or []) + (e.get("aliases") or [])))
        langs = sorted(set((old.get("language_set") or []) + (e.get("language_set") or [])))
        entities_map[eid] = {
            **old,
            **e,
            "aliases": aliases,
            "language_set": langs,
            "contested_name": bool(old.get("contested_name")) or bool(e.get("contested_name")),
            "confidence": round((float(old.get("confidence", 0)) + float(e.get("confidence", 0))) / 2.0, 4),
        }

    return list(entities_map.values()), list(docs_map.values()), mentions


def cooccurs_from_mentions(mentions: List[dict]) -> List[dict]:
    by_doc = defaultdict(set)
    for m in mentions:
        doc_id = m.get("doc_id")
        entity_id = m.get("entity_id")
        if doc_id and entity_id:
            by_doc[doc_id].add(entity_id)
    pair_counter = Counter()
    pair_docs = defaultdict(set)
    for doc_id, entities in by_doc.items():
        for a, b in itertools.combinations(sorted(entities), 2):
            pair_counter[(a, b)] += 1
            pair_docs[(a, b)].add(doc_id)
    out = []
    for (a, b), weight in pair_counter.items():
        out.append(
            {
                "source_entity_id": a,
                "target_entity_id": b,
                "weight": weight,
                "doc_count": len(pair_docs[(a, b)]),
                "doc_ids": sorted(pair_docs[(a, b)])[:50],
            }
        )
    return out


def write_neo4j(
    entities: List[dict],
    docs: List[dict],
    mentions: List[dict],
    cooccurs: List[dict],
    doc_refs: List[dict],
    uri: str,
    user: str,
    password: str,
) -> Dict[str, int]:
    neo4j_module = importlib.import_module("neo4j")
    GraphDatabase = neo4j_module.GraphDatabase
    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (a:Alias) REQUIRE a.alias_id IS UNIQUE")

        for e in entities:
            session.run(
                """
                MERGE (e:Entity {entity_id:$entity_id})
                SET e.label=$label, e.entity_type=$entity_type, e.primary_language=$primary_language,
                    e.confidence=$confidence, e.contested_name=$contested_name,
                    e.language_set=$language_set, e.aliases=$aliases
                """,
                **e,
            )
            for alias in e.get("aliases", []):
                alias_id = f"{e['entity_id']}::{alias}"
                session.run(
                    """
                    MERGE (a:Alias {alias_id:$alias_id})
                    SET a.text=$text
                    WITH a
                    MATCH (e:Entity {entity_id:$entity_id})
                    MERGE (a)-[:ALIAS_OF]->(e)
                    """,
                    alias_id=alias_id,
                    text=alias,
                    entity_id=e["entity_id"],
                )

        for d in docs:
            session.run(
                """
                MERGE (d:Document {doc_id:$doc_id})
                SET d.resource=$resource, d.o_id=$o_id, d.title=$title, d.uri=$uri,
                    d.modified=$modified, d.source_archive=$source_archive
                """,
                **d,
            )

        for m in mentions:
            session.run(
                """
                MATCH (d:Document {doc_id:$doc_id})
                MATCH (e:Entity {entity_id:$entity_id})
                MERGE (d)-[r:MENTIONS {mention_id:$mention_id}]->(e)
                SET r.field_key=$field_key, r.surface=$surface, r.language=$language,
                    r.confidence=$confidence, r.source_archive=$source_archive
                """,
                **m,
            )

        for c in cooccurs:
            session.run(
                """
                MATCH (a:Entity {entity_id:$source_entity_id})
                MATCH (b:Entity {entity_id:$target_entity_id})
                MERGE (a)-[r:CO_OCCURS]->(b)
                SET r.weight=$weight, r.doc_count=$doc_count, r.doc_ids=$doc_ids
                """,
                **c,
            )

        for r in doc_refs:
            session.run(
                """
                MATCH (a:Document {doc_id:$source_doc_id})
                MATCH (b:Document {doc_id:$target_doc_id})
                MERGE (a)-[r:REFERENCES {relation:$relation, surface:$surface}]->(b)
                SET r.confidence=$confidence
                """,
                **r,
            )

    driver.close()
    return {
        "entities": len(entities),
        "docs": len(docs),
        "mentions": len(mentions),
        "cooccurs": len(cooccurs),
        "doc_refs": len(doc_refs),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build incremental investigation graph from entity lab artifacts")
    parser.add_argument("--entity-dir", required=True)
    parser.add_argument("--graph-dir", required=True)
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    parser.add_argument("--skip-neo4j", action="store_true")
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="")
    parser.add_argument("--max-doc-ref-targets-per-surface", type=int, default=25)
    parser.add_argument("--max-doc-refs-total", type=int, default=500000)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    entity_dir = Path(args.entity_dir)
    graph_dir = Path(args.graph_dir)
    ensure_dir(graph_dir)

    new_entities = jsonl_read(entity_dir / "entities.jsonl")
    new_docs = jsonl_read(entity_dir / "docs.jsonl")
    new_mentions = jsonl_read(entity_dir / "mentions.jsonl")

    entities, docs, mentions = merge_incremental(args.mode, graph_dir, new_entities, new_docs, new_mentions)
    docs_by_id = {d.get("doc_id"): d for d in docs if d.get("doc_id")}
    cooccurs = cooccurs_from_mentions(mentions)
    doc_refs = build_doc_refs(
        docs_by_id,
        mentions,
        max_targets_per_surface=args.max_doc_ref_targets_per_surface,
        max_total_refs=args.max_doc_refs_total,
    )

    jsonl_write(graph_dir / "graph_entities.jsonl", entities)
    jsonl_write(graph_dir / "graph_docs.jsonl", docs)
    jsonl_write(graph_dir / "graph_mentions.jsonl", mentions)
    jsonl_write(graph_dir / "graph_cooccurs.jsonl", cooccurs)
    jsonl_write(graph_dir / "graph_doc_refs.jsonl", doc_refs)

    summary = {
        "mode": args.mode,
        "entities": len(entities),
        "docs": len(docs),
        "mentions": len(mentions),
        "cooccurs": len(cooccurs),
        "doc_refs": len(doc_refs),
        "neo4j_written": False,
        "max_doc_ref_targets_per_surface": args.max_doc_ref_targets_per_surface,
        "max_doc_refs_total": args.max_doc_refs_total,
    }

    if not args.skip_neo4j:
        if not args.neo4j_password:
            summary["neo4j_error"] = "Missing --neo4j-password; skipped"
        else:
            try:
                neo4j_counts = write_neo4j(
                    entities=entities,
                    docs=docs,
                    mentions=mentions,
                    cooccurs=cooccurs,
                    doc_refs=doc_refs,
                    uri=args.neo4j_uri,
                    user=args.neo4j_user,
                    password=args.neo4j_password,
                )
                summary["neo4j_written"] = True
                summary["neo4j_counts"] = neo4j_counts
            except Exception as exc:
                summary["neo4j_error"] = str(exc)

    (graph_dir / "graph_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
