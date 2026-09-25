# Premise retrieval and injected proposal providers

`jevops.premise_search` and `jevops.arena_providers` adapt the deterministic
selection, exclusion, and candidate-source design reviewed in
`endomorphosis/ipfs_datasets_py` at
`ddf6b79467b68159650df81befc288c8553df664`. Relevant upstream modules are
`logic/hammers/premise_selection.py`, `logic/tactician/planner.py`, and
`logic/software_verification/tactician/candidate_synthesis.py`. The reviewed
repository's root license is GNU AGPL v3, also used by this repository. The new
modules do not import that package or transplant its solver trust flags.

This is a proposal-generation integration, not an ATP solver, a trained model,
or an automatic trainer. Outputs are the existing four-field Arena draft files.
Only a fresh native evaluation can establish that a draft proves the original
statement. Token counts at generation time are not accepted compression scores.

## Retrieval and leakage boundaries

An operator supplies two separate inputs:

- A declaration inventory with exact names, type text, origin/family, split,
  aliases, dependencies, and an environment SHA-256.
- A scope bound to the exact benchmark record and that environment, containing
  the names actually available before the target declaration, excluded names,
  and excluded origin/family IDs.

For native use, bind the environment identity to the complete
`NativeLeanVerifier.context(record).context_id`, including all required version
and dependency pins. The available-name inventory must be the intersection of
the pre-target environments across those pins. This module does **not** itself
export or attest native declaration inventories. The bounded exporter below can
supply native availability/type/dependency observations for nominated names;
family/split provenance still comes from the caller. A matching
hash establishes identity, not authenticity or completeness of supplied facts.
Never construct the scope by simply admitting everything in a retrieved corpus.

The selector excludes the target, explicitly blocked names, unavailable names,
validation/test/canary entries, protected origin families, and their declared
aliases/dependents. Missing provenance or undisclosed semantic aliases remain a
limitation: lexical metadata cannot prove absence of benchmark contamination.
The candidate itself still goes through statement/type preservation, axiom
auditing, and fresh native checks. Canaries must never enter training feedback.

Features are case-sensitive lexical identifiers plus qualified-name leaf hints,
not elaborated Lean types or an InfoTree graph. A native `List.Subset` type can
overlap a source goal using `.Subset`; this does not equate namespaces or change
source hashes. The feature-method version is bound into index/ranking identities.
Jaccard scores use exact rational arithmetic and name-based
tie breaking. Feature extraction/postings are computed once per index; each
query still computes scope/exclusion closure over the bounded inventory.
At most 8,192 declarations and 4 MiB of field content are admitted per shard.
Queries score only overlapping postings. Exceeding `max_scan` abstains with
`SCAN_BUDGET`, rather than claiming a partial ranking is the corpus-wide top-k.
This is a bounded shard baseline, not a trillion-token retrieval system.

## Provider contract

### Local premise replay (opt-in)

`propose_local_batch(record, capture, index, scope)` now connects the existing
inventory to **captured local closing spans**, instead of replacing the entire
proof with a retrieved declaration. It emits the same four-field Arena drafts
and a separate `proposals` list accepted by `proof_replay.collect_replay_pairs`.
The old whole-proof provider and default CLI behavior are unchanged.

This deterministic baseline queries constant names reachable from a single
before-goal's type and its local hypothesis types. It does not use local proof
values, after-states, training answers or the whole theorem text as its query.
It is lexical retrieval from a structural observation, **not** unification,
ATP reconstruction, a trained policy, or an independently checked local proof.
The existing `scoped_proposals.local_terms` remains the separate structural
local-reference/application proposer.

The opt-in [bounded local tactic portfolio](ARENA_LOCAL_TACTIC_PORTFOLIO.md)
reuses that proposer as one family alongside guarded library application,
`exact`, and small closing tactics. Select `--local-strategy portfolio-v1`
with `--capture`, or `strategy="portfolio-v1"` in Python. `max_templates`
(CLI `--max-templates`) bounds attempted templates including non-shortening
and duplicate edits. Default `baseline-v1` behavior below is preserved.

