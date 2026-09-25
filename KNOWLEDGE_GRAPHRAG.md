# DuckDB knowledge retrieval and local proof plans

See [the comprehensive architecture and delivery plan](KNOWLEDGE_GRAPH_PROOF_PLAN.md)
for the full KG-to-proof pipeline, upstream review and remaining acceptance gates.

## Storage policy

Use DuckDB for new database-backed storage and querying in this work. Do not
introduce SQLite backends or silent SQLite fallbacks. Existing databases and
upstream SkillCenter assets are not migrated or deleted by this implementation.

Install the optional `jevops[knowledge]` dependency for the index. The current
implementation was tested with DuckDB 1.5.5. It uses ordinary DuckDB tables and
SQL BM25, not the FTS extension: no extension installation, model download,
network access, or mock embeddings. External access and automatic extension
loading/installation are disabled in each connection.

Both builders now default to bounded columnar inserts: one parameterized
`INSERT ... SELECT unnest(...)` per table/batch, using explicit SQL list types.
This follows DuckDB's [side-by-side unnest semantics](https://duckdb.org/docs/current/sql/query_syntax/unnest).
Row widths are checked before transposition, including all-null signature
columns. No Arrow dependency is added to `jevops[knowledge]`; the SkillCenter
Parquet reader still requires `jevops[knowledge-corpus]`.

Use `ingestion_mode="executemany"` in either builder (or `--ingestion-mode
executemany` in the corpus CLI) for the explicit reference transport. There is
no automatic fallback. Semantic snapshot IDs, validation, budgets, constraints
and atomic no-overwrite publication are unchanged; physical DuckDB file hashes
can differ and are checked independently. This changes insertion only, not
query-time exclusion/closure work or proof authority.

## Implemented boundary

- `jevops.knowledge_index`: streamed, batched premise ingestion; immutable
  DuckDB artifact publication; exact case/Unicode lexical postings; BM25;
  target, alias, family, availability and transitive dependency exclusions;
  typed telescope/head signature persistence and bounded head-based retrieval;
  a nomination bridge that preserves signatures for the Arena provider API.
- `jevops.skillcenter_corpus`: canonical SkillCenter Parquet export ingestion,
  complete CID-index join verification, and provenance-preserving DuckDB evidence
  lookup. Raw source prose is never automatically converted into Lean premises.
- `jevops.knowledge_proofs`: local propositional proof hypergraphs for
  implication application, conjunction projections/introduction, and both
  directions of equivalence. Plans bind the exact original source, statement,
  and caller-supplied environment. Deterministic rendering produces a Lean
  proof candidate, never new assumptions or declarations.
- `evaluate_plan`: explicitly injected `ArenaEvaluator` checks the candidate
  on the context's pins. Fixture observations remain fixtures. No automatic
  training, promotion, watcher changes, or official score claims.
- `jevops.knowledge_relations`: explicit graph-to-declaration mappings for a
  bounded propositional fragment, typed Lean obligations, constructive relation
  composition and all-pin replay. Graph/provenance validity alone is not proof.

These are opt-in building blocks, not a completed KG-to-dependent-Lean
compiler. The local planner does **not** promote retrieved claims into local
hypotheses. Arbitrary relation graphs, dependent-type reconstruction, open-state
serialization, incremental shard updates and live outer-loop integration remain
future work. First-found proof plans are not guaranteed shortest or cheaper.

## Index example

```python
from pathlib import Path
from jevops.knowledge_index import build_index, KnowledgeIndex

# premises and scope come from a trusted environment-bound inventory producer.
# corpus_digest identifies that exact input inventory; a hash is not attestation.
artifact = build_index(
    Path("premises.duckdb"), premises,
    environment_sha256=scope.environment_sha256,
    source_sha256=corpus_digest,
    signatures=typed_inventory.signatures.values(),  # optional native export
)
with KnowledgeIndex(Path(artifact.path), expected_sha256=artifact.file_sha256) as index:
    nominations, retrieval = index.provider_index(
        goal, target=target_name, scope=scope, top_k=8,
        conclusion=goal_head,  # optional ExprHead; not a unification certificate
    )
    # nominations can be passed to existing arena_providers.propose_batch.
    # Keep retrieval with the proposal receipts for snapshot/scope provenance.
```

