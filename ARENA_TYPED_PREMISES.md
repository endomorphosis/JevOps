# Native premise signatures and bounded application retrieval

This extends the [application/materialization slice](ARENA_APPLICATION_MATERIALIZATION.md)
of the [research plan](LEAN_REFACTOR_ARENA_RESEARCH_PLAN_2026_09_24.md).
There is still one existing Arena runtime and one verifier boundary, not a new
agent framework or an upstream ATP dependency.

## Implemented boundary

`NativePremiseExporter(..., include_signatures=True)` now requests V2 extraction
from the actual target-free Lean prefix on **every required pin**. In addition
to the existing type text, dependency closure and axiom audit, Lean traverses
the declaration's `Expr` to emit:

- A bounded telescope of binder kinds: explicit, implicit, strict implicit and
  instance implicit, plus a raw expression-head feature for each binder type.
- The conclusion's head kind, constant name when available, and application
  spine arity. Heads can be constant, bound variable, sort or unsupported/other.
- A versioned signature record bound to the exact declaration name.

These are structural features, **not a full type serialization or a native
unification result**. The exporter does not regex-parse a pretty-printed type,
reduce arbitrary definitions or reconstruct a proof from these features. For
example, a theorem concluding an abbreviation retains that abbreviation's raw
head. The candidate must still pass the native `apply`/premise-discharge,
kernel/type/axiom, printed-term replay and whole-source gates.

The default exporter and V1 inventory reader retain their historical behavior.
V2 contains the same premise records plus a separate signature list; V1 callers
need not synthesize signatures. With no signatures, the V1 index identity is
unchanged. Signature contents affect the V2 index identity and therefore the
source/capture-bound discovery request. Extra authority fields, unsupported
schemas, malformed telescopes, duplicate or foreign signature names, Boolean or
non-finite arities and oversized signatures are rejected.

Signatures must agree across all required pins before being used for head
priority. Unsupported/budget-exhausted or version-different signatures are
reported separately and omitted; the otherwise available premise remains in
the lexical inventory. Missing declarations, differing type text, excluded
dependencies and forbidden axioms retain the existing all-pin exclusion rules.
The raw per-pin signature records remain in the export report.

## Retrieval, not proof authority

`plan_local_applications(..., retrieval="typed-head-v1")`, also available through
`ArenaLocalRuntime.discover_batch`, extracts a bounded head feature from the
**before-goal** in the validated capture. It never reads the reference's solved
proof value. Full observation validation remains bounded global setup work.

The index combines lexical postings with exact constant-head postings and
generic/nonconstant signature postings. It prioritizes:

1. Equal constant conclusion heads.
2. Unknown/missing or nonconstant heads.
3. Different constant heads.

Lexical overlap and declaration name break ties deterministically. The reported
fraction is still a lexical score, not a probability of applicability; the
separate `head_priority` field exposes the structural tier. Arity and binder
features are recorded but do not independently establish an applicable rule.

When `top_k > 1` and alternatives exist, one slot is reserved for a fallback.
Head mismatch is **not** a permanent exclusion: definitions can unfold and
generic or forward lemmas may matter. Finite top-k/application caps can still
miss a useful premise; this is not a complete proof search or fair unbounded
inference engine. There is no forward chaining, equality saturation or learned
retriever in this increment. If the goal-head traversal is unsupported, lexical
ranking remains available. `NO_CONSTANTS` still abstains on library retrieval.

Defaults remain `retrieval="lexical-v1"`, with the existing `baseline-v1` and
`portfolio-v1` paths unchanged. Both retrieval modes use the **same native
symbolic application/materialization operation** from the previous slice.
This change does not substitute a ranking score for symbolic proof construction.

### Bounds and compatibility

- At most 64 nominated declarations per native export, 64 telescope binders per
  signature, 257 head-spine steps and 129 telescope traversal steps. Unsupported
  extraction yields no signature rather than a partial telescope.
