# Lossless structural expression storage

The bounded `jevops.expr_dag` / `jevops/lean/ExprDAG.lean` codec stores closed
Lean expressions as shared, topologically ordered graphs. This is implemented
storage infrastructure, not proof shortening, a graph autoencoder, or a new
arena score. The [JeV learning plan](STRUCTURAL_AUTOENCODER_PLAN.md) retains its
separate, potentially lossy proposal/training path.

## What is preserved

The Lean exporter traverses actual `Lean.Expr` values from a compiled theorem,
not pretty-printed approximations. It encodes the proof and declared type into
one shared table, including:

- Bound-variable indices, binder names and all four binder annotations.
- Applications, lambdas, foralls, let types/values/bodies and the `nondep` flag.
- Structured names, distinguishing a dotted string component from a name path,
  and numeric components from strings containing digits.
- Universe zero/successor/max/imax/parameters in a separate shared table;
  constant universe arguments retain order and multiplicity.
- Natural/string literals and structure projection names/indices.
- Ordered scalar metadata entries, including duplicate keys, with exact string,
  Boolean, name, natural and integer payloads.

Ordinary `Expr` equality is alpha-oriented and ignores binder annotations;
the codec uses `ExprStructMap` / `Expr.equal`, which includes binder names and
annotations. Round-trip checks compare the reconstructed native expressions
and re-encoded wire representation. Derived runtime caches and physical allocation
identity are not serialized. [Lean expression API](https://lean-lang.org/doc/api/Lean/Expr.html)

Syntax-valued metadata is explicitly unsupported, not silently dropped.
Free variables, expression/universe metavariables and loose bound variables at
roots are rejected. Universe parameters are permitted; theorem exports also
record their declaration list. A future proof-state codec will need explicit
local/metavariable contexts before it can handle open elaborator states.
The separate [proof-state observer](PROOF_STATE_CAPTURE.md) now captures a bounded
context projection for dependency analysis; it does not add decoding/round trips
for open states to this codec.

Sharing a `bvar 0` node under two different binders does **not** identify the
variables semantically. Each occurrence is interpreted under its own binders.
No let-lifting, substitution, alpha-renaming or cross-scope rewrite occurs.

## Wire and resource contract

V1 has exactly eight fields: `schema`, `environment`, `lean_version`,
`lean_githash`, `metadata_policy`, `levels`, `expressions`, and `roots`.
Tagged-array nodes refer only backward within their table. Node numbering is
root-ordered first-use postorder. No duplicate/unreachable nodes are accepted by
the portable validator or native CLI round-trip check. All integers, including
references, are canonical decimal **strings**, avoiding JSON precision loss and
numeric-exponent expansion. Names are lists of tagged string/numeric components.

The default node budget is 50,000, with a hard 100,000 limit across both tables.
Other limits: 256-node path depth, 64 roots/name components, 256 metadata entries
or constant universe arguments, 4,096 integer digits, 1 MiB string payloads and
16 MiB uncompressed JSON. Exceeding a limit fails; the codec never truncates data.
Compressed input is also bounded and rejects trailing streams/truncation.
The native CLI stops reading at the byte limit plus one, before parsing JSON,
and rejects malformed UTF-8.

`pack_dag` uses zlib over deterministic JSON; `unpack_dag` validates the restored
graph. This is a storage baseline, not an entropy-coded learned codec. Packing
need not make every small input smaller. Size reports expose raw JSON bytes,
zlib bytes, expression/level node counts and expanded expression counts per root.
Expanded counts are computed over the DAG, without constructing an expanded
tree. They exclude universe/name/metadata payload substructure; serialized byte
counts include the complete wire envelope and payloads.

## Correctness and trust boundaries

`validate_dag` checks format, bounds, canonical numbering, reachability and
binder scope. It does **not** know whether an application typechecks or a
constant exists. Its report always says `kernel_typechecked=False` and
`proof_admitted=False`.

The Lean theorem-export path decodes the graph, runs the native kernel type
checker on the restored proof, and checks its inferred type against the restored
declared type. It separately reports transitive axioms. It does not install a
new theorem or override the existing axiom/size admission gates. Kernel checking
relative to an environment containing axioms is not an axiom-policy approval;
`proof_admitted` remains false. No independent kernel implementation is run.

The Python wrapper hashes the actual `Main.olean` companion artifacts and codec
before/after export, combines them with a required caller-supplied dependency
environment fingerprint, and binds that identity into the graph. It does not
independently verify the complete dependency closure; that limitation is reported
as `dependency_closure_verified=False`. The native decoder requires its exact
Lean version/build hash. Fingerprints bind data; they are not signatures.

Losslessness here means exact supported **expression structure**, not original
Lean text, comments, whitespace, macros or `InfoTree`. Elaboration has already
removed distinctions needed to reconstruct those. It also does not imply that a
lossy learned embedding is reversible or that the encoded proof is minimal.

## Usage and validation

Compile `Main.lean` in the intended project first. Supply a real environment
manifest fingerprint rather than treating a path string as a dependency manifest:

```python
from pathlib import Path
from jevops.expr_dag import export_olean, pack_dag

report = export_olean(
    directory=Path("/path/to/compiled-module"), declaration="my_theorem",
    project_root=Path("/path/to/project"), use_lake=True,
    environment_sha256=dependency_manifest_sha256,
)
if not report["ok"]:
    raise RuntimeError(report["reason"])
wire = report["dag"]
archive = pack_dag(wire, environment=wire["environment"])
with open("proof.dag.zlib", "xb") as output:
    output.write(archive)
print(report["storage"])  # Small generated summary; do not print massive terms.
```

The native CLI also accepts `roundtrip ENV_SHA256 NODE_BUDGET` with a JSON wire
on stdin. This reconstructs native expressions and checks canonical re-encoding,
but does not typecheck arbitrary input graphs. Use Python's strict JSON loader
first for untrusted transport input; it additionally rejects duplicate JSON keys.

```bash
python -m pytest -q tests/test_expr_dag.py
```

Tests cover every supported expression/universe constructor, exact metadata and
names, sharing beneath binders, exponential expanded-tree counts without tree
expansion, corruption/resource failures, a universe-polymorphic theorem, and an
optional Mathlib theorem using `JEVOPS_MATHLIB_PROJECT`. Synthetic graph fixtures
include untyped expressions to test storage separately from theorem validity.
No graph model is trained and no compression result is promoted by these tests.

The subsequent [training-pair bridge](STRUCTURAL_TRAINING.md) uses per-root
structural fingerprints and recounted proof costs to gate shorter teacher
endpoints. It connects verified targets to sparse distillation while retaining
the graphs; it does not change this codec's storage or trust contract.
