# Context-aware proof-state observations

`jevops.proof_state` and `jevops/lean/ProofState.lean` capture bounded before/after
observations from native Lean `InfoTree` tactic nodes. A separate analyzer groups
visible goals by shared unresolved term or universe metavariables. This is an
opt-in data-collection increment, not an executable LeanTree replacement, a
replayable context codec, a trained graph model, or proof admission.

## Representation and dependency analysis

Each snapshot contains a shared expression/level table, the ordered visible
goal IDs, and their reachable metavariable declarations. It retains:

- Ordered local declarations with types, transparent-let values, names, binder
  annotations, declaration kinds, indices, and the let/have `nondep` flag.
- Registered local instances and expression metavariable types, assignments,
  kinds, depths, indices and scope-argument counts.
- Universe metavariable depths and assignments, including transitive links.
- Exact supported expression constructors, structured names, universes and
  ordered scalar metadata. No free/metavariables are silently replaced by text.

The Python validator checks references, node uniqueness/reachability, binder
scope, local declaration order, variable declaration closure, assignment cycles,
and resource limits. It does not check application types or authenticate native
observations. Syntax-valued metadata and reachable delayed metavariable
assignments produce explicit `unsupported` events, not truncated snapshots.
The native encoder also rejects root types, assignments, transparent local values or local
instances with loose bound variables or free variables outside the ordered
recorded local scope. Intermediate InfoTree contexts can fail that check even
when the finished theorem is valid. Such events are wholly unsupported; missing
declarations are never invented.

The native exporter uses `jevops-open-proof-state/v2`. In Lean, a local
`nondep=true` have-binding is an opaque typed variable, not a transparent
definition. Its hidden value may reference a hypothesis that has since been
cleared. Following Lean's `LocalDecl.value?` default, V2 retains the complete
typed declaration with `nondep=true, value=null`, not that obsolete hidden value.
Types, assignments, instances and transparent-let values still undergo full
scope validation. This is an explicit semantic projection, not a lossless dump
of raw Lean internals or permission to omit arbitrary dependencies. The analyzer
continues to read legacy V1 snapshots under their original raw-value contract;
V1 captures are neither silently rewritten nor treated as current V2 anchors.

The analyzer follows goal types, **all** recorded local types/values/instances, and
transitive metavariable contexts and assignments. Connected components share no
unresolved variable *in that captured dependency model*. Solved aliases are
followed to their remaining unresolved dependencies; shared immutable free
variables alone do not couple goals. Including unused locals is conservative
and can yield larger groups than necessary. Context-reference cycles are handled
by graph reachability, not expression expansion; assignment cycles are rejected.