Only `library` and `train` records can enter index statistics. The inventory
producer must exclude protected families and their derivatives **before build**;
query-time filters cannot undo statistical contamination. Unknown/excluded names
still propagate to dependent records at query time. Provenance and scope are
trusted caller inputs, not facts the retriever can independently authenticate.

BM25 uses a versioned bag containing type features plus declaration-name
features weighted twice, with k1=1.2 and b=0.75. It is lexical relevance, not
type checking, semantic similarity, or a correctness probability. Optional raw
conclusion-head postings add otherwise lexically invisible nominees. Matching
heads receive priority; when possible, one fallback slot remains for generic or
mismatching heads because raw heads do not decide definitional equality. This
does not perform unification. Graph features and learned rerankers remain future
work. Complete binder kinds/heads and conclusions survive the provider bridge.

New premise artifacts use schema v2 and bind signatures into entry and snapshot
identities. The reader still accepts v1 artifacts, treating absent signatures as
unknown. It does not rewrite old artifacts or reinterpret old probe receipts.

Record identities are `sha256:<hex>` URIs, not IPFS CIDs. The logical snapshot
digest is independent of ingestion order and binds environment, source manifest,
feature/scoring version, engine version and canonical records. The separate file
digest verifies physical DuckDB bytes; physical bytes need not be reproducible.

## Limits and lifecycle

The builder refuses existing output paths, batches 64 records, caps input bytes
and record count, checkpoints and closes the database, hashes it, then publishes
without overwriting another artifact. Scratch is removed on failure; existing
artifacts and all environment caches remain untouched. `max_bytes` caps input
and final artifact size, **not peak transient disk usage**. Production jobs must
reserve that transient headroom within the outer runner's 50 GB storage budget.

Readers rehash on open and hold a read-only connection. Do not mutate or swap an
artifact during a reader's lifetime. Handles are single-owner, not concurrent
query services. Each query uses temporary scope tables, bounded candidate and
context sizes, and a deadline with DuckDB interruption. Connections use one
thread, a 128 MB engine memory limit and disabled spill. This is not a hard
process-RSS or hard real-time isolation guarantee. A timeout or memory/candidate
budget failure yields no partial ranking and cannot count as proof success.

The provider bridge retains the existing bounded `PremiseScope` contract (8192
available names); this is not yet a whole-library scope service. Rebuild into a
new output path when inputs change. Existing caches are retained, not evicted.

## SkillCenter canonical corpus adapter

Install `jevops[knowledge-corpus]` for the additional PyArrow reader. The adapter
accepts the upstream `skillcenter-corpus/v1` directory containing a pinned
`manifest.json`, corpus Parquet and CID-index Parquet. It does not read SQLite
bundles, execute source instructions, fetch URLs, load extensions, or import the
upstream package at runtime. Only the interoperability test optionally uses the
upstream writer, with SQLite connections forbidden.

```bash
python -m jevops.skillcenter_corpus --corpus /path/to/canonical-export \
  --manifest-sha256 EXPECTED_SHA256 --split unassigned \
  --output /existing/capped/path/new-evidence.duckdb
```

The CLI emits a compact, programmatically generated artifact receipt. The
manifest/file hashes, raw CIDv1/sha2-256 profile, entry preimage, original UTF-8
body hash, container digest, source-reference ID, derived license fields,
dataset revision, per-bundle counts, unique keys and every CID-index foreign key
are checked before publication. This is identity/coverage verification, **not**
attestation of source truth, actual licensing rights, or Lean correctness. The
restricted SkillCenter identity encoder is tested against the upstream producer,
including Unicode NFC, signed zero and extreme float64 scores; it is not a
general IntentIR canonicalizer.