Small closing spans are considered first, with non-shortening edits discarded.
Each nominated library declaration generates separate root-qualified `exact`
and `apply` candidates; an `apply` that leaves goals open is not successful
replay. Full-source duplicates are deduplicated. Both the Arena problem ID and
the declaration spelled in the frozen statement are excluded, including their
declared aliases/dependents. Historical/model `verified` fields cannot enter
this interface.

Bindings cover exact source, capture/trace/exporter, dependency environment,
inventory, effective scope, query method, event and budgets. Hashes are not
attestations: a forged but structurally consistent capture can only nominate a
draft. Native replay must regenerate the original context; the Arena selector
must freshly check **every required pin** and its axiom/measurement policy.
Local replay success alone never admits a whole proof or earns a reward.

Offline generation from explicitly supplied artifacts:

```bash
python -m jevops.arena_providers --problem YOUR_PROBLEM \
  --premises /path/to/inventory.json --scope /path/to/scope.json \
  --capture /path/to/capture.json --cap 8 --max-events 16 \
  --output-dir /path/to/new-local-drafts
```

Add `--corpus /path/to/records.jsonl` for a custom corpus, or `--seed` only when
the capture describes that exact seed source. This command makes no native or
model calls and refuses an existing output directory. `--proposal-response`
is deliberately unsupported in local mode: whole-proof nominations are not
silently rebound to local targets. `request.json`, `manifest.json` and draft
JSON files retain inputs' identities and per-event exclusions/abstentions.

For the existing training-only replay collector, inject:

```python
def proposal_fn(source, capture):
    if source != frozen_record["src"]:
        raise ValueError("unexpected source")
    return propose_local_batch(frozen_record, capture, index, scope)["proposals"]
```

Continue to supply the collector's explicit `capture_fn`, `replay_fn`,
`compile_fn` and environment identity. Its whole-source structural gate is
unchanged; supplying a proposal callback does not enable model training or
outer-loop promotion. For Arena performance selection, use the emitted drafts
with the existing all-pin screening/fresh-confirmation workflow instead.

`cap`, `max_events` and `max_query_nodes` accept zero as exhausted. Query and
posting-scan overflows abstain; they never rank silently truncated features.
At most 64 events, 4,096 query nodes/event and eight drafts are allowed. Retained
ranking records share a 1 MiB budget; an overflow stops with `REPORT_BUDGET`.
The report distinguishes this bounded query traversal from the existing full
capture validation and inventory exclusion scans, which remain global work.
Single before-goals and the existing conservative theorem-envelope syntax are
the initial scope. The explicit project-context adapter below preserves open
prefix namespaces/sections without concatenating them to editable source.
Arbitrary open transitions remain unsupported; this does not make the full
Arena corpus replay-ready.

Tests: `tests/test_local_premise_replay.py` has offline capture/transport fixtures
and an explicit `JEVOPS_ARENA_NATIVE_TESTS=1` Lean-core integration control using
the already-installed Lean 4.26.0. No fixture proves native validity; the native
controls check local replay and fresh complete reference/candidate verification:
`True.intro` closes the local goal, while falsely advertising `False.elim` as a
proof of `True` is rejected. These are not an Arena score or heartbeat result.

Validation on 2026-09-23 (test-seal reuse disabled): the focused offline suite
below passed **487 tests**, skipped five explicit native cases and deselected
nine older auto-native scoped tests. The separate native command passed **two
controls** in 15.82 seconds. It ran sequentially, with no downloads or model
calls. The earlier native trial caught whole-body-first proposal starvation;
small-span-first ordering and its regression test now cover that case.

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off -p no:cacheprovider \
  tests/test_local_premise_replay.py tests/test_arena_providers.py \
  tests/test_premise_search.py tests/test_arena.py tests/test_arena_trial.py \
  tests/test_arena_pareto.py tests/test_refactor_prompts.py \
  tests/test_refactor_prompt_archives.py tests/test_scoped_proposals.py \
  -k 'not native_generated and not before_context_never_copies and not stale_capture_abstains and not native_admission'