This follows the dependency concern described in
[LeanTree §3.3](https://arxiv.org/html/2507.14722v1#S3.SS3): transitivity goals
sharing a witness cannot be solved independently just because their printed
goals are separate. The implementation here is an observation analyzer, not a
port of LeanTree's proof reconstruction or interactive execution machinery.

## Provenance and boundaries

Events preserve their InfoTree parent, declaration/namespace, syntax kind and
UTF-8 byte span into the supplied source. Before and after snapshots use their
own `TacticInfo.mctxBefore` / `mctxAfter`, never the final declaration's context.
Nested tactic nodes overlap: their pre-order list is **not** a linear execution
trace. A focused event may expose only a subset of a larger proof's goals.
CRLF normalization preserves Lean parsing behavior; exported spans map back to
the original source bytes, including Unicode and both bytes of each CRLF.

Source, exporter, caller-supplied dependency fingerprint, and configured budgets
are bound into the trace identity. The trace records Lean version/build and has
a content hash. These hashes detect mismatched artifacts; they are not signatures
or complete dependency-closure authentication. As with compilation elsewhere,
source and imports can execute metaprograms: this is **not a sandbox**.

This projection does not serialize the complete elaborator environment, options,
pending constraints, name-generation state, all unrelated metavariables, universe
age indices, or syntax trees. It has no decoder or native round-trip claim.
Components are scheduling/learning diagnostics, not permission to parallelize
arbitrary tactics and merge their results without checking. The existing
[closed-expression codec](EXPR_DAG_CODEC.md) is unchanged and still rejects open
states; its losslessness claim does not extend to these observations.

`ok=True` means capture/validation succeeded. It does **not** mean the source
compiled without errors, and even `elaboration_errors=False` does not rule out
`sorry` or unauthorized axioms. `kernel_typechecked`, `proof_admitted` and
`replayable` remain false. Independently recompiling completed candidates and
applying the existing type/axiom/cost gates remains mandatory.

## Collection and use

```python
from functools import partial
from pathlib import Path
from jevops.proof_state import capture_source, collect_training_observations

capture = partial(capture_source, project_root=Path("/path/to/project"),
                  use_lake=True, environment_sha256=dependency_manifest_sha256)
observations = collect_training_observations(rows, capture_fn=capture)
```

The collector reads only training sources, never evaluation sources or targets.
Split/family membership remains caller-owned. It recomputes dependency analyses
from bound raw traces, records failures, and creates **no** successful teacher
labels. Invalid/sorry-containing traces can remain in a diagnostic buffer.
Future policy/critic training must separate before-state inputs from after-state
feedback, resolve nested-event attribution, and independently verify any positive
labels. CE/cosine objectives, JeV updates and all model weights are unchanged;
default distillation and outer-router behavior are unchanged.

The separate [closing-replay bridge](PROOF_REPLAY.md) now regenerates native
contexts from source (never from this JSON), checks original/candidate closing
outcomes, and independently gates shorter whole proofs before edit-head training.
The observation exporter itself still creates no successful teacher labels.
The [Arena project adapter](ARENA_PROVIDERS.md#arena-project-context-and-controlled-comparison)
explicitly selects distinct single-goal closing source spans, rather than all
internal tactic events. It binds this projection into its origin/request and
uses the same selected native references for replay. Selected parents refer to
the nearest retained ancestor. The standalone API still observes all events by
default; neither projection represents a linear execution trace.

Generate a small report using code, without asking an LLM to write its contents:

```bash
python -m jevops.proof_state Example.lean --project-root /path/to/project --lake \
  --environment-sha256 "$DEPENDENCY_MANIFEST_SHA256" --output-dir /path/to/new-run
python -m pytest -q tests/test_proof_state.py
```

The CLI refuses an existing output directory and writes `capture.json` plus a
compact `summary.md`. Its success exit status refers to capture, not proof truth.
Defaults are 4,096 nodes per snapshot, 64 events and a 40-second subprocess timeout.
Hard limits include 1 MiB source, 16 MiB combined process output, 20,000 nodes,
256 events, 128 expression/level depth, 256 reachable metavariables of each sort,
256 locals/instances per declaration, and 64 visible goals. Event-level unsupported
captures are explicit. Each possible event reserves an equal share of the
16,000,000-byte event payload budget (`16,000,000 / event_budget`). An observation
larger than its share becomes a whole `unsupported` event with reason
`event observation byte budget`; no locals, assignments or dependency edges are
silently removed. Its ID/parent/span remain, and later small events still fit.
This can reduce observation coverage even when the actual event count is small;
it is not a proof rejection. Oversized event metadata and global
traversal/event/output limits still fail the run instead
of silently retaining a prefix. The collector defaults to 16 training rows and
32 MiB retained observations. These bounds do not establish compiler-memory or
large-corpus throughput guarantees.

Tests include real Lean conjunction/transitivity/local-definition examples,
failed tactics, `sorry`, synthetic native universe coupling and unsupported
delayed assignments, transitive Python dependency fixtures, scope/corruption
rejection, pipe limits, split exclusion and deterministic reports. Synthetic
contexts test representation rather than mathematical validity. No arena score
or model improvement is inferred from these tests.

The three-theorem native smoke fixture currently captures 59 events without
unsupported snapshots on Lean 4.26.0, 4.32.0 and 4.34.0. These are overlapping
InfoTree observations, not 59 independent tactic executions or held-out examples.
