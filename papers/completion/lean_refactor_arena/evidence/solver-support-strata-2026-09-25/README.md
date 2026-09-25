# Strata support minimization — 2026-09-25

Later baseline correction: this pass used a fixed 185-token comparator, but
overlooked the archived 169-token strict winner from a different experiment
family. Its no-candidate result is unchanged; 185 is not the strongest known
incumbent. See the [reconciled follow-up](../subset-triple-strata-2026-09-25/README.md).

This is a bounded, exposed-public-task experiment, not a corpus score, held-out
evaluation, model comparison, global support minimum, or production promotion.
The only optimizer change is in `jevops/solver_feedback.py`: single-line support
deletions now preserve `at *` / named locations and LF/CRLF endings. Previously
the confirmed Strata candidate's `at *` support list was silently skipped.
The existing whole-source checker remains the admission boundary.

## Observed outcome: no new candidate

**10 native checks** completed: two controls plus eight discovery calls.
Original, incumbent, seed and compiler-query probe verified; all **six deletion
candidates were rejected with Lean `candidate_errors`**, not timeouts or
infrastructure failures. Screening/confirmation used zero calls. No candidate
or incumbent was promoted, and no new strict or aggregate score gain is claimed.

The unchanged 190-token seed cost 2,049,152 raw heartbeats in its one discovery
sample. Fresh original and incumbent controls cost 2,607,572 and 2,324,397,
respectively. These are single observations, not a new performance confirmation.
Their accepted axiom sets remain `propext` and `Quot.sound`.

| Deletion from the five-entry list | Tokens | Native result / diagnostic |
| --- | ---: | --- |
| All entries | 181 | Rejected: unsolved application/subset goals and other continuation errors |
| `extractOldExprVars` | 188 | Rejected: `ite` branch induction application/grouping mismatch |
| `Imperative.HasVarsPure.getVars` | 188 | Rejected: unsolved variable-membership goals |
| `Lambda.LExpr.LExpr.getVars` | 188 | Rejected: unsolved variable-membership goals |
| `List.Subset.empty` | 188 | Rejected: base cases retain `[].Subset ...` goals |
| `List.append_assoc` | 188 | Rejected: `ite` branch induction application/grouping mismatch |

The compiler-query hints merged back to the existing seed, so source deduplication
avoided another identical check. Discovery reports `COMPLETE` **within the chosen
window**, with `truncated=true`: nine other query sites were intentionally omitted.
No checked child entered the frontier; deeper expansion therefore had nothing to
process. This does not prove global minimality, that multi-deletion combinations
cannot work, or that these lemmas are logically indispensable in another proof.

The useful next intervention is branch-local reconstruction/dependency repair,
especially the `ite` append grouping, before attempting deletion again. Merely
raising the depth cap cannot extend this accepted-only frontier. A separate
experiment could explore repaired composites or explicit rejected intermediates,
but would need a new frozen budget; none was launched in this pass.

Artifacts: [protocol](protocol.json), [report](report.json),
[full discovery receipts/diagnostics](discovery.json),
[original control](original-control.json), [incumbent control](incumbent-control.json),
[launch](launch.json), [before/after source binding](source-binding.json),
[manifest](source-manifest.json), [regression JUnit](regression.xml).
The read-only snapshot remained `UNCHANGED` (1,979 files, 50,836,200 bytes;
manifest SHA-256 `da4a59884768c622ea83341c70a092f31fb918cf29e13ddb00fd8bb17095fbd9`).
Runtime directory: `/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/solver-support-strata-e5jizgat`.
Experiment time: 245.33 seconds; child launch plus final snapshot check: 248.56
seconds. Free capped-volume space went from 814,247,936 to 757,248,000 bytes.
Content hashes establish identity, not independent proof authority.

## Frozen protocol

- Task: `CallElimCorrect.extractedOldExprInVars`, Strata commit
  `451e5f047bafa010d178856db76c00029bfa4d7f`, sole declared pin `v4.26.0`.
- Search seed: the historical **190-token** merged-simp-only candidate from
  [the earlier aggregate experiment](../solver-reference-strata-2026-09-24/README.md).
  Historical receipts are not reused as verification events.
- Strict incumbent: the distinct **185-token** proof. Original: **222 tokens**.
  A 188-token deletion is smaller than the seed, but cannot be a strict win.
- Fresh original/incumbent controls: ceiling 2 checks; stop on failure.
- Existing `minimize-v1` / `shortest-v1`: ceiling 16 checks, 8 checked states,
  depth 3, first solver site only, one nominated draft. FIFO expansion tries
  empty support, then each single deletion, then bounded compiler suggestions.
  Every edit is replayed against the unchanged whole-proof continuation.
- Only a checked nominee below 185 tokens may enter selection. Reserve 30
  **additional** checks: original/incumbent/candidate × two orders × two screen
  repetitions, then three fresh confirmation repetitions/order for the fixed
  winner. Use `strict-dual-v1`, raw heartbeat noise floor 100, seeds 17/18.
- Full ceiling **48 native checks**, no retries or post-result budget expansion.
  Unused confirmation allowance cannot be reassigned to discovery.

