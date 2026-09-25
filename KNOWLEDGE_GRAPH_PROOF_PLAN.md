# Knowledge graphs to verified Lean proofs: implementation plan

Reviewed and re-audited 2026-09-24. This is the architecture/planning deliverable;
it does **not** declare the entire proposed system implemented or benchmarked.
The operational first slice is documented in [KNOWLEDGE_GRAPHRAG.md](KNOWLEDGE_GRAPHRAG.md).

## 1. Objective and non-negotiable boundaries

Ingest Lean libraries and external graph data efficiently, inject relevant graph
context into proof search, contrast relationships to propose theorems and
refactorings, reconstruct proofs in Lean, and learn from verified outcomes.
Optimize proof tokens and heartbeats without confusing retrieval or learned
similarity with correctness.

- DuckDB is the database backend. No SQLite fallback or new SQLite stores.
  Parquet and content-addressed files are interchange/storage artifacts, not a
  second database authority. Preserve all existing caches and historical runs.
- Freeze the statement, local hypotheses, allowed imports, axiom policy and
  toolchain environment for an Arena refactor. Retrieved claims cannot enlarge
  its assumptions. Hashes bind artifacts; they do not attest provenance or truth.
- External claims produce explicitly conditional theorems, or theorems about a
  precisely encoded finite dataset. Neither proves the dataset describes reality.
- Keep source fidelity separate from logical validity: a kernel-checked proof
  of a mistranslated statement is not successful autoformalization.
- Unknown, rejected, timed-out and unmeasured are distinct states. No missing
  observation becomes a successful proof, zero heartbeat count, or training label.

## 2. Upstream architecture review and reuse decisions

Inspected checkout: `/home/barberb/ipfs_datasets_py`, HEAD
`7f0d38572f92f5fc0cba7a5ddd4bef28523876f3`. The reviewed upstream files had no local
changes at this audit. Paths below are relative to that checkout.

| Inspected implementation | Evidence and reuse decision |
| --- | --- |
| `docs/architecture/knowledge/GRAPHRAG.md` | Separates graph storage, retrieval, processors, optimizer advice and formal authority. Preserve these boundaries rather than treating all GraphRAG classes as one implementation. |
| `logic/intent_ir/graphrag/skillcenter_corpus.py` under `ipfs_datasets_py/` | Canonical entry/content/container identities; Parquet batch iteration. Reuse the identity/join model. Its complete CID map is in Python memory: replace that part with DuckDB lookup/shards. |
| `.../skillcenter_corpus_bm25.py` | Real disk-backed contentless FTS5/BM25 and integrity manifests. Reuse sparse postings, metadata joins and artifact validation, but implement them in DuckDB; do not import its SQLite backend. |
| `.../skillcenter_bm25.py` | Persisted Parquet postings loaded into in-memory search structures. Useful reference/control, not our large-corpus serving backend. |
| `.../skillcenter_cid_graph.py` | Checkpointed/resumable batches, provenance edges and bounded `BM25_NEIGHBOR_OF` edges explicitly labeled context-only. Port these lifecycle contracts; similarity edges remain non-inferential. |
| `.../semantic_projector.py`, `.../retrieval.py` | Distinguish semantic assertions, grounding and similarity; exact graph snapshots and trusted partition assignments. Schema-valid semantic assertions still require Lean grounding/proofs. |
| `.../skillcenter_cid_vectors.py` | Materializes all vectors and builds exact `IndexFlatIP`. Keep as a small-corpus control; benchmark sharded/approximate alternatives before larger use. |
| `.../skillcenter_graphrag.py::_nearest_skill_neighbors` | Dense fallback computes `vectors @ vectors.T`. Do not bring this quadratic build path into the scalable pipeline. |
| `ipfs_datasets_py/embeddings/sparse_embedding_engine.py` | `MockSparseEmbeddingService`, including its named SPLADE mode, generates mock vectors. Exclude it from quality/performance evidence. |
| `scripts/ops/intent_ir/audit_skillcenter_cid_indexes.py` | Reuse the idea of cross-index key/coverage audits, using bounded DuckDB joins rather than whole-corpus Python sets. |

The prefix `.../` above denotes `ipfs_datasets_py/logic/intent_ir/graphrag/`.
Preserve upstream attribution/revision and check licenses when adapting code.
No upstream SkillCenter code or datasets were modified for this plan.