- Constant-head names are limited to 1,024 UTF-8 bytes and arities to 0–256.
  Native signatures have a 15,000-byte compact-output cap; Python validates a
  16,384-byte serialization cap and accounts for signature bytes in the existing
  4 MiB inventory limit.
- The union of typed and lexical candidate postings uses the same `max_scan`
  ceiling. Overflow returns no partial ranking. Scope/alias/held-out/dependency
  exclusions remain mandatory. Inverted-head lookup is not a claim that scope
  setup or native dependency fingerprinting has no global work.
- No implicit model calls, retries, downloads, builds or paid service. Fixtures
  remain `FIXTURE_ONLY`, and neither typed features nor hashes authorize facts.
- Existing trusted-local execution and optional isolation are unchanged. This
  does not resolve the separately documented producer/measurement-integrity
  limitations, establish organizer measurement parity or enable promotion.

## Using the existing harness

```python
report = NativePremiseExporter(
    guard, max_processes=len(pins), include_signatures=True,
).export(record, nominees, excluded_names=protected_names)
# Check report status; deserialize inventory/scope with load_inventory.
batch = runtime.discover_batch(
    pin, capture, index, scope,
    retrieval="typed-head-v1", span_order="headroom-v1",
    max_applications=4, cap=1,
)
# Ordinary unadmitted drafts; fresh all-pin source and cost checks still required.
```

The existing inventory CLI accepts `--include-signatures`. Existing output
directories are refused, and native invocation still requires the existing
explicit `--trusted-local`, prepared projects and process allowance.

## Matched exploratory comparison

The existing `tools/run_local_premise_pilot.py` accepts
`--comparison application-retrieval`. Its two arms share the same fresh capture,
V2 all-pin inventory, headroom ordering, top-k, query limits and whole-source
verification adapter. Each receives **four** application processes and the same
final draft/screen limit. Each application includes checked term extraction and
independent term replay; there is no additional hidden replay process allowance.

Generation runs lexical then typed, with wall time recorded separately. Equal
process ceilings do not mean equal elapsed time, kernel work or model cost.
Successful drafts are screened in alternating arm order and stop at the first
non-verified pin. Only all-pin survivors enter the existing fresh balanced
measurements (two orders, two repetitions). There is no independent confirmation
or production promotion in this pilot. An infrastructure failure makes the run
incomplete, not a mathematical rejection or a zero score.

For the three-pin `Core.InitsUpdatesComm` task with `--cap 1`, reserve **57**
process units: 15 discovery/control, six screening and 36 measurement. Actual
launches and reserved ceilings are reported separately; unused allowance is not
measured expenditure. Native execution remains inside the existing capped
50,000,000,000-byte preparation volume with its exclusive lock. Source inputs
must come from a read-only snapshot, checked before and after the run.

Plan only, offline:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py \
  --nominees papers/completion/lean_refactor_arena/evidence/local-premise-core-nominees.json \
  --comparison application-retrieval --cap 1 --max-processes 57
