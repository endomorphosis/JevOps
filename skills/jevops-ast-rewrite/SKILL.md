---
name: jevops-ast-rewrite
description: Sandboxed Python AST rewrite under allowed roots. Use for rewrite_python, replace_function_def, inspect_python. Never writes Lean. Fail closed outside roots. Diagnostics must not get worse.
---

# AST rewrite

Module: `jevops.nca`.

- `inspect_python` / `walk_python` remain inspect-only.
- `rewrite_python(path, roots=, transform_fn=)` parses, transforms, `ast.unparse`s, writes only if:
  - path is under `allowed_path` roots
  - output parses
  - `looks_like_lean` is false
  - optional `diagnose_fn` does not worsen
- `replace_function_def` swaps one function by name.
- Jev does not write Lean. Tests/lake still admit. Never docker0.
