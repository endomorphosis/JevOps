# Arena artifact import policy

The in-tree Arena copy includes source code, frozen benchmark data, protocol
documents, and curated canary fixtures. It intentionally does not copy the
upstream worktree's generated receipt history, PDF build products, or hundreds
of timestamped experiment dumps.

Those artifacts are host- and run-specific evidence, not benchmark source.
Runtime sidecars, CAS entries, receipts, and canary outputs default to the
configured `LRA_STATE_ROOT` (under `artifacts/`) rather than this source tree.
Live results must be regenerated under the current checkout and accepted only
by `tools/verify_lra_batch.py --require-complete`. Generated artifacts must not
be treated as a benchmark score or used to seed the autoencoder's reward.
