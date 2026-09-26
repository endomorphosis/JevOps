# Locked legal source: first federal-law integration slice

Implemented in `jevops.statement_lock`; both `admit_roundtrip_rule` and
`admit_locked` use it before the existing Lake check. This closes the inspected
helper-substitution gap, not the whole federal-law training plan.

Previously, a reply could keep the theorem text but replace
`decide (bound <= n)` with `decide (n = bound)`. The threshold boundary examples
still agree, while behavior above the threshold changes. Comparing theorem
strings alone did not detect that substitution.

## Contract

`lock_statement(expected, reply)` retains `ok`, `error` and `source`. The trusted
`expected` comes from the existing legal renderer. A successful result adds
`lock`, a versioned record containing SHA-256 content hashes of the protected
envelope, expected source, candidate source, and the ordered theorem names.
The record explicitly sets `verification_performed=false`.

The generated package's entire helper prefix and each theorem header through
`:= by` must match byte-for-byte. Names, target types, theorem order/count and
helper bodies cannot change. The result is assembled from that trusted envelope
and validated proof bodies. A bare tactic reply is permitted only for a single
theorem; every line is indented within its proof. Multiple theorems require the
full source with one proof per unchanged header.

The bounded `legal-numeric-tactics/v1` profile accepts:

- Single-line helper definitions followed by single-line theorem headers with
  no declaration parameters. This covers threshold, conjunction and amount
  packages currently produced by `render_lean`.
- `decide`, `rfl`, `exact rfl`, `constructor`, `trivial`, `assumption`, `simp`,
  `simpa`, `unfold` of declared helper names, and `simp`/`simpa` with bracketed
  helper lists (optionally `only`).
- Newlines, `;`, `<;>`, a single `all_goals` prefix per atom and inline bullets.
  Lean still determines whether the resulting syntax and goal sequencing work.
- At most 16,384 UTF-8 bytes per source (including normalized final newline),
  16 theorems, 128 lines per proof slot and 256 tactic atoms per proof.

This is a deliberately restricted source format, **not a general Lean parser**.
Unsupported syntax, helper references, comments, strings, escaped identifiers,
tabs/control characters, imports, attributes, commands, metaprogramming,
arbitrary term proofs and added declarations fail closed. Benign whitespace
changes to protected definitions/headers are also rejected. A missing final
newline is the only whole-source normalization. Proof whitespace can change.

`native_decide` and `decide +native` are outside this profile. Lean documents
that native decision procedures introduce an axiom and enlarge the trusted
computing base; they are not interchangeable with ordinary `decide` under the
existing no-new-axiom legal policy.
[Lean tactic reference](https://lean-lang.org/doc/reference/latest/Tactic-Proofs/Tactic-Reference/)

## Authority and compatibility

Source-lock success is not proof success. Even `False := by rfl` can pass the
source profile when supplied as the trusted target; the verifier must reject
its proof. No verifier/store call occurs for a failed lock. A failed Lake check
still prevents storage. The legacy `statements()` extractor remains available
for inspection but is no longer the admission comparison.

Both legal admission functions propagate the lock as `source_lock` once the
source check has passed, including a subsequent verifier failure. This metadata
is not an independently authenticated verification receipt. Current attestation
storage and legacy status names are unchanged. Direct `lake_check` remains a
separate diagnostic path; it has not become a source-bound legal admission API.

This intentionally narrows formerly accepted arbitrary Lean replies. Extending
the profile requires explicit grammar/tests; do not add a permissive fallback.
General Arena proof editing continues through its existing, separate interfaces.

The follow-up [explicit legal adapter](LEGAL_ADAPTER.md) now supplies opt-in
per-run dependencies and declared-file source guards. Still outstanding:
complete toolchain/import/axiom closure receipts, native backend and isolated
verifier qualification, reviewed semantic fidelity,
durable proof retrieval, shared-report qualification, sparse whole-cycle updates,
and mapped-weight performance. Expected helper definitions are trusted inputs;
this source checker is not a sandbox for arbitrary caller-supplied packages.

## Offline verification

`tests/test_statement_lock.py` covers renderer preservation, multi-theorem order,
helper drift, changed targets, bounded proof edits, command injection, unsupported
syntax, bytes/line/step limits, malformed inputs and separate content identities.
`tests/test_legal_source_admission.py` tests both admission entry points with
explicit fixture verifiers and stores; it requires no sibling checkout or Lean.
These mocks validate call boundaries, not actual proof acceptance.

The focused command is:

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
  python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-legal-lock-tests/cache \
  tests/test_statement_lock.py tests/test_legal_source_admission.py \
  tests/test_autoformal_tools.py -q
```

No native Lean run is performed by this slice. The older `test_legal_document.py`
contains live Lake integration cases; the regression command for this increment
selects only its explicit no-execution checks, not that whole file.

The expanded regression completed with **210 passed, 1 deselected in 14.86 s**:

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
  python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-legal-lock-tests/cache \
  tests/test_statement_lock.py tests/test_legal_source_admission.py \
  tests/test_autoformal_tools.py tests/test_proof_ca.py \
  tests/test_duckdb_ingest.py tests/test_skillcenter_corpus.py tests/test_muse.py \
  tests/test_legal_document.py::test_a_deadline_rule_is_not_rendered_or_stored \
  tests/test_legal_document.py::test_import_and_a_changed_numeral_never_reach_lake \
  -k 'not legal_autoformal_prompt_does_not_bake_in_the_text' -q
```

The one deselected prompt test requires the sibling legal autoformalization
module. It is not counted as passing. Broader sibling/native integration and
the full repository test suite were not run. `git diff --check` also passed.
