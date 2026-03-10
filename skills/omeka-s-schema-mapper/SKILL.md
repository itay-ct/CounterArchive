---
name: omeka-s-schema-mapper
description: Build a research-ready schema map for Omeka S from vocabularies, properties, resource classes, and templates. Generates JSON/CSV/Markdown artifacts for field discovery and template analysis.
---

# Omeka S Schema Mapper

Use this skill when you need a complete metadata model for deep research.

## What it does

- Crawls schema endpoints in read-only mode:
  - `vocabularies`
  - `properties`
  - `resource_classes`
  - `resource_templates`
- Generates:
  - machine-readable JSON summary
  - CSV files for properties and template-property matrix
  - Markdown report with key counts and most-used fields

## Script

- `scripts/omeka_schema_map.py`

## Example

```bash
python3 skills/omeka-s-schema-mapper/scripts/omeka_schema_map.py \
  --url "https://example.org/archive/admin/user/7/edit" \
  --key-identity "$OMEKA_KEY_IDENTITY" \
  --key-credential "$OMEKA_KEY_CREDENTIAL" \
  --out-dir "outputs/omeka-schema"
```

## Output

- `outputs/omeka-schema/schema_summary.json`
- `outputs/omeka-schema/properties.csv`
- `outputs/omeka-schema/template_properties.csv`
- `outputs/omeka-schema/schema_report.md`