`EvidenceCorpus(path, expected_sha256=...)` provides bounded `context((cid, ...),
excluded_cids=(...), max_context_bytes=...)`. Bodies remain explicitly untrusted
source text with `proof_verified=false`. The required caller-supplied split is
snapshot-bound: only `library`/`train` may return context; unassigned and held-out
splits abstain. Exclusions are CID-based, not yet graph-family closure. A missing
requested CID or exhausted context budget returns no partial records. Byte
counts are checked before fetching bodies into Python. No evidence body enters
premise BM25 statistics or training through this API.

The importer batches 64 rows, uses DuckDB unique constraints and a SQL coverage
join rather than a corpus-sized Python CID set, caps row/file/decoded/final
artifact sizes, and rejects Parquet row groups declaring over 16 MiB expanded
size. It preserves all row fields (binary identity fields as hex in JSON), plus
the full manifest. Hashes are rechecked after ingestion to detect ordinary
mid-import mutation. Keep the input immutable; this is not protection against a
hostile racing filesystem. PyArrow decompression is not covered by DuckDB's
128 MiB memory limit. There is no automatic shard splitting, resumable import,
aggregate storage reservation, or hard RSS/peak-disk sandbox yet.

Source skills, similarity edges, and licenses cannot serve as theorem
certificates. The opt-in mapping bridge below supports only an explicit
propositional fragment, not arbitrary graph autoformalization.

## Scoped relationship obligations

`jevops.knowledge_relations` accepts a `RelationGraph` with an exact target-record
hash, environment hash, evidence-corpus snapshot and extraction identity. Nodes
map stable graph IDs to structured propositional formulas; they cannot contain
Lean commands. Edges distinguish `implies`, `iff` and `similarity` and cite
existing SkillCenter entry CIDs. A `DeclarationBinding` names one exact scoped
Lean declaration, binds `content_hash(asdict(premise))` and
`content_hash(signature.to_dict())`, and supplies structured proposition
arguments. It does not supply arbitrary proof text or new local assumptions.

The bridge checks the record/environment, resolves every evidence CID through
DuckDB, enforces evidence partition/exclusion policy, reconstructs the nomination
index to detect mutation, and uses its existing target/alias/dependency exclusion
closure. Missing, stale, unavailable or excluded mappings cannot silently enter
proof search. Multiple bindings for the same edge and dangling endpoints are
rejected; missing bindings remain explicit `UNMAPPED` obligations.

```python
from jevops.knowledge_relations import RelationGraph, propose_relations, evaluate_relations

graph = RelationGraph.from_dict(mapping_document)
proposal = propose_relations(graph, record=record, index=nominations, scope=scope,
                             corpus=evidence_corpus, excluded_cids=protected_cids)
if proposal["status"] == "PROPOSED":
    receipt = evaluate_relations(proposal, graph, record=record, index=nominations,
        scope=scope, corpus=evidence_corpus, excluded_cids=protected_cids,
        evaluator=trusted_arena_evaluator)
```

Each used mapping becomes a fresh local `have` whose expected type is the graph
edge, with a proof term such as `@_root_.Bridge.forward (p) (q)`. Lean must check
that term against the edge type; raw signature heads and hashes do not discharge
the obligation. The existing bounded constructive search composes implications,
combines opposite directions into equivalences, and uses equivalences in either
direction. It does not infer a converse, fact from an unseeded cycle, or logical
rule from similarity. Only mappings in the actual proof support are emitted.
A local proof that used no mappings is labeled `NO_GRAPH_PLAN`, not graph success.

Evaluation re-derives the proposal from the current graph, evidence, inventory,
scope, exclusions and limits **before any compiler call**. The unchanged theorem
then passes through `ArenaEvaluator`. Only all-pin native success marks used
edges `CHECKED_IN_CANDIDATE`; unused mappings remain unchecked. Fixture successes
cannot mark native proof verification. Per-evaluation verifier-call/cache-hit
deltas distinguish new checks from receipt reuse. Extraction/source fidelity
remains explicitly unverified even after a valid Lean proof: type correctness
cannot prove that a prose claim was translated faithfully.