The follow-up audit confirmed the same HEAD and no local changes in the reviewed
paths. Concrete source anchors: corpus CID-map materialization at
`skillcenter_corpus.py:160`, in-memory posting loads at `skillcenter_bm25.py:347`,
contentless FTS5 at `skillcenter_corpus_bm25.py:607`, SQLite staging/resume at
`skillcenter_cid_graph.py:361`, exact FAISS indexing at
`skillcenter_cid_vectors.py:397`, and the all-pairs matrix at
`skillcenter_graphrag.py:1308`. These are reuse **designs**, not an endorsement
of copying their storage engines. The mock sparse engine uses generated random
vectors; its advertised model names are not evidence of real SPLADE inference.
Here, "SkillCenter" means the subsystem in this checkout, not a separately
verified deployment. Its retrieval constructor materializes node/edge maps and
its cross-index auditor compares complete Python CID sets. Reuse their snapshot,
partition and coverage contracts, not those whole-corpus memory layouts.

## 3. Three linked representations and explicit interfaces

```text
Lean sources / graph exports / documents
        -> adapters -> immutable corpus and provenance
             |             |                |
       evidence graph   typed Expr DAG   proof hypergraph
             +-------------+----------------+
                    scoped sparse retrieval
                          -> context packet
                          -> relational proposals / proof plans
                          -> Lean reconstruction and checking
                          -> token, heartbeat and full-cost evaluation
                          -> verified teachers + separate failure feedback
```

The evidence graph stores assertions and their sources. The Expr DAG stores
Lean terms/types with binders, universe parameters and structural sharing.
InfoTree observations connect source syntax to local elaboration/proof states;
they are not a replacement for Expr or a proof certificate.

The proof hypergraph stores inference applications: several premises may be
required simultaneously. An ordinary graph path is not sufficient evidence.
Inference records contain ordered premise IDs, conclusion, rule/theorem ID,
instantiation/substitution, side obligations, local context, environment and
verification reference. Keep equality, equivalence, implication, type membership,
dependency and lexical similarity as different relation kinds.

Proposed DuckDB entities: `sources`, `claims`, `expr_nodes`, `declarations`,
`inference_steps`, `step_inputs`, `dependencies`, `partitions`, `postings`,
`term_statistics`, `snapshots`, `verification_receipts`, `training_pairs`.
Local hypotheses belong to scoped contexts, never global facts. A rule for
`Nat` does not apply to `Int` merely because printed operators coincide.

Inject `CorpusReader`, `GraphStore`, `PremiseRetriever`, `ContrastPlanner`,
`ProofRenderer`, `LeanVerifier` and `EvaluationRecorder`. Default calls must not
start providers, training, network requests or watchers. Test doubles must retain
fixture status and cannot manufacture native verification evidence.

## 4. Ingestion, identity, indexing and storage efficiency

1. Accept versioned JSON-LD/typed edge exports and Parquet batches from
   SkillCenter. Require entity namespaces, relation schemas, exact source IDs,
   extraction versions and provenance. Quarantine ambiguous identity mappings.
2. Extract declarations/dependencies natively from pinned Lean environments.
   Keep raw text, exact Expr/type identity and normalized retrieval features
   separately. Do not assume equal hashes of lossy features mean equal terms.
3. Use source-byte hashes and dependency Merkle roots for incremental invalidation.
   mtime/size are cheap hints only. Source, import, toolchain, extractor, tokenizer,
   partition-policy and model changes invalidate the relevant downstream artifacts.
4. Build sparse postings before optional embeddings. Preserve case, qualified
   names, Unicode operators, type heads, binder roles and operator direction.
   Fit statistics only on admissible library/training partitions and their
   allowed dependency closure; filtering heldouts after fitting is too late.
5. Bulk-insert bounded Arrow/Parquet batches into DuckDB where profiling shows
   Python `executemany` overhead. Store directed adjacency in both traversal
   directions with explicit relation filters, not all-pairs similarity matrices.
6. Shard by environment/module and size. Publish new immutable snapshots from
   checkpointed staging, with manifest-bound resume and coverage checks. Use
   tombstones for changed declarations; invalidate dependent proofs/retrieval
   results. Refuse partial or identity-mismatched publication.
