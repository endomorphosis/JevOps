---
name: jevops-audit
description: AST audit of Python sources — forbidden imports/calls, LOCK_EX, membership flags. Use for audit_source / membership. Does not execute. Never docker0. Never writes Lean.
---

# Source audit

Module: `jevops.repair`.

- `audit_source` walks AST. `membership` builds import/call flags. LRA audits (PCA/draft/mistral/compile/lake/bake/warmup/ledger) are shims.
- Extra fields: `call_names`, `attr_names`, `string_constants`, `score_keys`, `forbidden_attrs`.
- `scan_constant_uses` flags a needle Constant and Call.attr scans.
- `assigned_constant` reads frozen constants (JEV_GENERATES_LEAN, DEFAULT_MODE).
- Does not POST, does not generate Lean, does not call docker0.
