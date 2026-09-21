# Lean Refactor Arena runbook

This is the in-tree `LRA/v1` warm-up harness. It is not an official Arena
submission and it never writes an Arena score. The frozen corpus contains 15
records with SHA-256:

```text
6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
```

## Protocol checks

Run these from the JevOps repository root:

```bash
python papers/completion/lean_refactor_arena/tools/summarize_warmup.py
python papers/completion/lean_refactor_arena/harness/run_warmup.py --plan
python papers/completion/lean_refactor_arena/tools/verify_lra_batch.py --schedule
python papers/completion/lean_refactor_arena/harness/splice.py --self-check
python papers/completion/lean_refactor_arena/harness/compile_worker.py --self-check
python papers/completion/lean_refactor_arena/harness/run_warmup.py --self-check
```

The benchmark consumer hooks are opt-in when importing modules into another
Python process. For the complete harness test suite, activate them explicitly:

```bash
JEVOPS_REGISTER_LRA_HOOKS=1 \
  pytest -q papers/completion/lean_refactor_arena/harness
```

This keeps the JevOps core suite independent of optional benchmark modules:

```bash
pytest -q
```

## Optional dependency paths

The harness resolves optional `ipfs_accelerate` and `ipfs_datasets` checkouts
relative to this repository (or its sibling research checkout). CI and
multi-checkout runs can override them without editing benchmark code:

```bash
export LRA_IPFS_ACCELERATE_PATH=/path/to/ipfs_accelerate
export LRA_IPFS_DATASETS_PATH=/path/to/ipfs_datasets
export LRA_STATE_ROOT=/path/to/lra-state
```

TypeSafe and router imports remain lazy and fail closed when the configured
accelerator checkout is absent. Lean/Lake capability is independently gated by
the tag-pinned toolchain probe.

## Experimental autoencoder bridge

`autoencoder_bridge.py` binds every candidate to the frozen statement, sends
all listed version pins through the benchmark compiler callback, and records
the verified search target separately from the autoencoder's own prediction.
Cross-entropy and cosine diagnostics are never replaced by candidate-target
loss. The bridge's `arena_score` and `official_score` fields remain `null`.

```bash
python papers/completion/lean_refactor_arena/harness/autoencoder_bridge.py --plan
```

Synthetic compiler fixtures are plumbing tests only. They do not establish a
Lean result or an Arena ranking.

## Real execution

An actual run requires every repository clone, tag-pinned Lean/Lake toolchain,
and required cache. Missing infrastructure is retained as a failure and never
falls back to a PATH Lean executable:

```bash
python papers/completion/lean_refactor_arena/harness/run_warmup.py \
  --run --network deny \
  --receipts-dir /tmp/lra-receipts \
  --state-root /tmp/lra-state
```

Completion is claimed only by the receipt verifier with all gates enabled:

```bash
python papers/completion/lean_refactor_arena/tools/verify_lra_batch.py \
  --receipts-dir /tmp/lra-receipts --require-complete
```

Plans, self-checks, synthetic compiles, partial runs, and local token proxies
must not be reported as official Arena scores.