7. Avoid a full graph copy or full scope/closure scan per query. Add environment
   scope indexes, reusable exclusion closures and snapshot-bound query caches.
   Cache keys include goal/local context, exclusions, budgets and backend versions.
8. Add dense or learned sparse retrieval only after a measured lexical failure
   analysis. Benchmark indexing cost, recall and query latency; never select a
   backend because a mock or model name advertises a capability.

DuckDB memory settings are not process-RSS enforcement. Use process/container
limits and an aggregate storage reservation covering databases, WAL/checkpoints,
temporary joins/sorts, embeddings, prepared Lean environments and receipts.
Honor the 50,000,000,000-byte cap: retain caches and stop before exhausting it.
No automatic cache eviction or silent cap increases. Million/trillion-scale
claims require measured scaling and capacity estimates, not these small controls.

### Incremental build and serving contract

Keep a single writer per staging shard and immutable, read-only serving shards.
Each checkpoint binds source revision, last committed batch, row/edge counts,
schema/extractor versions, input hash and reserved disk allowance. Publish the
manifest only after recomputing identities and checking both directions of the
CID/declaration joins; a changed input starts a new retained artifact, not an
in-place repair of a published snapshot. Readers use a pinned manifest, never
whatever shard happens to be newest mid-query.

The current DuckDB index already implements weighted lexical BM25 scoring with
typed-head hints. The next scalability work is bulk ingestion, persisted scope
indexes and bounded dependency-closure lookup—not replacing a mock with a second
mock. Measure physical query plans as well as returned row counts: a top-k output
limit alone does not bound the work of a join, sort or recursive traversal.
Track postings per document, edges visited per query, scanned rows, peak RSS and
transient disk. Optional learned sparse vectors add model/tokenizer identities,
nonzero-count limits, training-split provenance and reindex costs.

