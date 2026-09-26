# Federal-law training: the next JevOps integration tranche

Planning audit: 2026-09-25. **Proposed work, not a completed formalization or
deployment.** JevOps baseline: `e6d54af65c470e702dab797a3bbe90c17b84cfda`.
Sibling `ipfs_datasets` HEAD observed:
`ddf6b79467b68159650df81befc288c8553df664`, with 25 tracked modified files.
Its HEAD alone does not identify the inspected working tree. Freeze exact source
contents before qualification; do not reset either repository or discard edits.

Implementation follow-up: the first [legal source-lock slice](LEGAL_SOURCE_LOCK.md)
now rejects the helper-substitution finding below and bounds proof edits in both
legal admission entry points. The follow-up [explicit legal adapter](LEGAL_ADAPTER.md)
adds opt-in owned sessions and before/after guards over caller-declared source
files to tools, admissions and the Leanstral loop. These implement source-envelope
and dependency-injection portions of M0, not native qualification or a complete
toolchain identity. Toolchain-bound receipts and corpus/training integration
remain pending. Historical planning observations below retain their original scope.

This is the JevOps integration and prioritization companion to the existing
[federal-law master plan](../external/ipfs_datasets/docs/implementation/plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md),
not a replacement scheduler, model framework, or duplicate implementation of its
codecs. Sibling links below use the current workspace layout; they will not
resolve in a standalone JevOps clone. Production integration must replace that
layout dependency with an explicit pinned adapter/artifact contract.

## 1. Outcome and scope

Build a versioned, queryable corpus with exact source text, typed candidate
interpretations, dependencies, review decisions, Lean obligations and evidence,
training lineage, and explicit gaps. Use the existing DuckDB owner and artifact
storage locally; distribute selected immutable Parquet releases through Hugging
Face. Train for better source-grounded formalizations, not merely more iterations.