env -u JEVOPS_ARENA_DOCKER_TESTS JEVOPS_ARENA_NATIVE_TESTS=1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off -p no:cacheprovider \
  tests/test_local_premise_replay.py::test_native_local_candidate_replay_and_whole_theorem
```

### Arena project context and controlled comparison

`ArenaLocalRuntime` in `jevops.arena_local` requires an explicit
`NativeLeanVerifier` and frozen benchmark record. It reuses the Arena prefix
parser and the existing proof-state/replay implementation, rather than guessing
namespace wrappers or shifting captured source offsets. The trusted prefix must
elaborate with the target absent. Only the target command's InfoTree is captured;
prefix proof events are discarded. Open namespace/section scopes are preserved.
Its explicit `closing-source-spans/v1` projection selects single-goal closing
events with nonempty source spans, retaining the first event in preorder for
each distinct span. Events generated at the same span can have other contexts;
those alternatives and open transitions are intentionally not observed here.
This is not a full execution trace. The global InfoTree traversal/depth limits
remain; too many distinct selected spans still fails rather than returning a
silent prefix. Capture and replay use the same bounded selection and exact
native references, so selected IDs cannot drift to unfiltered event IDs.
The standalone full-trace API retains its default selection behavior.

The shared state exporter uses the explicit V2 opaque-have representation
described in [proof-state capture](PROOF_STATE_CAPTURE.md): a `nondep` local
retains its type but not its potentially stale hidden value. Transparent lets
and all actual scope dependencies remain checked. For module contexts, the
project replay injects the existing Arena transitive axiom audit, inspecting
matching private imported theorem bodies without exposing private names to
elaboration. Kernel checking still uses the original context, and forbidden
axioms remain forbidden. This aligns local replay with whole-proof auditing;
it does not turn a local closing result into an admitted refactor.

```python
from jevops.arena_local import ArenaLocalRuntime

local = ArenaLocalRuntime(guard, record, max_processes=3, event_budget=256)
observed = local.capture(pin)
if observed["ok"]:
    batch = propose_local_batch(record, observed["capture"], index, scope, cap=2)
    for proposal in batch["proposals"]:
        outcome = local.replay(pin, record["src"], observed["capture"], **proposal)
        # outcome["closing_reproduced"] is NOT whole-proof admission.
```

Captures bind the full record, all-pin dependency context, specific capture pin,
assembled driver/adapter contracts, exact target and observation budgets.
The projection identity is included in both the origin and native request.
Dependency and implementation identity are checked before and after native work.
Project captures cannot be passed silently to the standalone replay function;
use the same explicitly configured project adapter. Each invocation reserves one
integer process unit before launch. Zero is exhausted; exceptions/timeouts are
errors, not counterexamples or refunded work. A supplied fixture runner is
always labelled `fixture`. Native mode inherits the guard's optional Docker
isolation; without it this is trusted-local execution, **not an OS sandbox**.
No imports, toolchains, builds, hosted inference or retries are automatic.

The fixed public-warmup pilot is plan-only by default:

```bash
python papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py \
  --nominees papers/completion/lean_refactor_arena/evidence/local-premise-core-nominees.json \
  --cap 2 --max-processes 81
