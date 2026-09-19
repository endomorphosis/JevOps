---
name: jevops-redact
description: Recursively redact API keys and bearer tokens from evidence JSON. Use for redact() before writing canary payloads. Never writes Lean.
---

# Redact

Module: `jevops.jev.redact`.

- Keys containing `api_key`, or exact `authorization`/`token` (except usage token counts), become `[redacted]`.
- String values starting with `apikey_` (or extra prefixes) are redacted.
- LRA `draft_fanout` / `track1_mistral_leanstral` wrap this. Never docker0.
