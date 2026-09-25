# Cycle-guard pilot: no usable repeats, no shorter refactor

Historical exploratory evidence, not an admission cache or official score.
[Implementation, trust boundary and test commands](../../../../../ARENA_CYCLE_GUARD.md).

## Protocol and result

Public warmup `Core.InitsUpdatesComm`, original 224 Arena tokens. Original-proof
controls verified on Lean 4.29.1, 4.27.0 and 4.26.0. All arms share a fresh
37-event capture and an eight-lemma all-pin inventory. Nominees are
reference-informed, not held-out. All select events **13, 14, 17, 2**.

The baseline is the previous proposition-only discharge policy: window eight,
depth eight, 96 primitive attempts, 32 retrievals (top-k four), and 256 discharge
inspections per invocation. Each arm has four discovery invocations and one
shorter-draft slot. The two cycle-aware arms each allow 256 additional checks
per invocation; only `guarded` prunes eligible ancestor repeats.

| Arm | Primitives | Retrievals | Discharge inspections | Cycle inspections | Explicit node visits | Prunes | Shorter drafts | Discovery seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 349 | 47 | 310 | 0 | 0 | 0 | 0 | 98.6066 |
| Observe | 349 | 47 | 310 | 51 | 5,090 | 0 | 0 | 92.1792 |
| Guarded | 349 | 47 | 310 | 51 | 5,090 | 0 | 0 | 100.4796 |

All arms made 126 `apply` attempts and skipped 135 non-propositional discharge
attempts. All proof paths are null. **No draft reached source screening,
measurement or confirmation. No Arena improvement was produced.**

Each arm reserved 384 primitive, 128 retrieval and 1,024 discharge-inspection
units. Each cycle-aware arm additionally reserved 1,024 cycle-check units.
No timeout, unknown search count, cycle-check exhaustion, classification error,
or cycle-key size overflow occurred. Events 13, 14 and 17 hit the primitive cap;
event 2 used 61 attempts. These distinct work units must not be added together
as though their costs were interchangeable.

**19 actual native processes / 19 stage reservations, 499.2063 seconds total**,
under the predeclared maximum of 76. Single serial-run wall times do not establish
a speedup: ordering, setup and cache effects are not isolated. The guard added
work without changing proof search here. It remains disabled by default.

No model/API calls, downloads, project builds or automatic promotion. Money and
electricity costs are unmeasured (`null`). Execution is trusted-local native,
not an OS sandbox. `COMPLETE` means the bounded protocol finished; failure to
find a proof is not evidence that the theorem is false.

## Why the guard did not help

The compact native checks distinguish key eligibility from a proven cycle:

| Event | Checks | Meta-containing keys rejected | Eligible keys | Node visits |
| --- | ---: | ---: | ---: | ---: |
| 13 | 14 | 14 | 0 | 910 |
| 14 | 15 | 15 | 0 | 975 |
| 17 | 14 | 14 | 0 | 1,680 |
| 2 | 8 | 5 | 3 | 1,525 |

**48 of 51 inspections abstained because an expression in the goal/local
context contained a raw term or universe metavariable.** The current receipt
does not distinguish unresolved metavariables from assigned placeholders, or
identify which context expression contained them. Do not infer that all these
metavariables were unresolved, assigned, or in the goal itself.

The three eligible checks are all from event 2, at primitive offsets 1, 7 and
13, with depths 0, 1 and 2 and declaration counts 9, 10 and 11. Their types and
contexts are not an eligible exact ancestor repeat; all `repeat_of` fields are
null. Repeated lemma names in the earlier hard branches therefore remain a
diagnostic suspicion, not established state equality.

The **entire primitive, retrieval and discharge-check traces are identical
across all three arms**, not just their totals. The two cycle traces are also
identical. Baseline additionally reproduces the previous proposition-only
trial's traces on all four events. Observation/pruning did not accidentally
change unification here, but this is not a universal non-interference theorem.

The next justified experiment is bounded, read-only instantiation of already
assigned metavariables, still rejecting keys with unresolved constraints and
preserving all context information. It needs separate controls and an
observation-only arm before pruning. It is **not implemented by this trial**;
loosening equality to raw heads or silently dropping local hypotheses would
not be a safe substitute.

## Identity and retained evidence

The JSON files here are byte-identical runtime outputs, plus the frozen snapshot
manifest. `*-drafts.json` include the full bounded search accounting; no native
outcome has been converted into a synthetic win or a new proof claim.

- Plan SHA-256: `27e0dd1e24b29f655cd38e3cc0114323643c6d26d7792c0c8df5e19f5a3db85d`.
- Snapshot manifest SHA-256: `0bd35b21a184e4be8260f4318c73b9a5408b1e9824beecdf92d1421b88eea703`.
- Snapshot content hash: `8581a9ef8ab7cf90d81c83c119fb3ab6dd09d022ea7b09683786233b1a165233`.
- 415 source/input files, 8,598,739 bytes; unchanged before/after execution.
- Capture SHA-256: `f48e2cff9f2951f403b7509c3c6800c51ca5cc088bb5779fcef494dfe46f91d7`.

These hashes establish content identity, not truth or proof. Full capture and
reservation journals remain in:

```text
/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/cycle-guard-20260924-oLwVoo/run
```

The sibling `snapshot` directory contains the read-only implementation and
explicit project/nominee inputs. Seven changed runtime/planner/test files were
checked byte-for-byte against that snapshot. The capped 50,000,000,000-byte
preparation volume and its exclusive kernel-held lock were used; no native
trials were run concurrently.

## Command used

This is the command used, with the long roots factored into shell variables.
Its output already exists and must not be overwritten. A new trial requires
a new snapshot/output directory and that snapshot's manifest hash.

```bash
cycle_prep=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM
cycle_trial="$cycle_prep/work/cycle-guard-20260924-oLwVoo"
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  TMPDIR="$cycle_prep/work/tmp" JEVOPS_CAS_DIR="$cycle_trial/cas" \
  python -I -B "$cycle_trial/snapshot/papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py" \
  --execute --comparison cycle-guard --cap 1 --max-processes 76 \
  --nominees "$cycle_trial/snapshot/inputs/nominees.json" \
  --projects "$cycle_trial/snapshot/inputs/projects.json" \
  --preparation-root "$cycle_prep" --elan-home "$cycle_prep/work/elan" \
  --snapshot-manifest-sha256 0bd35b21a184e4be8260f4318c73b9a5408b1e9824beecdf92d1421b88eea703 \
  --output "$cycle_trial/run"
```