```

Execution requires `--execute`, a new output inside the existing capped
preparation volume, and a [frozen source snapshot](ARENA_FROZEN_RUNS.md) containing
`jevops`, the harness, warmup corpus and pilot script, plus immutable
`inputs/projects.json` and `inputs/nominees.json`. Supply
`--snapshot-manifest-sha256`, `--preparation-root`, `--projects`, `--nominees`,
`--elan-home` and `--output` explicitly. The preparation lock serializes native
work; the script validates the volume cap and snapshot before/after execution.
The three-pin/two-draft ceiling is 81 process reservations, not 81 guaranteed
launches. Reference controls, all-pin inventory extraction, capture and local
replay have separately reported discovery costs. Whole/local families use the
same inventory, draft cap and screening policy. Their discovery overhead is
**not matched**, so this is not an equal-total-cost superiority experiment.

Local replay failures are retained for whole-source screening rather than
silently pruned. Only all-pin-valid candidates enter fresh balanced heartbeat
measurement (both execution orders, two repeats). There is no confirmation,
promotion, training or official score; the warmup target is already inspected,
not held out. A candidate with fewer tokens can still fail proof or heartbeat
checks. Empty families and infrastructure failures remain visible.

`tests/test_arena_local.py` covers stale prefix/pin/source/implementation,
malformed capture and mismatched replay receipts, zero/exact budgets, and explicit
fixtures. Its native controls exercise actual open namespaces/sections and fresh
whole-proof checks on installed Lean 4.26.0 and 4.34.0. The standalone replay
controls remain separate regression tests; none is an Arena performance score.
The [pilot record](ARENA_LOCAL_PREMISE_PILOT.md) retains exact commands, source
snapshots, failures, resource accounting and observed results.

### Whole-proof providers

The four injected value adapters are:

- `PremiseProvider`: nominate root-qualified terms, `exact`, or `apply` for
  ranked declarations. Small batches cover distinct premises before repeating
  application methods. Each alternative is a separate draft; whole-proof
  verification, not a large `first` portfolio, must establish closure.
- `RuleProvider`: nominate bounded paths through existing allowlisted rules.
- `JsonProvider`: replay an offline, request-bound response.
- `CommandProvider`: invoke an explicit, trusted executable with JSON stdin and
  stdout. This is the adapter point for a separately configured `llm_router` or
  hammer wrapper; there is no automatic provider discovery or live model call.

The request includes record/base/environment/scope/index/ranking hashes, the
exact statement, base source, tokenizer identity, and permitted nominations.
The response accepts **only**:

```json
{
  "request_sha256": "COPY_FROM_REQUEST",
  "proposals": [
    {"kind": "premise", "name": "Nat.add_zero", "method": "apply"},
    {"kind": "path", "rules": ["port_exact_hyp"]}
  ]
}
```

The example name must actually occur in that request's ranked premises.
Arbitrary Lean/Python, unknown rules, foreign names, claimed rewards, extra
fields, duplicate JSON keys, nonfinite numbers, and stale responses are rejected.
This initial integration does not mint new tactic code. Provider failure rejects
the entire response and continues to the next configured provider, subject to
the remaining batch deadline. The defaults are two deterministic providers.

Commands use no shell and inherit no environment credentials. Explicitly passed
environment entries are operator-owned. Combined stdout/stderr and wall time
are bounded; the launched process group is killed/reaped on timeout or overflow.
This is **not a security sandbox**: trusted adapters retain host/network access,
and a hostile executable can escape a process group or consume host resources.
Untrusted executable code needs separate OS isolation. No arbitrary in-process
callbacks are accepted, because their deadlines could not be enforced here.
Raw stderr/exception text and command credentials are not written to manifests.

## Use

The inventory schema is `jevops-premise-index/v1` with fields
`schema`, `environment_sha256`, and `premises`. Every premise has `name`,
`type_text`, `origin`, `split`, `aliases`, and `dependencies` (the last two are
arrays). The scope schema is `jevops-premise-scope/v1` with fields `schema`,
`record_sha256`, `environment_sha256`, `available_names`, `excluded_names`, and
`excluded_origins` (the last three are arrays). Python callers can use the typed
`Premise`, `PremiseIndex`, and `PremiseScope` constructors directly.

```bash
python -m jevops.arena_providers \
  --problem CallElimCorrect.extractedOldExprInVars \
  --premises /owned/premises.json --scope /owned/scope.json \
  --seed /owned/historical-seed.json --cap 8 \
  --output-dir /owned/new-provider-drafts
