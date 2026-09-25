# Vendored Lean Refactor source

This directory is a source snapshot of the upstream Lean Refactor repository,
imported into JevOps so the Arena implementation is inspectable without a
sibling checkout.

- Source: https://github.com/delta-lab-ai/lean-refactor
- Source commit: `05f1dad9719979d1f2d82167fb7aeedf6b85233b`
- Imported: 2026-09-22
- Snapshot manifest: [`VENDOR_MANIFEST.json`](VENDOR_MANIFEST.json)

The snapshot contains the upstream Python optimizer, agent graph, prompts,
configuration, Lean data-extraction project, and checked-in examples. It is
kept below `papers/completion/lean_refactor_arena/upstream/` so it cannot
shadow JevOps' `jevops` package or change the offline kernel's dependency
surface.

## Optional upstream execution

The upstream project declares a separate environment with LangChain,
LangGraph, LeanClient, model SDKs, and numerical packages. JevOps does not
install those dependencies for its core runtime. To inspect or run this
snapshot in an appropriately provisioned environment:

```bash
cd papers/completion/lean_refactor_arena/upstream
PYTHONPATH=. python -m lean_refactor.cli --help
```

The command is capability-gated: importing the full CLI requires the upstream
optional packages and a Lean workspace. The core JevOps Arena checks remain
offline and do not claim an upstream optimization run.

The upstream repository records `lean_refactor/mathlib4` as a git submodule at
commit `f198c5fbaae84e872cb341731527553fc9c99f2a`. The gitlink and
`.gitmodules` metadata are retained in the snapshot, but Mathlib itself is not
copied into JevOps; it is a large toolchain checkout rather than Arena source
and remains an explicit optional capability.
