---
name: jevops-repair
description: Diagnose/heal NCA grid, tape, stack, program_state, and restore missing lines. Use for heal, classify_text, restore_bound_lines. Never writes Lean.
---

# Repair

Module: `jevops.repair`. TypeSafe ranks which kernel; the validator is the oracle.

- Closed repairs: only accept if diagnostics drop.
- `classify_text` needles plus optional all-of rules.
- `restore_bound_lines` injects a binder finder. Never docker0.
- `call_func_name` / `attr_hits` / `subprocess_invokes` — AST audits, no exec.
- `keyword_names` / `string_constants` / `function_names`.
- `call_short_name` / `call_short_names` / `ast_name_hits` / `call_kwarg_numbers`.
- `score_keys` / `has_constant` / `assigned_constants` / `matching_constants`.
- `audit_source` also returns call/attr names, string constants, and forbidden_attrs.
- `assigned_literal` — ast.literal_eval of a dict Name assignment.
- `idents_in` — regex tokens minus stopwords.
- `class_ann_names` — AnnAssign fields on a top-level class.