The launcher captures read-only implementation, tests, corpus and inputs before
checking; it holds the existing kernel `flock` over the whole run. All native
work is serial on the existing 50 GB capped volume. At least 200 MB must be free
before capture and 100 MB at subsequent resource checks. There are no new
downloads, dependency builds, model calls, or credentials forwarded to the child.
This is trusted-local native execution, **not an OS sandbox** or a solution to
all source-execution/metric-authenticity threats in the safety roadmap.

Reproduce with a new automatically allocated run directory:

```bash
PYTHONDONTWRITEBYTECODE=1 python \
  papers/completion/lean_refactor_arena/evidence/solver-support-strata-2026-09-25/run_experiment.py \
  --repo /home/barberb/lift_coding/JevOps \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --execute
```

Prepared project/toolchain paths are local prerequisites, not portable downloads.
The driver uses `ArenaLocalRuntime.discover_solver`, `NativeLeanVerifier` and
`arena_pareto.run_selection`; it introduces no parallel optimizer or verifier.
Raw heartbeat observations are actual native measurements; API cost is not
measured. Discovery is single-sample and cannot establish a speedup by itself.

## Regression command

Executed fresh from the workspace before native launch, with outputs outside
the watched source roots:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 \
JEVOPS_ARENA_DOCKER_TESTS=0 python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-support-tests-NRb8yghL/cache \
  --junitxml=/tmp/jevops-support-tests-NRb8yghL/regression.xml \
  tests/test_arena_solver.py tests/test_arena_solver_balanced.py \
  tests/test_arena_solver_reference.py tests/test_solver_spans.py \
  tests/test_arena_solver_pilot.py tests/test_arena_pareto.py -q
```

Observed: **344 passed**, zero reused, **334 fresh passes sealed**, 23.57 seconds.
This includes 22 added cases for location/end-of-line preservation, stale-source
rejection, unsupported suffixes, archived Strata nomination, and full-source
fixture replay rejecting deletion of a required premise. Fixtures are not Lean
verification. An initial development run failed two tab-location expectations;
the tests were corrected to preserve the existing policy that tabs abstain.
The passing run above was fresh, not a reused seal result.

Supplemental boundary/legacy suite: **196 passed, 6 skipped, 85 deselected**,
zero reused, **189 fresh passes sealed**, 12.65 seconds. [JUnit](safety.xml).
No skipped/deselected test is counted as passed. The installed-Lean legacy
tests require explicit exclusion: several use `which(lean)`, not the newer
`JEVOPS_ARENA_NATIVE_TESTS` opt-in. No full-repository pass is claimed.

Exact command, using a byte-identical read-only copy of the native snapshot
on the host temporary filesystem (same externally checked manifest hash):

```bash
env -u PYTEST_ADDOPTS -u JEVOPS_MATHLIB_PROJECT \
  PATH=/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
  /home/barberb/.local/bin/python -I -B -c \
  'import os, sys; os.chdir(sys.argv[1]); sys.path.insert(0, sys.argv.pop(1)); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' \
  /tmp/jevops-support-safety-copy-m6EJDk6F/source --test-seal=refresh \
  -o cache_dir=/tmp/jevops-support-safety-copy-m6EJDk6F/cache \
  --junitxml=/tmp/jevops-support-safety-copy-m6EJDk6F/safety.xml \
  tests/test_solver_feedback.py tests/test_arena.py tests/test_arena_lean.py \
  tests/test_arena_source.py tests/test_candidate_audit.py \
  tests/test_scoped_evaluation.py tests/test_arena_solver_native.py \
  -k 'not real_ and not native_rfl' -q
```

Two preliminary supplemental invocations were interrupted, not completed test
results: the unfiltered selection stopped after 3 fixture passes / 2 skips to
exclude implicit installed-Lean tests; the corrected selection on the FUSE
snapshot stopped after 24 passes / 2 skips because seal traversal was slow
(186 seconds, 54,410 file reads). Moving the **same immutable input bytes** to
`/tmp` allowed the fresh suite above to finish. Neither interrupted invocation
is included in the 540 completed-suite passes, and neither ran a native proof
test. A first restricted-PATH launch also exited before pytest because `python`
was not on that PATH; the absolute interpreter above fixes that launcher issue.

## Changed files and preserved boundaries

- `jevops/solver_feedback.py`: narrow location/end-of-line nomination fix;
  unchanged source-hash binding, payload limits and checked-replay requirement.
- `tests/test_arena_solver.py`: 22 added offline regression cases.
- `run_experiment.py` in this directory: reproducible fixed-budget wrapper over
  existing local runtime, native checker and strict selector; no new optimizer.
- `ARENA_SOLVER_SPECIALIZATION.md`, `LEAN_TOKEN_HEARTBEAT_SAFETY_PLAN.md`, root
  `README.md` and this evidence archive: implemented scope, protocol, observed
  neutral result, limitations and next research intervention.

Final checks: frozen implementation/test/launcher bytes match the working
checkout; both source-copy manifests verify unchanged. Native context/request
identities, edit hashes, six semantic rejections, no cache hits, and ten total
processes are retained in the artifacts. These are local record-consistency
checks, not independent re-verification. No commit, push or unrelated worktree
reset was performed.
