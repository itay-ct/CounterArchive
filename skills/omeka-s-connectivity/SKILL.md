---
name: omeka-s-connectivity
description: Verify Omeka S API connectivity and credentials using a curl-backed checker when Python TLS clients are unreliable. Use when debugging access to Omeka S endpoints, validating key_identity/key_credential pairs, or deriving API base URLs from admin URLs.
---

# Omeka S Connectivity

Use this skill when a user needs to validate Omeka S API access quickly and reliably.

## Workflow

1. Use `scripts/verify_omeka.py` with an admin URL or site URL.
2. Pass credentials via flags or environment variables:
   - `OMEKA_KEY_IDENTITY`
   - `OMEKA_KEY_CREDENTIAL`
3. Confirm success by checking:
   - HTTP status is 200
   - `omeka-s-version` header is present
   - at least one item is returned (or total results header is present)

## Command

```bash
python3 skills/omeka-s-connectivity/scripts/verify_omeka.py \
  --url "https://example.org/archive/admin/user/7/edit" \
  --key-identity "$OMEKA_KEY_IDENTITY" \
  --key-credential "$OMEKA_KEY_CREDENTIAL"
```

## Notes

- The script derives `/api` automatically from admin URLs.
- It uses `curl` under the hood because this environment can fail TLS handshakes with some Python HTTP stacks.