```

The CLI writes `request.json`, `manifest.json`, and `provider-N.json` drafts
programmatically, without overwriting an existing output directory. Optional
`--proposal-response response.json` files precede the deterministic fallbacks.
Source-deduplicated drafts must be shorter than the seed under the current
reference tokenizer. They remain **unverified**, including apparently trivial
lemma applications. Token filtering does not establish heartbeat savings.

Pass chosen `provider-N.json` files through the existing `arena_pareto
--candidate` interface, preserving the historical incumbent and original record.
Freeze code/inputs and predeclare `strict-dual-v1`, budgets, required versions,
both execution orders, and independent confirmation as usual. Do not inspect
canary failures and then call them an untouched evaluation set.

Only separately admitted, training-split native successes can supply compressed
teacher targets. Failures may supply negative examples, never positive proof
labels. CE/cosine/Jev surrogate evaluation and training admission are unchanged;
these modules do not optimize them or confer authority on their scores.

Run focused tests fresh:

```bash
python -m pytest --test-seal=off -q tests/test_premise_search.py tests/test_arena_providers.py
JEVOPS_ARENA_NATIVE_TESTS=1 python -m pytest --test-seal=off -q tests/test_arena_providers.py -k native_gate
```

The latter uses installed Lean v4.26.0 only, downloads nothing, and checks a
valid proposal plus unavailable-name and forbidden-axiom counterexamples.
These are correctness regressions, not Arena score measurements.

## Bounded native premise extraction

[arena_premises.py](jevops/arena_premises.py) now provides `NativePremiseExporter`.
It probes **up to 64 nominated names**, not every declaration in a library. It
reuses a `NativeLeanVerifier`'s exact target-free project prefixes, dependency
fingerprints and optional Docker configuration. Only the trusted prefix is
elaborated; no candidate or reference proof source is sent to the exporter.
No imports or toolchains are installed.

For every required pin, the Lean driver checks that the target is absent, looks
up each nominated declaration in the visible prefix, pretty-prints its actual
type and walks its type/value dependencies. Module-private proof data is loaded
only for that walk: it must not expose private premises to retrieval or hide an
axiom behind an exported theorem. Per-entry closure and output limits fail
closed rather than publishing truncated dependencies.

The resulting index admits only names available on **all** required pins, with
identical displayed type text, no nonstandard axioms, and no known protected
name anywhere in the transitive dependency closure. Type-text equality is a
conservative retrieval filter, not a proof of cross-version semantic identity.
Rejected entries retain reasons. Missing/malformed stages, changed dependencies
or implementation, timeout and insufficient process budget produce no inventory.
All-pin capacity is reserved up front; failed attempts are not refunded.

Given an already constructed native `verifier` and its benchmark `record`:

```python
from pathlib import Path
from jevops.arena_premises import NativePremiseExporter, PremiseOrigin, write_inventory

exporter = NativePremiseExporter(verifier, max_processes=len(verifier.context(record).versions))
report = exporter.export(record, (
    PremiseOrigin("Nat.add_zero", "stdlib", "library"),
), excluded_names=(record["name"],), excluded_origins=("protected-family",))
if report["status"] == "INVENTORY_ONLY":
    write_inventory(report, Path("new-premise-inventory"))
