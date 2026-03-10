## Skills
A skill is a set of local instructions to follow that is stored in a `SKILL.md` file.

### Available skills
- omeka-s-connectivity: Verify Omeka S API connectivity and credentials with a curl-backed checker, including deriving `/api` from admin URLs. (file: /Users/itay.tevel/omeka/skills/omeka-s-connectivity/SKILL.md)
- omeka-s-operations: Run comprehensive read-only Omeka S API operations (verify, list, get, metadata inspection, parsed JSON fetch, raw body fetch) with key_identity/key_credential auth via curl-backed tooling. (file: /Users/itay.tevel/omeka/skills/omeka-s-operations/SKILL.md)
- omeka-s-crawler: Crawl Omeka S resources in read-only mode with pagination, retries, and resume checkpoints into local JSONL datasets. (file: /Users/itay.tevel/omeka/skills/omeka-s-crawler/SKILL.md)
- omeka-s-schema-mapper: Build research-ready schema artifacts from vocabularies, properties, classes, and templates (JSON/CSV/Markdown). (file: /Users/itay.tevel/omeka/skills/omeka-s-schema-mapper/SKILL.md)
- omeka-s-entity-lab: Extract multilingual entities from crawl snapshots with alias preservation and delta-aware provenance outputs for investigation pipelines. (file: /Users/itay.tevel/omeka/skills/omeka-s-entity-lab/SKILL.md)
- omeka-s-graph-forge: Build and incrementally update investigation graph snapshots, with optional Neo4j persistence and provenance-rich edges. (file: /Users/itay.tevel/omeka/skills/omeka-s-graph-forge/SKILL.md)
- omeka-s-story-miner: Discover ranked entity-cluster story candidates with facts+hypotheses and cross-source evidence scoring. (file: /Users/itay.tevel/omeka/skills/omeka-s-story-miner/SKILL.md)
- omeka-s-story-packager: Enforce story evidence gates and export visualization-ready JSON plus Markdown story briefs. (file: /Users/itay.tevel/omeka/skills/omeka-s-story-packager/SKILL.md)
- omeka-s-detective-agent: Orchestrate incremental and weekly deep investigative runs by chaining crawl, schema map, entity, graph, mining, and packaging steps. (file: /Users/itay.tevel/omeka/skills/omeka-s-detective-agent/SKILL.md)

### How to use skills
- Trigger this skill when the task involves Omeka S API access checks, key validation, endpoint debugging, or connectivity troubleshooting.
- Trigger this skill when the task involves comprehensive read access to Omeka resources and endpoints without any write operations.
- Trigger this skill when the task requires large-scale extraction of Omeka resources for offline research or analytics.
- Trigger this skill when the task requires deep metadata model analysis, field cataloging, or template/property mapping.
- Trigger this skill when the task requires multilingual entity extraction, alias/ambiguity handling, or delta-aware extraction from Omeka snapshots.
- Trigger this skill when the task requires relationship graph construction, co-occurrence analysis, provenance graph edges, or Neo4j sync.
- Trigger this skill when the task requires ranked story candidate discovery from graph structures and evidence scoring.
- Trigger this skill when the task requires final story artifact generation with strict evidence gates and visualization-ready exports.
- Trigger this skill when the user asks to run full iterative investigative pipelines (incremental or weekly deep recompute).