Current bounds: 32 nodes, 32 edges, 16 bindings, 32 distinct evidence CIDs,
64 eligible nominated declarations, and 16 total local hypotheses plus mapped
edges. Search, input, evidence context and candidate byte budgets fail closed.
Only proposition atoms present in the original goal/hypothesis types are allowed;
unused or dependent binders, term-valued arguments, universal graph relations,
equality congruence and side-condition synthesis are not inferred. This is not a
whole-library graph service, shortest-proof algorithm or a hard real-time sandbox.
The rendered type obligations can increase token/heartbeat cost; native validity
is not evidence of compression. Training, watcher changes and promotion remain off.

## Verification

Fresh offline tests:

```bash
python -m pytest tests/test_knowledge_index.py tests/test_knowledge_proofs.py tests/test_skillcenter_corpus.py tests/test_knowledge_relations.py --test-seal=off -q
```

Explicit native controls, using already installed Lean 4.26.0 and 4.29.1:

```bash
JEVOPS_ARENA_NATIVE_TESTS=1 python -m pytest tests/test_knowledge_proofs.py --test-seal=off -q
```

The new native bridge control additionally exports signatures on both installed
pins, persists/retrieves them through DuckDB, proposes a proof with the existing
Arena provider, and verifies the resulting candidate on both pins:

```bash
JEVOPS_ARENA_NATIVE_TESTS=1 python -m pytest tests/test_knowledge_index.py::test_native_inventory_duckdb_bridge_and_all_pin_verification --test-seal=off -q
```

The 2026-09-24 validation receipts are generated by pytest, not hand-authored:

- [Regression XML](papers/completion/lean_refactor_arena/evidence/knowledge-bridge-validation-2026-09-24/regression.xml): 194 passed, 19 opt-in tests skipped; includes the actual upstream SkillCenter writer integration, using `PYTHONPATH=/home/barberb/ipfs_datasets_py` to select the reviewed checkout.
- [Native XML](papers/completion/lean_refactor_arena/evidence/knowledge-bridge-validation-2026-09-24/native.xml): 24 passed (15 offline planner tests, eight native planner cases, one native DuckDB bridge test covering both pins). These are not 24 independent Arena benchmark cases.

Native cases check unchanged theorem types, both reference and candidate proofs,
empty axiom sets and heartbeat observations. These small controls are not the
15-case Arena benchmark, an autoencoder training run, or evidence of a new high
score. Native tests never reuse sealed results.

Relationship bridge controls can additionally retain full machine-generated JSON
receipts (the output directory must exist; existing case files are never replaced):

```bash
JEVOPS_RELATION_RECEIPTS=/existing/new-run-directory JEVOPS_ARENA_NATIVE_TESTS=1 \
  python -m pytest tests/test_knowledge_relations.py::test_native_all_pin_mapping_obligations_accept_correct_and_reject_wrong_types --test-seal=off -q
```

The separate [relationship regression receipt](papers/completion/lean_refactor_arena/evidence/knowledge-relations-validation-2026-09-24/regression.xml)
records 252 passed and 23 opt-in skips. The [four native scenario controls](papers/completion/lean_refactor_arena/evidence/knowledge-relations-validation-2026-09-24/native.xml)
passed on the installed 4.26.0 and 4.29.1 pins, with zero receipt-cache reuse:
[opposite-direction composition](papers/completion/lean_refactor_arena/evidence/knowledge-relations-validation-2026-09-24/contrast.json),
[implication chaining](papers/completion/lean_refactor_arena/evidence/knowledge-relations-validation-2026-09-24/chain.json),
and [equivalence reversal](papers/completion/lean_refactor_arena/evidence/knowledge-relations-validation-2026-09-24/iff.json)
were verified on both pins; the [wrong-type mapping](papers/completion/lean_refactor_arena/evidence/knowledge-relations-validation-2026-09-24/wrong_type.json)
was rejected on both pins. Receipts include the exact original record, graph,
native inventory, retrieved evidence and candidate/evaluation observations.
Artifact paths inside them refer to temporary test fixtures, not retained
production databases. These controls do not calibrate an Arena score baseline or
establish token/heartbeat improvements; source fidelity and training remain off.

## Synthetic ingestion probe

