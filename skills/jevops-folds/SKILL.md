---
name: jevops-folds
description: Portable Lean tactic folds and unused-binder gates. Use for CALL ptr://skill/port_* folds, compose_pipeline, or binder repair after Unknown identifier. Lake is the oracle. Never writes Lean.
---

# Lean folds and binders

Modules: `jevops.folds`, `jevops.binders`, `jevops.lean`.

- Pattern folds (`exact Hin`→`assumption`, pack `use`/`exact ⟨⟩`, hoist repeated `simp`, drop unused intros). TypeSafe picks; code applies; lake admits.
- `jevops.binders` — `rename_i`/`have` drop only when names are unused later. Restore the binding line on lake `Unknown identifier`.
- `jevops.lean` — `measurement_argv`, `parse_axioms`, `lake_measurement_ok`. IndependentKernelVerifier is not the oracle.

Jev does not write Lean. Never docker0.