```

`inventory.json` and `scope.json` feed the existing provider CLI; `report.json`
contains generated all-pin observations, metadata and exclusions. The writer
refuses existing directories and fixture/partial exports. The source identity
remains the exact native verifier context; extraction implementation and request
hashes are also recorded. A trusted in-process runner can be injected for unit
tests, but its output is labeled `FIXTURE_ONLY` and cannot use this publisher.

The native report keeps complete bounded dependency closures. The retrieval
index projects edges onto admitted nominees only, so its `available_names`
never invents callable private names. Do not mistake these projected edges for
the full closure when building a later cache or audit. Importantly, the exported
files are **not authenticated certificates**: ordinary inventory loading still
accepts operator-supplied data. Prefixes, project metaprograms and local tools
remain trusted. Without an explicit Docker profile, execution is not sandboxed.
The deadline bounds process work and is checked around filesystem validation;
it cannot preempt a blocking filesystem call. The exporter has its own process
budget, separate from proof verification; it reports no heartbeat savings.

Provenance remains incomplete: the kernel cannot infer whether a lemma belongs
to a canary family or is a semantic duplicate of heldout material. Supply full
protected-name/family metadata; unlisted family members require explicit name
exclusions. Unknown semantic aliases cannot be detected by a constant-dependency
walk. No result grants proof acceptance, promotion or positive training labels.
New native inventory tests use `no_seal` even with `--test-seal=on`.

```bash
python -m pytest --test-seal=on -q tests/test_arena_premises.py
JEVOPS_ARENA_NATIVE_TESTS=1 python -m pytest --test-seal=on -q tests/test_arena_premises.py
```

Native controls use installed Lean 4.26, 4.27 and 4.34, with no downloads. They
test module privacy, hidden axioms, protected wrappers, missing names, resource
limits, target leakage and provider-to-verifier roundtripping, not Arena scores.

The exporter also has a bounded CLI for prepared Arena projects. `nominees.json`
is an array of objects containing exactly `name`, `origin`, and `split`. The CLI
excludes every target name in the supplied corpus, plus explicit exclusions,
and requires exactly one project binding per required pin. `--trusted-local`
explicitly selects the existing trusted-project execution model; use the Python
API for an explicit Docker profile. It never builds or downloads dependencies.

```bash
python -m jevops.arena_premises --problem PROBLEM --projects /prepared/projects.json \
  --nominees nominees.json --trusted-local --max-processes REQUIRED_PIN_COUNT \
  --output-dir new-inventory
python -m jevops.arena_providers --problem PROBLEM \
  --premises new-inventory/inventory.json --scope new-inventory/scope.json \
  --seed incumbent.json --cap 3 --output-dir new-drafts
```

The default process allowance is zero. An incomplete extraction writes only a
failure report, not usable inventory/scope files; previous evidence is never
overwritten. Submit generated drafts to `arena_pareto` with the same incumbent,
frozen code/inputs, strict-dual selection and a predeclared confirmation reserve.

To check the generated artifact chain without rerunning Lean:

```bash
python -m jevops.arena_report_audit --protocol selection/protocol.json \
  --report selection/report.json --inventory-report new-inventory/report.json \
  --provider-manifest new-drafts/manifest.json --output-dir new-pipeline-audit