```

Execution follows the [frozen pilot instructions](ARENA_LOCAL_PREMISE_PILOT.md#reproduction)
with those comparison/cap/process options and a **new** snapshot/output. The
fixed three-pin plan ID is
`b962dbdb055e4e042ae2fb5a5fe8f08bec2c8786142bb67bfb538413fc7e6f70`.
This is one already-inspected public warmup theorem with eight reference-informed
nominees, not held-out performance or a full-corpus score. Any prospective winner
must beat the known current incumbent under the strict-dual confirmation protocol
before it can be described as a new improvement.

## Tests observed before the pilot

The expanded offline integration suite passed **643 tests**, with 28 native
cases skipped and nine older auto-native cases deselected, in **10.34 seconds**.
Run the command in
[the preceding slice's test report](ARENA_APPLICATION_MATERIALIZATION.md#observed-results-2026-09-24)
with `tests/test_typed_premises.py` added to its test file list.

The native control deliberately puts an `Or` premise in a lemma whose conclusion
is `True`. Lexical retrieval chooses it and fails to close the `Or` goal; typed
retrieval chooses the actual `Or` conclusion, extracts an explicit term and
passes fresh whole-source verification with the same single-application cap.
The control also inspects polymorphic, instance-implicit and abbreviation heads.

```bash
env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SIGNATURE_LEAN_TAG=v4.26.0 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off tests/test_typed_premises.py -k native
```

Observed: **one passed in 13.32 seconds** on installed 4.26.0. A second run with
`JEVOPS_SIGNATURE_LEAN_TAG=v4.29.1`, both `tests/test_typed_premises.py` and
`tests/test_arena_premises.py`, and
`-k 'native_signatures or native_export_roundtrip'` passed **two checks in
25.39 seconds**. That includes the legacy exporter roundtrip on its existing
4.26.0/4.34.0 control pins. These are mechanism/regression tests, not Arena gains.

## Real warmup pilot result, 2026-09-24

The fixed trial completed, **without an accepted improvement**. The
[retained report](papers/completion/lean_refactor_arena/evidence/typed-premise-pilot-2026-09-24/report.json),
[lexical trace](papers/completion/lean_refactor_arena/evidence/typed-premise-pilot-2026-09-24/lexical-drafts.json)
and [typed trace](papers/completion/lean_refactor_arena/evidence/typed-premise-pilot-2026-09-24/typed-drafts.json)
record all eight failed application attempts; these failures are not
counterexamples to the theorem.

| Arm | Application processes | Checked extracted terms | Shorter drafts | Discovery wall time |
| --- | ---: | ---: | ---: | ---: |
| Lexical | 4 | 0 | 0 | 106.7038 s |
| Typed head | 4 | 0 | 0 | 103.9660 s |

All three original-proof controls verified. All eight nominees were available
with agreeing signatures on every required pin. All 37 selected spans were
captured; 31 editable spans entered retrieval. The run used **15 actual native
processes**, 15 stage reservations from the 57-unit ceiling, and **426.4394 s**
overall. No candidate reached whole-source screening or balanced measurement;
there is no candidate heartbeat result, confirmed winner or official score.
The small difference in discovery wall time is not a demonstrated speedup.
`COMPLETE` means the fixed exploratory protocol finished, not that it found an
improved proof.

Typed retrieval changed the first nominee on **14 of 31** eligible spans. For
example, `List.Nodup` goals now nominate `Core.InitStatesNodup`, replacing the
lexically related but wrong-conclusion `Core.updatedStatesInit`. However, both
arms' four-application budgets were spent on the same largest spans, events
**2, 6, 8 and 11**, with the same nominees. Those compound/unsupported-head goals
did not unify with the nominated lemma conclusions. No matched-head alternative
existed in the nominated inventory for those chosen spans, so the documented
fallback retained the same lexical choices. Changing a nomination at an unvisited
span is not a measured proof improvement.

This identifies the next interaction to test: **joint applicability-aware region
selection plus bounded multi-step premise construction**, preserving a fallback
allocation. Simply increasing head priority within each region cannot help when
the scheduler never visits the changed regions. The larger conjunction/function
goals also need decomposition or intermediate facts, beyond this one-application
grammar. These are hypotheses for a new predeclared experiment; the completed
pilot was not adaptively altered or relabelled.

The read-only snapshot contained 234 files / 4,851,196 bytes, with manifest hash
`25f3a494d0d2e4f9d00638805f5cd5563fb0ffc8b438d857fe566b4502654788`.
[Before/after binding checks](papers/completion/lean_refactor_arena/evidence/typed-premise-pilot-2026-09-24/source-binding.json)
both report unchanged source. The original complete run, including the 7.1 MiB
capture, remains at:

```text
/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/typed-premises-20260924-Vw3uN3/run
```

Its `capture.json` SHA-256 content hash is
`879c3973a065a07a0e3c4eedb298c2fb249d061579bc3ff01e65b8d903e0b5bf`.
This is an artifact identity, not a proof. Compact evidence is copied into the
repository; no prior reports were overwritten. No API calls, model training,
downloads, dependency builds, commits, pushes or promotions occurred in this turn.
