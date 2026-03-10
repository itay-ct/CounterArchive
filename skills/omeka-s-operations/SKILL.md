---
name: omeka-s-operations
description: Run read-only Omeka S API operations from Codex using a curl-backed CLI: verify connectivity, list resources, get by id, inspect endpoint metadata, and fetch structured JSON or raw response bodies for any endpoint path.
---

# Omeka S Operations

Use this skill for read-only Omeka S API work.

## Script

- Main CLI: `scripts/omeka_ops.py`
- Authentication: `--key-identity/--key-credential` or env vars:
  - `OMEKA_KEY_IDENTITY`
  - `OMEKA_KEY_CREDENTIAL`
- URL input can be admin URL, site URL, or API base URL. The script derives `/api`.

## Common Commands

Verify connection/version:

```bash
python3 skills/omeka-s-operations/scripts/omeka_ops.py verify \
  --url "https://example.org/archive/admin/user/7/edit" \
  --key-identity "$OMEKA_KEY_IDENTITY" \
  --key-credential "$OMEKA_KEY_CREDENTIAL"
```

List items (first page):

```bash
python3 skills/omeka-s-operations/scripts/omeka_ops.py list \
  --url "https://example.org/archive/admin/user/7/edit" \
  --resource items \
  --per-page 5
```

Get one item:

```bash
python3 skills/omeka-s-operations/scripts/omeka_ops.py get \
  --url "https://example.org/archive/admin/user/7/edit" \
  --resource items \
  --id 4664
```

Read endpoint metadata (headers/status/size):

```bash
python3 skills/omeka-s-operations/scripts/omeka_ops.py meta \
  --url "https://example.org/archive/admin/user/7/edit" \
  --path "/resource_templates" \
  --query "page=1" \
  --query "per_page=10"
```

Read any endpoint as parsed JSON:

```bash
python3 skills/omeka-s-operations/scripts/omeka_ops.py fetch-json \
  --url "https://example.org/archive/admin/user/7/edit" \
  --path "/resource_templates" \
  --query "page=1" \
  --query "per_page=10"
```

Read any endpoint as raw body text:

```bash
python3 skills/omeka-s-operations/scripts/omeka_ops.py fetch-raw \
  --url "https://example.org/archive/admin/user/7/edit" \
  --path "/resource_templates" \
  --query "page=1" \
  --query "per_page=10"
```

## Supported Resources

`items`, `item_sets`, `media`, `sites`, `users`, `resource_templates`, `resource_classes`, `vocabularies`, `properties`

Singular aliases like `item`, `item_set`, and `user` also work.

## Read-only Guarantee

- The CLI exposes only `GET`-based operations.
- There are no `create`, `update`, or `delete` commands.
- No request body is sent by this tool.

## Notes

- The CLI uses `curl` to avoid TLS/runtime issues sometimes seen with local Python HTTP stacks.
- `meta`, `fetch-json`, and `fetch-raw` are intentionally separate so metadata inspection and content retrieval are explicit actions.