```

This optional audit checks record, pin, scope/index, request, incumbent and draft
bindings, and separates discovery work from proof measurements. It expects an
explicit incumbent. Consistent unsigned JSON still grants no fresh proof,
performance, promotion or training authority. The discovery context can differ
from later measurement settings; selection must verify every draft freshly.

## Frozen Arena pilot, 2026-09-23

The generated [selection summary](papers/completion/lean_refactor_arena/evidence/native-premise-provider-pilot-2026-09-23/selection/summary.md)
and [pipeline audit](papers/completion/lean_refactor_arena/evidence/native-premise-provider-pilot-2026-09-23/audit/summary.md)
record a bounded run on `CallElimCorrect.extractedOldExprInVars`, using its exact
Strata revision and Lean 4.26 pin. This is a repeatedly inspected development
problem, **not a fresh canary or an official Arena submission**.

One native export admitted four nominated list-subset lemmas from the original
prefix. The deterministic provider selected three distinct whole-proof terms.
All counted as one token, but all twelve draft executions failed Lean with type
mismatches. All eight original/incumbent checks passed, retaining the historical
**185-token incumbent**. Status: `NO_IMPROVEMENT`; no confirmation, reward,
promotion or training occurred. Rejected drafts have **missing**, not zero,
accepted heartbeat observations.

The unchanged strict-dual schedule used both branch orders and two repetitions,
with a 32-request ceiling including 12 reserved confirmation requests. Actual
work was one export plus 20 selection processes. The 118-file source/input
bundle was checked unchanged after the run. Reports and receipts were generated
by the exporter, provider, selector, snapshot checker and report auditor; they
were not hand-authored. Inventory extraction used a 180-second limit, and later
measurement used 120 seconds; those are separate contexts, with every proof
checked freshly in the latter. No heartbeat speedup is inferred from discovery.

This pilot establishes integration and rejection behavior, not optimizer quality:
lexical relevance does not mean a lemma proves the entire goal. The next
algorithmic increment should use these premises in **local proof-state edits**,
followed by whole-proof verification at the same fixed objective. Do not train
on the tiny invalid sources or keep probing canaries until they become training
examples. The saved-evidence regression only audits bookkeeping; rerunning it
does not recreate native proof or timing evidence.

## Further upstream reuse review, 2026-09-23

Revalidated on 2026-09-25 against the same local revision and unchanged reviewed
paths. The [current audit](papers/completion/lean_refactor_arena/evidence/goal-plan-audit-2026-09-25/README.md)
records exact file hashes and six fresh identity/serialization probes. No
upstream package import, solver execution, source copy or runtime dependency
was added by that audit. Adaptation boundaries below remain in force.

The additional review used the local `/home/barberb/ipfs_datasets_py` checkout
at `7f0d38572f92f5fc0cba7a5ddd4bef28523876f3`. This is a separate snapshot
from the revision cited above; that earlier object is unavailable in this
checkout, so this review does not claim a commit-by-commit comparison.
Paths below are relative to upstream `ipfs_datasets_py/logic/`.

| Upstream implementation | Useful adaptation here | Required boundary |
| --- | --- | --- |
| `hammers/premise_selection.py`, `tactician/planner.py` | Already adapted: deterministic retrieval, explicit exclusions, bounded nominations and fallback | Keep Lean identifiers case-sensitive; lexical overlap and caller-supplied provenance are not typing or native inventory attestation |
| `hammers/learned_selector.py::select_premises_gated` | Next learned-selector increment: pin model/feature identities, record missing/corrupt/mismatched-model fallback, preserve deterministic baseline | Reorder only eligible premises; preserve heldout exclusions and exact budgets; model identity does not establish model quality or proof validity |
| `hammers/portfolio.py::SolverPortfolio.run` | Later discovery scheduler: shared resource budget, bounded concurrency, per-attempt outcomes and cancellation accounting | Do not stop compression search just because a solver claims success; reserve fresh strict-dual confirmation and measure candidates without concurrent discovery contention |
| `hammers/proof_cache.py::PersistentProofCache.get_or_compute` | Coalesce identical in-flight discovery work within one process and retain context-bound historical evidence | Use exact source bytes and complete environment/policy identity; add waiter deadlines/cancellation; never substitute cached evidence for fresh cost confirmation or repeatedly reward a cache hit |
| `software_verification/tactician/candidate_synthesis.py::ProofCandidatePortfolio.synthesize` | Typed per-hole proposals, stable ordering and explicit unsupported/unavailable outcomes | Adapt the value contract, not unrestricted in-process callbacks; deadlines must cover provider work before collecting/sorting all hits |
| `hammers/reconstruction.py`, `hammers/receipts.py` | Separate untrusted solver results from reconstruction evidence and generate receipts programmatically | Keep our exact-statement, axiom, all-pin and source/export checks; serialized trust flags are not independent attestations |
| `translations/planner.py` | For a future definition-equivalence adapter: compose preservation/assumption/loss contracts and retain the weakest authority along a translation path | Require explicit coverage for the supported Lean fragment; unknown feature coverage fails closed. A planner's declared preservation contract is not a checked equivalence proof |

Do **not** transplant the upstream proof cache's text-obligation key unchanged.
`canonicalize_obligation` strips indentation, collapses horizontal whitespace
and normalizes Unicode before `ProofCacheKey.build` hashes a text obligation.
A read-only probe of that key builder found the same key for these distinct
inputs, holding every other key field constant:

```lean
theorem spaces : "a  b" = "a b" := by rfl
theorem spaces : "a b" = "a b" := by rfl
```

This demonstrates an identity collision for **raw-source use**, not a claim
that every upstream caller uses that representation. The probe did not run
Lean. JevOps `arena.source_hash` distinguishes the two strings. Provider
regressions additionally protect string whitespace, indentation and Unicode
normalization: changing any of them invalidates a request-bound old response.
Any future discovery cache must preserve the same exact-byte boundary.

Additional read-only probes of the same revision's key/serialization definitions
found `content_digest({1: "v"}) == content_digest({"1": "v"})`, and a custom
object with `str(obj) == "same-label"` sharing a digest with that string. The
serializer stringifies mapping keys and falls back to stringifying unsupported
objects. JevOps' strict `proof_ca.canonical_json` rejects both the non-string
key and the opaque object; retain that fail-closed behavior. Together with the
raw-source key and JevOps source-hash comparison above, these were six asserted
identity/serialization checks, not native Lean or full upstream package tests.
The probes executed only the reviewed definitions extracted from that file;
they did not instantiate a persistent cache, import global services or run a
solver. A direct standalone file import was unsuitable because the module also
has package-relative compatibility imports.

The broader logic review also found adaptation constraints beyond cache keys:

- `ProofCandidatePortfolio` treats `max_candidates_per_hole=0` as a fallback
  to `budget.max_candidates or 16`; it gathers provider hits before limiting
  them, and replaces a mismatched hit's `hole_id` with the current hole ID.
  JevOps must instead reserve before work, treat zero as exhausted, enforce a
  provider deadline and reject mismatched target/context identities. Test these
  cases before integrating the contract; no upstream semantics were changed.
- `tactician/planner.py` accepts a policy label or its digest as `config_root`.
  Our verification/cache identity needs the policy's content digest, even when
  a human-readable label is also recorded. A label reused for changed options
  must not preserve an old admission or cached outcome.
- `hammers/portfolio.py` can obtain an ambient resource scheduler. Inject the
  JevOps ledger explicitly; discovery concurrency must not bypass the one-build
  allowance or contend with final heartbeat measurement.
- `translations/planner.py` treats paths with no declared feature preconditions
  as unconstrained. For Lean transformations, absence of coverage is unknown,
  not evidence of supported syntax or semantic preservation. Reject unsupported
  constructs and require the equivalence/caller obligations in the safety plan.

These are boundaries for **adaptation**, not claims that upstream conventions
are erroneous for every existing caller. Hammer/tactician are tracked Python
modules, while `.gitmodules` lists separate CEC components. Those CEC worktrees
were dirty and were not evaluated or copied. Do not pull that dependency stack,
domain-specific default adapters or the broad logic README's performance claims
into the Lean optimizer. Review license and record revision provenance for any
later source copy; this review adds no external runtime dependency.

The upstream default graph-selector artifact is a hand-authored linear score,
not a gradient-trained GNN or autoencoder. Reuse its model-identity/fallback
contract, not its name as evidence of learning. The single-flight cache also
waits without a timeout on its shared event; bounded callers need deadline and
cancellation propagation before adopting that mechanism.

Upstream reconstruction currently tries premise hints plus a small native
fallback portfolio, rather than generally translating ATP proof traces. Its
Lean `first` portfolio is a discovery mechanism, not evidence of minimum
tokens/heartbeats. Emit alternatives separately and minimize/recheck the
successful replay before comparing costs.

Priority: extend bounded native inventories/provenance and finish verifier/measurement
gates first; evaluate the existing deterministic providers at equal budgets;
then add scheduling/deduplication and, only with useful training data, learned
reranking. These additional adaptations are a roadmap, **not implemented by
this review**. No upstream package dependency, solver trust flag or cache-key
normalizer was imported into the production path.