First scope: one declared U.S. Code release plus a versioned Constitution and
amendment source set. This is **not all federal law**: the Code omits temporary
and special laws, and does not contain the whole regulatory or judicial corpus.
Track uncodified statutes, CFR/Federal Register, treaties and judicial
interpretations as separately scoped extensions, not silently covered material.
The [OLRC FAQ](https://uscode.house.gov/faq.xhtml) explains the Code's limits;
the [National Archives transcription](https://www.archives.gov/founding-docs/constitution-transcript)
distinguishes original text and subsequent amendments.

Define three different milestones:

1. **Source-complete:** every expected source unit in the declared release is
   accounted for, including missing, inactive, nonoperative and unsupported units.
2. **Profile-formalized:** a unit's required meaning and dependencies are covered
   under a declared semantic profile and interpretation branch, with review and
   any required proof evidence. A proved numerical subclaim is not the whole law.
3. **Release-complete:** the selected artifact closure is durable, queryable after
   restart, reproducibly packaged and independently checked at a remote revision.

Never merge source integrity, legal applicability, semantic fidelity, optimizer
acceptance, Lean checking and publication into a single success flag. Existing
Constitution inventory remains `formalized=false`; do not turn `roundtrip_ok`
on to satisfy a coverage goal. A future constitutional admission policy needs
separate reviewed qualification. Complete legal interpretation cannot be promised
from a compiler or model-loss result.

## 2. Reuse and present evidence

| Existing component | Reuse | Remaining boundary |
| --- | --- | --- |
| JevOps `proof_ca.py`, `plan.py`, typed dependency work | Local checked inference, fair work, immutable reasoning epochs | Ground positive Horn reasoning is not a general semantics for exceptions, powers or repeal |
| `autoformal_tools.py`, `statement_lock.py`, Lean/Arena verification | Bounded tools, source-bound proof search, isolated verification | Inject the legal adapter; lock helpers and complete package; emit durable receipts |
| `autoencoder_training.py`, graph/scoped/rewrite training | Frozen splits, sparse heads, verified refactor teachers | JevOps Lean models and the sibling modal model have different state schemas; no direct weight merging |
| `duckdb_ingest.py`, `knowledge_index.py`, `skillcenter_corpus.py` | Bounded inserts, immutable provenance, strict Parquet/CID checks | SkillCenter schema is not a legal corpus schema; add a narrow legal adapter |
| Sibling target/report bundles and daemon sessions | Exact full targets/reports, requested-only hydration, source guards | Qualify complete daemon reuse and partitioned corpus coverage |
| Sibling state transactions, sparse checkpoints, coordinator/registry | Accepted patches, parent binding, leases, owner replay, compaction | Full-cycle daemon sparse authority remains distinct from worker sparse support |
| Sibling Arrow inputs and `modal_autoencoder_arrow_weights.py` | Read-only buffers, private row overlays, exact float/key checks | Only selected inputs/feature weights are covered; native daemon benefit unqualified |
| Sibling source index, embedding producer, legal IR and HF release modules | Pinned sources, frozen membership, existing publication/outbox contracts | Full source closure, independent semantic review, durable proof retrieval and remote qualification |

Key implementation sites in the sibling are under
`ipfs_datasets_py/optimizers/logic_theorem_optimizer/`:
`autoencoder_corpus_index.py`, `autoencoder_embedding_production.py`,
`legal_ir_target_bundle.py`, `legal_ir_report_bundle.py`,
`autoencoder_daemon_{target,report,weight}_session.py`,
`modal_autoencoder_{state_transaction,patch_codec,sparse_checkpoint}.py`,
`autoencoder_daemon_invocation.py`, and `autoencoder_training_coordinator.py`.

### What the archived measurements actually establish

These are inspected historical reports, **not rerun benchmarks in this planning
pass**, and they describe different workloads and source revisions.

| Recorded experiment | Observation | Decision |
| --- | --- | --- |
| [Source-bound worker jobs](../external/ipfs_datasets/docs/implementation/reports/autoencoder_produced_corpus_arrow_training.md), three train + three validation records | Fresh targets: 87.0047 s; shared JSON: 22.9321 s median. All eight jobs rejected their optimizer update | Reuse can amortize preparation; this is not learned improvement |
| Same worker report, mapped inputs | 23.0663 s median versus 22.9321 s JSON | No measured input-mapping speed win on this small batch |
| [Actual target-only daemon pair](../external/ipfs_datasets/docs/implementation/reports/autoencoder_daemon_shared_targets.md) | Whole call 93.382 → 106.976 s; diagnostics 2.619 → 50.736 s; peak RSS +41.70% | Target-only sharing moved work into diagnostics and regressed end-to-end cost; keep default off |
| [Full-report daemon integration](../external/ipfs_datasets/docs/implementation/reports/autoencoder_daemon_shared_reports.md) | Exact codecs implemented; native comparisons invalidated by producer edits | Stabilize sources and measure the actual full path before claiming a fix |
| [Daemon Arrow feature weights](../external/ipfs_datasets/docs/implementation/reports/autoencoder_daemon_mapped_weights.md) | Opt-in owner binding and 772 reported fixture passes; native validation deferred | Do not treat fixture parity as daemon throughput evidence |
| [Complete-state sparse shadow](../external/ipfs_datasets/docs/implementation/reports/autoencoder_daemon_sparse_shadow.md) | Exact historical zero-update and archived changed-state replay; full checkpoint remains authoritative | Qualify real changed-state whole-cycle capture before sparse-only authority |

Historical master-plan counts (60,077 U.S. Code rows, 60,068 canonical entries;
231 Constitution spans with zero compiled) are inventory observations, not a
fresh census, current-law completeness, or proof counts. The qualified source
pilot produced 51 vectors from 64 selected records; 13 exceeded its token cap.
Do not delete those 13 from corpus coverage or call the excluded canary passed.

### Gaps reproduced or confirmed by this audit

- `statement_lock` preserves theorem strings but not helper definitions. A
  read-only diagnostic replaced `decide (bound <= n)` with `decide (n = bound)`
  in a threshold example; the lock accepted it. Both still fit its two boundary
  examples, but differ above the threshold. No Lean run or admission occurred.
- The legal loader uses a hardcoded sibling path and ambient module/session
  state. Keep compatibility, but give new corpus runs explicit dependencies.
- `ProofCorpusDuckDBRepository` defaults to process-local blob/index state;
  `DuckDBProofStore` uses an `OrderedDict`. DDL/SQL mirroring alone does not prove
  fresh-process retrieval of the complete evidence closure.
- `ir_publisher.py` can construct remote verification metadata from its local
  plan when remote observations are absent. That fallback must not count as
  independently verified remote publication.
- Public Hub metadata for `justicedao/ipfs_uscode` returned revision
  `5016b86a273ce5e4ffd066c5ae9f5fe494dd417e` and 2,802 files. Dataset Viewer
  `/splits` and `/size` returned HTTP 500. This establishes neither corruption
  nor row coverage. Pin a manifest and verify actual artifact closure.

## 3. One pipeline, explicit owners

```text
Pinned sources → versioned spans/dependencies → frozen samples/splits
                                               ↓
                                 shared reports + derived targets
                                               ↓
               existing worker: immutable base + private sparse overlay
                                               ↓
                       owner replay + validation → candidate model version
                                               ↓
        source-grounded IR proposal → semantic review → locked Lean package
                                               ↓
                          verifier-owned evidence + explicit gaps
                                               ↓
             DuckDB catalog + durable artifacts → outbox → HF release
```

JevOps handles bounded proposals, local dependencies, proof/refactor operations
and its existing improvement harness. The existing sibling owner handles model
versions, leases, fences and durable job decisions. Link IDs and receipts across
that boundary; do not run two schedulers claiming the same work.

Inject a pinned `LegalCorpusAdapter` into new JevOps runs: source retrieval,
target/report resolution, existing-owner submission/status, and evidence lookup.
Keep model/router selection explicit; no inference from an old credential or
default remote endpoint. Existing legacy functions remain thin compatibility
wrappers, not the new authoritative corpus path.

DuckDB transactions register verified metadata and pointers. Artifact hashing,
training, replay, encoding and uploads happen outside short transactions. Use
the existing owner/Quack route, not independent writers to the same native file.
Current [DuckDB concurrency guidance](https://duckdb.org/docs/stable/connect/concurrency.html)
distinguishes in-process ownership from server/catalog-mediated concurrency.
DuckLake delivery remains a separate outbox transaction and qualified adapter;
do not make a new storage service a prerequisite for the first local slice.

## 4. P0: reproducible identities and the admission boundary

Freeze an exact, isolated source manifest for both repositories and their
relevant dependencies, including the intended uncommitted changes. Existing
guards caught real concurrent edits: do not weaken them. Hash at startup and
final receipt; qualify imports from the frozen tree, not a mutable resident
module cache. Existing daemons, protected checkpoints and archives stay intact.

Define a source-neutral record for Constitution and Code, replacing fake
`US-CONST U.S.C.`-style compatibility citations in the qualified path. Retain:
stable legal ID; release/content version; raw byte selectors and normalization
maps; parent/child structure; source authority and rights; legal effective
interval and recorded time; definition/reference closure; interpretation profile.
Preserve title appendices, notes, tables, repeated text and every segmented child.
Distinguish source credits/editorial notes from operative provisions.

Reconcile a selected full source inventory against pinned OLRC/USLM manifests;
keep current-source acquisition failures as explicit gaps. Positive-law status
is provenance, not a model label. The [OLRC guide](https://uscode.house.gov/detailed_guide.xhtml)
explains source credits and editorial integration. Fetching a current download
index was blocked in this audit, so no new official release was authenticated.

Replace theorem-string admission with a complete immutable package contract:
source span, reviewed IR, target type, helper definitions, imports, toolchain,
dependency/axiom policy and candidate proof bytes. Restrict proposed edits to
qualified proof spans; verify the resulting declarations and dependency closure.
Keep existing no-import/no-sorry/no-admit/no-new-axiom legal restrictions.
`lake build Legal` is necessary in the current legal path, but successful build
output alone is not semantic fidelity or proof of an unbound intended claim.

Exit: helper-substitution attacks fail; exact source selectors replay; fresh
processes reproduce source/context IDs; ambiguous/missing provenance cannot
enter training or mint admission.

## 5. P1: share complete reports, not just teacher summaries

Here, "shared targets" means reusable source-derived training supervision,
not shared theorem names or a cached model prediction.

Extend the existing full-report bundle path to one partitioned report inventory.
Every report binds exact sample/vector bytes, source and dependency versions,
parser/compiler/grammar/bridge revisions, ordered bridge configuration, options,
timeouts and label authority. Share across model versions only where generation
is model-independent; otherwise include the generating model identity.

Prepare once; give training, acceptance validation and diagnostics the same
qualified reports and derived native target objects. Each candidate still
computes its own predictions, losses, grammar decisions and acceptance. Never
replace a full target with a dictionary that silently loses scoring attributes,
or reuse model-dependent evaluations under a target-only cache key.

Use bounded shards and requested-only hydration. Preserve ordered fields,
aliases required by native consumers, rich grammar data and adapter outcomes.
`ready` means the artifact is available, not that all bridges succeeded. Keep
unsupported semantics separate from transient failures/timeouts and retry only
the latter under explicit limits. Retain raw timestamp-bearing graph identities;
any semantic comparison excluding volatile fields needs a versioned allowlist.

Measure hydration, diagnostic reuse and snapshot paths as well as initial
evaluation. No silent resampling to fit whichever reports are cached. Missing
selected rows produce an explicit incomplete/preparation job. Cache eviction
must enforce encoded bytes, expanded bounds and measured worker memory; evict
only rebuildable materializations, not source or admission history.

Exit: matched complete-cycle parity and repeatable amortized benefit, or keep
the option off. Break-even is measured from preparation + all loading/checking +
N complete jobs, not one warm evaluation. Start with the existing six-record
diagnostic fixture, then a new frozen 100/1,000/10,000-span scaling series within
capacity. These proposed sizes are not claims of representativeness.

## 6. P2: sparse updates with whole-cycle replay

Keep three concepts separate: sparse feature computation, sparse mutation
capture, and sparse checkpoint persistence. One does not establish the others.

Reuse the native transaction/patch/checkpoint contracts. Record component/key,
operation, precondition, exact new value, base version, ordered sequence,
operation ID and resulting identity. Preserve absent versus zero, deletion,
empty rows, iteration order, scalar types, signed zero and operational revision.
Optimizer moments/counters, vocabulary, memory and schedules belong to exact
resume state, even if only weights are presented as the learning result.

Cover mutations after projection: TODO/guidance updates, pruning/compaction,
rollback, snapshot completion and shutdown. First compare sparse shadow replay
with the independently loaded authoritative full final checkpoint for both
rejected and genuinely accepted native updates. A synthetic scalar insertion
tests storage, not learning. Never force an accepted update by relaxing the gate.

Workers stage immutable patches; the owner independently replays and checks
them, then uses its existing fenced compare-and-swap to register a candidate.
Duplicate completion must not charge, advance steps or publish twice. Reject
stale parents. Concurrent independently trained branches are separate candidates,
not automatically additive gradients; rebasing requires renewed evaluation.

Bound chain depth/bytes, reserve compaction space, and compact through the owner
outside its short commit. Prove full-anchor + patches reconstruct every field
after restart and crash at each stage. Keep full checkpoints authoritative until
the full-cycle gate passes; sparse shadow remains useful without promotion.

Exit: corruption, missing/reordered patches, lease loss, interrupted compaction,
duplicate delivery and shutdown mutations are covered; accepted native changes
replay exactly with measured transport/write savings.

## 7. P3: Arrow-backed weights where they help

Use existing uncompressed IPC mappings for immutable numeric bases and private
copy-on-write rows for changes. Parquet is the compressed durable exchange
format. [Arrow IPC documentation](https://arrow.apache.org/docs/python/ipc.html)
supports mapped reads, not a blanket claim of zero-copy training. Respect the
repository's pinned supported versions; do not upgrade dependencies implicitly.

Qualify the existing feature-weight component first. Measure how long the daemon
stays mapped and when pruning/state replacement detaches it. Include repeated
hashing, key indexes, scalar boxing, snapshots and full serialization. Never
reattach an old base after native state replacement. Close mappings only after
all consumers/snapshot copies have detached; read-only views may retain buffers.

Then add one measured hot component at a time, with matching presence/offset/key
and precision contracts. Restart12's legacy prose feature keys must not bypass
the typed-key validator: retain a private lossless codec or qualify a separate
semantic migration. Do not hash/drop keys merely to satisfy an export schema.
Do not change float precision, reduction order or optimizer mathematics in a
storage experiment. Add hot buffer accessors only where profiling shows list
materialization; count fallbacks explicitly.

Exit: exact numerical/state/update/rollback parity; mapped buffers really back
reads; bounded overlays; clean asynchronous lifetimes. Compare total time,
PSS/private dirty pages, faults, bytes and throughput at 1/2/4 workers after
resource admission. RSS double-counts shared pages. Keep JSON/native defaults if
neither useful throughput nor memory-limited capacity improves.

## 8. P4: train for semantic improvement

### Distinct learning tasks

- **Modal/IR learner:** structure, roles, operators, time, exceptions, references,
  applicability and abstention. Current modal autoencoder losses are advisory;
  they are not a demonstrated general text-to-Lean decoder.
- **JevOps proof learner:** premise retrieval, scoped construction, replay and
  refactoring of already locked, supported obligations. Shorter/faster proofs
  improve proof engineering, not the fidelity of the original legal translation.
- **Scheduling policy:** which eligible gap/tactic receives effort. Existing
  bandits can allocate a bounded experiment budget; maintain FIFO coverage so
  difficult provisions do not disappear. Priorities cannot create legal facts.

Build a source-grounded annotation pilot, proposed initial size 200–500 spans,
stratified by source type, length, references and semantic family. Two independent
reviews plus adjudication for critical disagreements; record reviewer authority
and unresolved interpretations. Distinguish reviewed gold, compiler silver,
synthetic counterfactuals and unknown/unsupported examples. Parser roundtrip and
multi-bridge agreement are consistency signals, not independent legal truth.

Freeze grouped splits before target preparation/tuning: source lineage and
amendments, duplicate formula families, paraphrases/translations, and derived
IR/proof siblings stay together. Evaluate grouped in-distribution performance,
unseen titles/families and later-release deltas separately. Audit cross-split
retrieval to prevent gold IR/proofs entering prompts. Existing repeatedly viewed
examples are regression/development data; checkpoint history may prevent claiming
an unseen holdout. Do not use the final test set for line search or bandit reward.

First diagnose the archived rejection by family and head on development data:
label validity, feature coverage, gradient direction, imbalance, optimization
step and retention. Keep the existing acceptance thresholds. Compare:

1. Frozen deterministic compiler/router baseline.
2. Reviewed-only supervised sparse-head training.
3. The same training plus reviewed boundary/counterfactual negatives.
4. The same plus provenance-weighted provisional targets and balanced replay.
5. Only if justified, a constrained structured generator or JevOps graph-policy
   extension, with its own schema, training evidence and capacity comparison.

Track per-family typed slot/operator accuracy, units and negation/exception
scope, dependency resolution, exact/differential outcomes, abstention calibration,
critical semantic errors and reviewed proposition coverage. Normalize losses by
their real denominators, not sums of batch means. Promotion requires zero new
critical regression in the declared suite and a predeclared improvement with
uncertainty reporting; an accepted optimizer step alone is insufficient.

Train curricula from actors/actions to Boolean/quantifier scope, durations and
deadlines, definitions/references, eligibility, powers/procedures and temporal
priority. Constitutional institutional powers must not be coerced into obligations.
Use [Catala](https://arxiv.org/abs/2103.03198) as a design reference for explicit
statutory computation and lawyer/programmer review, not a claim that our compiler
inherits its correctness proof. Following the testing approach in
[CUTECat](https://arxiv.org/abs/2410.18212), add boundary and exception-path tests
to supported computational profiles; SMT-backed concolic exploration can remain
an optional adapter. Tests do not prove faithful interpretation of all prose.

The positive Horn cellular kernel stays unchanged in scope: explicit assumptions
and checked monotonic implications within one epoch. Legal negation, defeasible
priority and changed applicability require a separately specified typed semantics
or an explicit unsupported outcome, not missing-fact-as-false or neural voting.

Mandatory regression examples: `within 10 days unless emergency` retains deadline
and exception and is not rendered as a minimum; `shall not disclose` is a
prohibition; `at least 20 days` retains its integer/unit; empty parser vocabulary
abstains; changed helpers/definitions cannot preserve a false admission. Include
limits, competing exceptions and missing referenced definitions.

## 9. P5: durable corpus, incremental updates and HF distribution

Extend existing logical table families rather than placing everything in one
JSON/status column. Proposed mappings, not yet installed schemas:

| Table/view family | Required linkage |
| --- | --- |
| Source releases/versions/spans/dependencies | Exact bytes and selectors, legal IDs, valid/recorded time, source authority, rights |
| Sample/split/target/report membership | Frozen roles, label authority, producer/embedding IDs, per-adapter outcomes and artifact closure |
| Model versions/runs/patches | Base, accepted mutations, evaluations, owner decisions and checkpoint/materialization identities |
| Formalization attempts/interpretations/reviews/gaps | Source/profile/branch, supported meaning, assumptions and unresolved residue |
| Lean obligations/packages/verifier events | Intended type and helpers, complete dependency policy, actual command and bound evidence |
| Release membership/publication outbox | Immutable snapshots, artifact closure, destination/expected parent, remote receipt and verification level |

Use typed searchable projections plus retrievable complete artifacts. Prove
fresh-process restore, not just same-process lookup or successful DDL. Export
schema-homogeneous Parquet configurations for sources, candidates, reviewed IR,
Lean/evidence and gaps. Keep exact-resume/private model packages separate from
public inference weights and legal datasets. DuckDB can query these releases
without loading whole tables into Python.

Provide views for inventory coverage, training eligibility, pending dependency
work, reviewed obligations, verified proofs, release readiness, and legal-as-of /
known-at / interpretation-branch retrieval. A partial numerical formalization
must not make a section disappear from the unresolved coverage view.

For an amendment or compiler/definition change, create a new source/semantic
epoch. Use typed reverse dependency indexes to enqueue the affected closure,
retain old evidence historically, and explicitly requalify reusable artifacts.
Measure touched cells/edges, reused/rebuilt reports, reverified obligations and
bytes. Cycles require explicit resolution state; very broad changes may correctly
touch most of the graph. Sparse updates are not a promise that every change is local.

Use existing publication seals, expected-parent checks and owner outbox. Upload
only a selected fully validated release after destination/privacy approval;
record independent remote inventory at its returned commit and, where required,
byte verification. Local-plan fallback stays `verification_pending`. Remote
failure must not undo local training completion. Dataset cards report exact
source release, separate coverage denominators, limitations, rights, review
status and reproducible queries. Explicit configs/file lists follow
[HF manual configuration](https://huggingface.co/docs/hub/datasets-manual-configuration).
Viewer availability is a separate health signal, not proof of payload integrity.

## 10. Experiment and delivery gates

First freeze a source-stable complete baseline. Then compare identical task sets,
base checkpoints, budgets, diagnostics and acceptance rules:

| Arm | Change from matched baseline |
| --- | --- |
| E0 | Native full cycle, live reports, ordinary weights/full checkpoints |
| E1 | Verified full reports + derived targets shared across all eligible consumers |
| E2 | E1 + complete-state sparse shadow, then qualified sparse persistence |
| E3 | E1 + mapped inputs only |
| E4 | E1 + mapped feature weights only |
| E5 | Qualified E2/E3/E4 combination |

Keep shadow overhead visible; it cannot measure the savings of a future sparse-only
path. Use at least three counterbalanced pairs for a first pilot, fixed seeds and
isolated memory/cache directories. Pin the five-bridge recipe used by historical
comparisons; record actual names, prover/cache flags and sample-memory policy
per pass. Fresh processes do not imply cold OS caches. Include preparation,
imports, failed/rejected work, asynchronous drain, durability and owner checks in
end-to-end time. Report stage distributions, peak hydration memory, PSS, row/byte
counts, accepted/rejected updates and actual cost when measured. No API cost or
GPU advantage is inferred from fixtures.

Suggested rollout (engineering estimates after stable prerequisites, not a date
for complete federal-law formalization):

| Milestone | Main change sites | Exit deliverable | Indicative effort |
| --- | --- | --- | --- |
| M0 | JevOps legal adapter/statement boundary; existing source manifests | Reproducible fixture + closed helper/package identity | 2–4 days |
| M1 | Existing corpus index/import and Constitution adapter | Reconciled source census, frozen role manifest, every gap retained | 3–6 days for a bounded slice; full acquisition unestimated |
| M2 | Existing report session/preparation and daemon harness | Valid complete E0/E1 pair series; decision on default | 2–5 days, after stable source window |
| M3 | Existing transactions/owner/shadow/checkpoints | Accepted and rejected native whole-cycle replay + crash recovery | 4–8 days |
| M4 | Existing mapped inputs/feature weights and hot accessors | E3/E4 parity and capacity measurements; expand only if useful | 3–6 days for existing components |
| M5 | Existing modal/JevOps learners and semantic compiler | Reviewed pilot, ablations, untouched evaluation and promotion decision | Set after annotation pilot; can proceed alongside storage |
| M6 | Existing evidence repositories, HF release/seal/outbox | Restartable full-row corpus and deterministic offline HF package | 5–10 days for a bounded slice |

M0/M1 precede corpus-scale reuse. M2 and M3 can be developed independently with
fixtures; M4 should not delay semantic work. M6 starts offline without waiting
for live publication. Do not sum these estimates into a promise of complete law
coverage. Expert review, long-source handling and acquisition are unmeasured.

Carry forward the conservative provisioning ceiling: one isolated Lean build
at a time and at most 50 GB for the selected experiment workspace unless revised.
Reserve space for targets, expanded working sets, WAL, compaction, retained
failure evidence and exports; stop before exceeding it. A whole-corpus report
cache is not assumed to fit. No automatic deletion of protected data, model
download, paid call, new daemon or remote publication follows from this plan.
Native validations previously deferred remain opt-in.

### First complete vertical slice

Choose one reviewed supported U.S. Code provision, one deadline/exception case
that must abstain from the narrow renderer, and one constitutional inventory gap.
Exercise exact source → frozen samples → full shared reports → candidate update
→ owner decision → reviewed IR → locked obligation → real verifier evidence
where supported → fresh-process DuckDB retrieval → offline HF package.
Include duplicate completion, missing artifact, rejected update, changed source
and restart. Produce a new candidate even if it is rejected; never manufacture
an accepted model update or constitutional proof to finish the demonstration.

Success for this tranche: cheaper repeated work **with unchanged trust gates**,
measured improvement on reviewed legal tasks, and honest durable coverage. The
complete source ledger is attainable before every provision is formalized.

## 11. Verification performed for this plan

Read-only code/report audit and bounded unauthenticated metadata/documentation
requests; no corpus download, live model call, Lean build, training campaign,
daemon change or upload. The Hugging Face datasets skill informed split/size
discovery and the decision to keep manifest validation independent of Viewer.
The connected dataset-search tool was disabled, so public HTTP metadata was used.

This exact JevOps offline command completed with **78 passed in 4.71 s**:

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
  python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-federal-plan-tests/cache \
  tests/test_proof_ca.py tests/test_duckdb_ingest.py \
  tests/test_skillcenter_corpus.py -q
```

These tests validate reused cellular/ingestion boundaries, not the proposed
legal-corpus integration. The helper-lock diagnostic is a confirmed planning
finding, not a fix. Sibling historical test counts above were not rerun here.