`jevops.knowledge_probe` programmatically generates a bounded corpus, builds a
DuckDB artifact, checks exact-name retrieval and broad-query exhaustion, and
writes a machine-generated `report.json`. It keeps every completed artifact and
refuses to overwrite an existing output directory.

```bash
python -m jevops.knowledge_probe --output /existing/capped/path/new-knowledge-probe --records 64 512 2048 --queries 16
```

The [2026-09-24 receipt](papers/completion/lean_refactor_arena/evidence/duckdb-knowledge-probe-2026-09-24/report.json)
records the actual build/open/query times, database bytes, input and snapshot
identities, correctness checks and budget outcomes. It is a single-process,
synthetic, post-build probe with 16 exact-name queries per size. It is not cold
storage latency, real Lean premise recall, a comparison against another backend,
an RSS/peak-disk profile, or a million-record scalability result. The broad query
uses a 64-candidate cap and should abstain for the larger two corpora.

The small artifacts show appreciable fixed database/index overhead; benchmark
shard sizes before creating one database per tiny declaration group. Larger
real-corpus probes must reserve aggregate transient disk headroom first, and
must include query scope construction/dependency filtering in the measured cost.

For a matched comparison of the two premise insertion modes:

```bash
python -m jevops.knowledge_probe --output /existing/capped/path/new-ingestion-comparison --records 64 512 2048 --queries 16 --compare-ingestion --rounds 3
```

The comparison alternates mode order, retains every completed database and
per-arm receipt, and checks snapshot and complete query-result digests before
reporting a ratio of median build times. Failures, mismatches and incomplete
runs do not produce a speedup. Before each build it requires 640 MiB free
(128 MiB working allowance plus 512 MiB reserve); a storage stop retains all
existing artifacts. This check is not a hard aggregate reservation or peak-disk
measurement: run under the existing shared lock on the capped volume and do not
interpret it as permission to exceed the fixed storage allowance.

These are same-process synthetic trials, not cold-start measurements,
SkillCenter import throughput, a memory profile, learned compression or Arena
token/heartbeat scores. Corpus transport parity is covered separately by
multi-batch tests and upstream writer interoperability. The comparison report
records implementation hashes, database configuration and actual timings.

Bulk-transport validation on 2026-09-24: the
[broader regression](/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/knowledge-bulk-20260924-fEJjLs/regression.xml)
passed **253 tests**, including 13 native bridge controls across installed Lean
4.26.0/4.29.1; one separately opt-in relation benchmark was skipped. The
[final transport/probe recheck](/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/knowledge-bulk-20260924-fEJjLs/probe-check.xml)
passed 18 tests. These include a tiny two-round comparison as a correctness
fixture, not meaningful throughput evidence. The intended 64/512/2048-row,
three-round timing run never started: another solver experiment held the shared
build lock, including after a bounded wait. No larger-run speedup is claimed;
no background benchmark is left queued. All prior caches remain retained.

## Design references

For frozen local-only versus mapped-premise measurements, see
[relation experiments](KNOWLEDGE_RELATION_TRIALS.md). Both arms use the existing
constructive search and native verifier. Matched ceilings do not imply matched
work, and extra premises do not isolate a graph-structure effect. Abstentions,
identical sources and failed controls remain explicit.
Optional structural renderings keep the original typed witness in the trial;
implicit argument inference cannot certify a supplied graph instantiation merely
because the shortened theorem compiles. Direct local terms provide a matched
rendering control, and all variants stay opt-in with training disabled.

[Protected relation canaries](KNOWLEDGE_RELATION_CANARIES.md) extend those
controls with six fixed synthetic cases and a persistent DuckDB exposure
ledger. Structural renaming cannot refresh a used canary; setup failures and
abstentions remain visible. This is not a blind generalization or Arena claim.

The reviewed SkillCenter corpus, BM25, graph and semantic-projection modules at
ipfs_datasets_py revision `7f0d38572` inform the separation of content identity,
retrieval hints and proof authority. This backend is DuckDB-only and does not
import those upstream database implementations.

DuckDB connection/configuration and interruption interfaces:
[Python API](https://duckdb.org/docs/current/clients/python/reference/).