Advance through representative 10k/100k/1M input stages only when projected peak
disk (existing retained data + staging + serving + spill + receipts + safety
reserve) fits the unchanged allowance. Compare against the same frozen lexical
baseline and a full rebuild for a 1% update. Require exact coverage, no heldout
statistics leakage, successful interruption/resume, and preregistered latency,
memory and recall tolerances. A storage stop is an incomplete scale stage, not
permission to delete caches. The current 64/512/2048 synthetic probe establishes
none of the larger-stage capacity claims. DuckDB's buffer-memory limit is not
a process-memory cap; separately constrain the process and spill reservation.
See [DuckDB's memory guidance](https://duckdb.org/docs/current/guides/performance/oom)
and [query-plan guidance](https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads).

### Immediate performance work, based on the current implementation

- A first bulk-transport slice is implemented: both builders retain their
  64-record validation batches but default to typed parameterized column lists
  inserted in one SQL call per table/batch. Explicit `executemany` mode remains
  the reference control. Multi-batch parity and late-failure tests protect
  canonical identities, constraints and coverage; the
  [comparison runner](KNOWLEDGE_GRAPHRAG.md#synthetic-ingestion-probe) generates
  matched synthetic measurements. Representative real-export profiling,
  Arrow/Parquet comparisons and peak RSS/disk measurements remain open.
- Each `KnowledgeIndex.search` rebuilds availability, exclusion, origin and query
  tables and computes recursive dependency exclusions. Separate snapshot-scoped
  availability/adjacency from request-scoped exclusions. Reuse only closures
  keyed by the exact environment, snapshot, scope, target, exclusions and policy;
  changes must invalidate them. Unknown or incomplete closure means abstention,
  never permission to admit a potentially excluded premise.
- Profile these changes on representative real exports before adding embeddings.
  Compare query plans, rows scanned, cold/warm latency, RSS, transient disk and
  exact eligible-hit parity. Treat persisted scope tables and prepared queries as
  candidates to measure, not a promise that another SQL index solves the problem.

## 5. Relational contrasts and theorem construction

| Contrast | Generated obligation | Required guard/certificate |
| --- | --- | --- |
| Matching intermediate term | Compose `R a b` and `R b c` | A proved transitivity theorem for this exact relation/type; not every relation is transitive. |
| Opposite implication directions | Construct `P ↔ Q` | Both `P → Q` and `Q → P`; one direction never supplies the converse. |
| Symmetric-looking edges | Invert/reorient a relation | Explicit symmetry/inverse lemma; distinguish symmetry from converse. |
| Equal subexpressions | Rewrite/congruence/CSE | Type-correct equality and scoped substitution; capture-avoiding binders. |
| Similar proof subgraphs | Generalize/factor a helper lemma | Check generalized statement, all instantiations and total helper cost. |
| Transformation versus property | Discover an invariant | Initialization, preservation and use/exit obligations; examples alone are insufficient. |
| Redundant Boolean structure | K-map/BDD/Boolean reduction | Replay a Lean equivalence certificate, including explicit classical assumptions if needed. |
| Conflicting claims | Contradiction/counterexample task | Keep source/assumption namespaces separate. Missing edges are unknown, not negated facts. |

Apply this search order: known lemma application; directed implications;
congruence and explicit rewrites; minimized simplification sets; domain solvers;
helper/invariant discovery; then bounded equality saturation. Rule applications
must retain substitutions, side conditions and proof explanations. Reconstruction
may reject solver output. Start with monomorphic fragments before dependent
rewriting; never erase universes/binders to force a match.

An external claim without a Lean proof may enter a clearly labeled conditional
theorem's assumptions, not an Arena refactor. Decidable finite-data claims must
name their exact encoded dataset and checked certificate. Reject source/graph
prompt injection as data; never execute graph-supplied Python, shell or SQL.

The renderer emits a typed proof plan with stable premise IDs and explicit
obligations, then Lean syntax. Python schema validation is only an intake check.
All required pins recheck the original statement and reconstructed term in the
trusted environment, with a fixed axiom policy and target-free prefix.

### Worked contrast: a path versus an opposite-direction edge

Suppose the admissible, typed graph contains `P → Q`, `Q → R` and `R → P`.
The planner first composes the first two edges into `P → R`, then contrasts that
result with `R → P` to propose `P ↔ R`. A reconstruction template is:

```lean
theorem contrast (P Q R : Prop)
    (hPQ : P → Q) (hQR : Q → R) (hRP : R → P) : P ↔ R :=
  ⟨fun hp => hQR (hPQ hp), hRP⟩
```

For a refactor, these hypotheses must already be in the unchanged theorem's
context, or be discharged by permitted library proofs: the graph cannot add
them. For unverified external assertions, this is only a conditional theorem.
For grounded declarations, retain each instantiated type, source evidence ID,
edge direction and environment; verify the final reconstructed proof on all pins.
Deleting `R → P` must leave the reverse direction unsolved. Replacing it with a
similarity edge must not help. Replacing `Q` on one edge by a different typed
entity must break composition. These are mandatory negative controls.

Each proposal returns its conclusion, ordered premises, rule applications,
unresolved obligations and status. Successful search is still a draft. Only a
fresh native receipt can move it to verified; source-faithfulness review is an
additional gate for natural-language inputs. More expressive relations follow
the same contract rather than interpreting arbitrary graph paths as proofs.

## 6. Context injection and empirical prompt engineering

Filter by environment, declaration availability and protected-family closure
before ranking. Retrieve sparse seeds, traverse selected relations under
node/edge/hop budgets, check type applicability, and assemble a compact packet:
exact goal, locals, premise types, justified edges, remaining obligations and
output contract. Preserve IDs/provenance without dumping the entire graph.

Compare no retrieval, lexical retrieval, typed graph retrieval, then optional
learned reranking. Vary one factor at a time: premise count, token budget,
ordering, local proof-state detail, failed-obligation feedback, and plan versus
tactic-text output. Use equal request/output/search budgets and randomized blocks.
Log exact prompts/responses, truncation, parse errors, unsupported context,
native rejection, useful premise recall and final verified results separately.

Freeze the selected configuration before fresh confirmation. Repeated tuning of
the same canaries makes them development data. A formatting improvement or high
retrieval similarity is not a proof or refactoring improvement.

## 7. Autoencoder, JeV and NCA learning

Keep verified compression teachers separate from failure/repair observations.
Teacher pairs bind original and candidate source, theorem/type, input graph
snapshot, rule path, native receipts and measured costs. No held-out proofs,
renamed wrappers or derivatives may leak into the training graph or embeddings.

Use separate reconstruction CE and compression/rewrite CE objectives; preserve
cosine/contrastive monitoring rather than optimizing length alone. Add graph
edge/type applicability and verified-cost ranking losses only with independent
labels. Test for embedding collapse. Hard negatives include wrong types,
reversed implications, missing side conditions and unavailable premises; a
premise not used in one proof is not automatically false or unusable.

Extend existing `graph_policy.candidate_loss` and
`jev_surrogate.expected_utility_gradient`: fuzzy utilities can guide a lossy
proposal policy, but neither JeV nor the Lean call is magically differentiable.
Freeze scorer/rubric per update; use the finite-choice expected-utility objective
or a justified sampled estimator. Calibrate critics on held-out development data
and retain abstentions/uncertainty. NCA/message passing may prioritize graph
regions; it cannot propagate proof authority.

Tune learning rate, clipping, loss weights and batch size on development splits.
Compare fixed-rule, frozen-encoder, CE-only, CE+cosine, and JeV/NCA ablations.
Keep changes only when independently checked proof/cost outcomes improve without
violating frozen validity, reconstruction and canary gates. Do not train directly
on failure text as if it were a successful compression target.

## 8. Honest evaluation, feedback and migration

Maintain a Pareto frontier over source tokens, measured Arena heartbeats and
proof-term size. Separately report wall time, search/model tokens, native calls,
ingestion and query costs. Explicit reusable proofs may cost less than repeating
an expensive short tactic. New helper declarations must not hide uncounted cost.
The same tokenizer and pinned heartbeat method must be used for both arms and
historical comparisons; current command-elaboration heartbeats are not an
independent kernel-only timing metric. Missing results remain visible.

Run all 15 Arena cases for continuity and fresh family-separated canaries for
generalization. Keep the judge, axiom policy and sealed holdouts outside the
self-improving system's edit authority. The outer loop may propose tactics,
prompts and Python changes; isolated tests and frozen development gates admit
them. Failed candidates become diagnostics, not positive rewards.

Generate JSON receipts and concise reports programmatically from actual events.
Bind every measurement to source/configuration/environment and graph snapshots.
Use fresh native checks for final promotion; cached historical success is labeled
reuse, never a new measurement.

Older watcher/prompt-lab ledgers still use SQLite. A separate migration must copy
into new DuckDB artifacts, validate row keys/counts, reservations, terminal states
and receipt hashes, test crash/resume behavior, then explicitly cut over. Retain
the original ledgers read-only; never reset consumed model/compiler budgets or
restart a watcher just to complete storage migration.

### Separate library reuse from proof discovery

The 2026-09-24 canary audit found that the reported **66→1** case is a direct
application of the pre-existing `and_or_left` theorem. The fixture supplied that
exact declaration name and its instantiation; the retrieval query also contained
the name. The original constructor reference counted as **57**, while **66** was
the generated compact-local baseline. Eight native observations verified the
one-token candidate with unchanged type and empty axiom sets. This demonstrates
valid library reuse and renderer behavior, not independent retrieval, learned
compression, semantic novelty or generalization. See the retained
[case receipt](papers/completion/lean_refactor_arena/evidence/knowledge-relation-canaries-2026-09-24/and-or-distrib.json),
[fixture mapping](jevops/knowledge_canaries.py) and
[name-supplied runner](tests/test_knowledge_canaries.py).

Split subsequent evaluation into three explicitly labeled tracks:

| Track | Permitted inputs and baseline | Claim it can support |
| --- | --- | --- |
| Supplied-mapping smoke | Explicit answer mappings; typed witnesses; renderer variants | Bridge correctness and local rendering costs only; no discovery/learning reward. |
| Library-reuse refactoring | Frozen eligible library; goal/locals and real source graph, without supplied solution names or reference-proof text; exact-type lemma lookup and lexical retrieval baselines | Whether the system finds/reuses available proofs better than those baselines. |
| Composition/generalization | Separately frozen task families and a restricted premise universe; full-goal aliases/wrappers and task-derived proof artifacts excluded before indexing | Bounded evidence of composing permitted facts, not merely re-emitting an available complete answer. |

For the third track, check binder-aware elaborated goal/type matching and
admissible instantiation, not just theorem names or text hashes. Record detected
direct answers, aliases and dependent wrappers; reject direct-answer use in the
candidate's dependency audit too. Typeclass search and implicit elaboration must
not silently reintroduce an excluded answer. Removing a declaration from a
retrieval list alone does not remove it from Lean's environment. Freeze a
restricted environment or enforce the dependency policy on the checked term.
Arbitrary logical equivalence is not generally decidable: label the detector's
supported fragment, checked universe and unknown/timeouts. Unknowns are not
certificates of novelty. This detector and track separation are **planned**, not
features of the current four-atom alpha-group guard.

All arms in a retrieval/graph ablation get the same admissible information,
environment and total budget. Include a no-graph arm supplied the *same retrieved
premise set* to isolate graph structure from additional information. Keep the
original reference, generated baseline and strongest preregistered lookup
baseline separate; never inflate a denominator with a worse generated proof.
Report lexical proof-body tokens, source bytes, elaborated-term/DAG size and
dependency cost under explicit conventions. A one-token library reference does
not encode its proof without the shared library. New helper bodies and checking
costs must be charged; existing-library cost is reported separately and shared
consistently across arms. Elaboration heartbeats exclude ingestion, retrieval,
library builds and other work, which need separate end-to-end measurements.

The six exposed synthetic cases remain immutable regression/smoke evidence.
Renaming them cannot make fresh holdouts, and a valid one-token result cannot
be relabeled as autoencoder learning. Freeze development choices, track labels,
exclusions, tokenizer and scorer before evaluating new families. Admit training
teachers only from independent training partitions after the section-7 gates;
report reuse, composition and reconstruction losses separately.

## 9. Delivery order and acceptance evidence

| Milestone | Deliverable and acceptance gate | Current status |
| --- | --- | --- |
| A: contracts/baseline | Fixed schemas, scope/trust rules, DuckDB-only policy, upstream review and benchmark protocol | Plan specified here; opt-in index/plan contracts exist. |
| B: corpus bridge | SkillCenter export + Lean declaration adapters; exact coverage and provenance; duplicate/ambiguity/mutation tests | Canonical SkillCenter Parquet-to-DuckDB evidence adapter and explicit propositional edge-to-declaration mappings exist. General grounding and whole-library extraction remain. |
| C: scalable index | Batched typed postings, scope index, incremental shards, resume/tombstones, budget accounting | Bounded lexical/head DuckDB retrieval, typed-signature persistence and columnar batch insertion with an explicit reference mode exist. Incremental serving, reusable whole-library scope and aggregate reservation remain. |
| D: relational compiler | Proof-bearing relation schema, hypothesis generation, side-condition resolution, Lean replay | Bounded mapped implication/equivalence composition emits typed obligations and checks the unchanged candidate on all pins. Arbitrary typed/dependent graph compilation and source-fidelity validation remain. |
| E: context experiments | Matched-budget graph/no-graph arms, frozen prompt selection, native outcomes | Supplied-mapping smoke and a bounded goal-only library-lookup control exist, including direct scan/BM25 and optional one-lemma application. Independent full-corpus selection, same-premise graph ablation and direct-answer-filtered composition remain; exposed bounded controls cannot substitute for them. |
| F: training | Verified pair export, protected partitions, CE/cosine controls, JeV/NCA ablations and learning-rate sweep | Existing learners are reusable; graph-derived training path is not enabled. |
| G: deployment gates | All-15 report, new canaries, unchanged judge, no cost regressions hidden by aggregation | Not run for the new graph pipeline; no high-score or promotion claim. |
| H: scale and migration | 10k/100k/1M probes as storage permits; 1% update tests; storage reservation; ledger migration audit | Small synthetic DuckDB probe only; no large-scale or completed-migration claim. |

Dependency order: A -> B -> C/D -> E -> F -> G, with H's performance probes
informing C before deployment. No production activation until storage and proof
gates pass. Milestones are implementation acceptance requirements, not assertions
that their tests have already been run merely because this plan is complete.

Measure build rows/s, peak process RSS, peak disk including staging, bytes/row,
changed-shard rebuild fraction, cold/warm query distributions, candidate recall,
timeouts, proof validity and end-to-end cost. Fail scale progression on unbounded
growth, incomplete coverage or budget overruns. Scale-gate thresholds should be
registered from the real baseline before comparing alternative backends.

## 10. Evidence and research anchors

Current executable controls: [index tests](tests/test_knowledge_index.py),
[proof-plan tests](tests/test_knowledge_proofs.py), and
[synthetic probe](jevops/knowledge_probe.py). The probe writes receipts from real
DuckDB calls; synthetic names/relationships are not mathematical benchmark data.
Its command, limitations and current receipt link are in
[KNOWLEDGE_GRAPHRAG.md](KNOWLEDGE_GRAPHRAG.md#synthetic-ingestion-probe).

Existing integration points: [premise contracts](jevops/premise_search.py),
[native exports](jevops/arena_premises.py), [Expr DAG](jevops/expr_dag.py),
[graph policy](jevops/graph_policy.py), [JeV adapter](jevops/jev_surrogate.py),
[Arena verifier](jevops/arena_lean.py), and
[prompt experiments](LEANSTRAL_PROMPT_LAB.md).
Typed telescope/head signatures now survive the DuckDB nomination bridge.
The [SkillCenter adapter](jevops/skillcenter_corpus.py) imports canonical exports
as evidence, not as Lean declarations. Its [tests](tests/test_skillcenter_corpus.py)
check upstream writer conformance, CID/coverage/provenance and rejection paths.
The [relation bridge](jevops/knowledge_relations.py) grounds an explicit
propositional fragment in scoped declarations. [Bridge controls](tests/test_knowledge_relations.py)
test stale/excluded mappings, statement preservation, actual native obligations
and wrong-type rejection. They are not a full dataset autoformalization result.

Primary research grounding:

- [Lean elaboration, InfoTree and kernel checking](https://lean-lang.org/doc/reference/latest/Elaboration-and-Compilation/): distinct representations and trust boundaries.
- [LeanDojo/ReProver](https://arxiv.org/abs/2306.15626): accessible-premise retrieval and generalization-oriented evaluation.
- [SPLADE](https://arxiv.org/abs/2107.05720): learned sparse expansion as a future measured alternative, not the upstream mock service.
- [Lean equality saturation](https://www.steuwer.info/files/publications/2026/POPL-Lean-Egg.pdf): reconstruct explanations into Lean proofs; engine discovery is not proof authority.
- [Lean expressions in e-graphs](https://arxiv.org/abs/2405.10188): binder/type/definitional-equality handling is a substantive integration problem; Lean checking remains the authority even when the search procedure is unsound.
- [DuckDB Python API](https://duckdb.org/docs/current/clients/python/reference/): explicit connections, read-only artifacts and interruption.

## Planning completion checklist

- KG ingestion and injection: sections 3, 4 and 6.
- Theorem construction by contrasting relationships: sections 3 and 5.
- ipfs_datasets_py GraphRAG and sparse architecture review: section 2.
- SkillCenter-specific reuse and scaling limits: sections 2 and 4.
- Efficiency measurement and progression: sections 4, 9 and executable probe.
- DuckDB preference, preservation and migration: sections 1, 4 and 8.
- Training, proof authority and reward-hacking controls: sections 1, 7 and 8.
- Concrete delivery sequence, integration seams and acceptance criteria: section 9.

### Planning acceptance audit

| Requested requirement | Authoritative review/evidence and plan coverage |
| --- | --- |
| Inject a knowledge graph | Sections 3/6 specify evidence, expression and inference representations, scoped retrieval interfaces, context packets and controlled experiments. Current DuckDB nomination and relation modules demonstrate only a bounded first slice. |
| Construct proofs by contrasting relationships | Section 5 gives typed composition, opposite-direction equivalence, equality, invariants and contradiction obligations plus a worked Lean template and negative controls. Existing relation tests distinguish drafts from native receipts. General dependent graph compilation remains an implementation milestone. |
| Review ipfs_datasets_py GraphRAG and sparse indexing | Section 2 records the checked revision, architecture owners and concrete implementation anchors. Section 4 gives DuckDB BM25, bulk/sharded ingestion, scope filtering and optional real learned-sparse alternatives; mock vectors are excluded as evidence. |
| Review SkillCenter GraphRAG | Corpus, Parquet/postings, CID graph, vector index, dense neighbors, semantic projector, retrieval and cross-index auditor were inspected. Source identity, context-only similarity and partition isolation are retained; SQLite and all-pairs paths are not ported. |
| Plan efficient ingestion with verification | Sections 4/9 specify bounded batches, transactional publication/resume, incremental invalidation, scope caches, capacity stages and measurements. The retained probe covers 64/512/2048 synthetic rows only; it does not establish production throughput. |
| Respect DuckDB/storage and avoid reward hacking | Sections 1/8 specify DuckDB-only new storage, audited migration, retained caches and the fixed cap. Supplied-answer smoke results are separated from retrieval/composition/learning claims, with missing or unknown evidence kept explicit. |

This audit establishes completion of the requested **plan and upstream review**,
not completion of milestones B–H, full-corpus ingestion, training or Arena success.
The section-8 evaluation separation now has a first
[goal-only library-reuse control](KNOWLEDGE_LIBRARY_REUSE.md): a frozen bounded
DuckDB pool, direct lemma scan and BM25 ranking, with fresh paired native
confirmation. An opt-in mode now adds one-lemma application with argument
inference and local-hypothesis discharge after the bare-constant sweep. A separate
materialization stage now captures selected application tactics, replays printed
terms and freshly checks/measures the compact whole theorem on every pin. Saved
lookup successes remain nominations rather than fresh verification. This
deliberately bounded baseline does not establish unbiased corpus selection,
arbitrary argument-term or equivalence detection, or blind generalization.
An opt-in incumbent-aware bridge now routes compact nominations into the existing
fresh screening/confirmation selector. It rejects token ties without claiming
new verification, and requires strict token and heartbeat improvements against
both the original and current incumbent before a local recommendation. The
[admission regression report](papers/completion/lean_refactor_arena/evidence/knowledge-compact-selection-2026-09-24/summary.md)
also demonstrates native rejection of a deliberately rehashed false success
receipt. This does not activate the watcher, training or source promotion, and
the exposed compact controls still do not beat their original references.
Those gates and section-4 real-corpus ingestion profiling remain open. Do not
promote the supplied-answer smoke score as a discovery result.

Earlier retained audit validation: [108 tests passed, 5 opt-in native tests skipped](papers/completion/lean_refactor_arena/evidence/knowledge-plan-audit-2026-09-24/adapter-regression.xml),
including the real upstream Parquet-writer-to-DuckDB interoperability test with
SQLite connections forbidden. The worked Lean template was separately checked
on both installed pins: the positive theorem compiled without axioms, and
wrong-direction and mismatched-intermediate variants were rejected on both
([six-check receipt](papers/completion/lean_refactor_arena/evidence/knowledge-plan-audit-2026-09-24/lean-example.json)).
These checks validate the example and bounded adapter contracts, not full-scale
ingestion or a performance advantage. No training, watcher restart, downloads,
cache eviction or increased storage allowance were needed.

The follow-up source audit reran `test_knowledge_index.py`,
`test_knowledge_proofs.py`, `test_skillcenter_corpus.py` and
`test_knowledge_relations.py` with test seals disabled: **123 passed, 13 skipped**
([programmatically generated JUnit receipt](/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/knowledge-goal-audit-20260924-Tvbr8W/regression.xml)).
The upstream writer interoperability check passed with SQLite connections
forbidden. This uses a fixture reader and establishes wire-format conformance,
not full SkillCenter corpus ingestion. A native-enabled attempt did not start
because another process held the shared build lock; the completed run explicitly
disabled native tests. All 13 skips are native controls, and the earlier Lean
receipt above remains historical evidence, not fresh verification from this run.
No model calls, graph-derived training, watcher changes or cache removal were
performed in that audit. The later bulk-transport slice is documented in section
4; reusable scope/closure work remains planned.

The [frozen relation experiment](KNOWLEDGE_RELATION_TRIALS.md) now implements
matched search ceilings and token/heartbeat accounting against local-only
search. It compares mapped-premise injection, not graph structure in isolation.
An opt-in structural-rendering ablation now measures compact local terms,
typed inlining and implicit-argument inference, gated by the original fully
typed witness. Next milestones include real-corpus coverage, protected
generalization controls and verified-pair export before enabling graph-derived
training. The three-case native rendering pilot improved over the old scaffolded
outputs; only one case also reduced tokens versus compact local search. This
does not establish generalization or an Arena leaderboard improvement. The bounded
propositional bridge is not a general KG theorem prover or, by itself, evidence
of improved compression.

An opt-in [six-case protected smoke harness](KNOWLEDGE_RELATION_CANARIES.md)
adds frozen structural families, alpha/context identity checks, a persistent
DuckDB exposure ledger and an explicit future training-admission guard. It
keeps failures and abstentions in the denominator, does not resample based on
results, and leaves training/promotion disabled. This protects the harness's
own evaluation boundary; it does not complete real-corpus decontamination or
enable the milestone-F training path.
