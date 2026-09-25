# Assignment-aware cycle pilot: more eligible keys, no shorter refactor

Historical exploratory evidence, not an admission cache or official score.
[Implementation, trust boundary and exact test commands](../../../../../ARENA_ASSIGNED_CYCLE_GUARD.md).

## Protocol and result

Public warmup `Core.InitsUpdatesComm`, original 224 Arena tokens. Fresh original
controls verified on Lean 4.29.1, 4.27.0 and 4.26.0. The three arms share a fresh
37-event capture and eight-lemma all-pin inventory. Nominees are
reference-informed, not held-out. All select events **13, 14, 17, 2**.

`raw` uses the previous conservative raw-key guard. `observe` follows existing
assignments without pruning; `guarded` follows those assignments and prunes exact
eligible ancestor repeats. All have proposition-only discharge, window eight,
depth eight, 96 primitive attempts, 32 retrievals (top-k four), 256 discharge
inspections and 256 cycle inspections per invocation. Each arm has four
discovery invocations and one shorter-draft slot. No late data fallback,
constraint solver, new tactic, enlarged budget or relaxed context equality was
mixed into this comparison.

| Arm | Primitives | Retrievals | Cycle checks | Eligible keys | Prunes | Shorter drafts | Discovery seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw pruning | 349 | 47 | 51 | 3 | 0 | 0 | 98.0410 |
| Assigned observation | 349 | 47 | 51 | 17 | 0 | 0 | 96.9558 |
| Assigned pruning | 349 | 47 | 51 | 17 | 0 | 0 | 102.0877 |

Each arm made 126 `apply` attempts, 310 discharge inspections and 135
non-propositional discharge skips. Every proof path is null. **No draft reached
whole-source screening, measurement or confirmation. No Arena improvement was
produced.** `official_score` is `null`, not a measured zero score.

Each arm reserved 384 primitive, 128 retrieval, 1,024 discharge-inspection and
1,024 cycle-check units. No timeout, unknown search count, cycle-check exhaustion,
classification error or key-size/depth overflow occurred. Events 13, 14 and 17
hit the primitive cap; event 2 used 61 attempts. These are separate work units,
not interchangeable cost measures.

Raw checks visited 5,090 expression nodes. Each assigned arm visited **6,371
expression nodes plus 491 universe nodes**, following **277 term assignments**
and zero universe assignments. Repeated dereferences count again; 277 does not
mean 277 distinct variables or solved constraints. Assigned V6 `nodes` includes
universe visits whereas V5 raw `nodes` does not, so the totals are not identical
cost units. Assignment following added inspection work without changing proof
search in this task.

**19 actual native processes / 19 stage reservations, 513.9291 seconds total**,
under the predeclared ceiling of 76. Serial single-run timings are not a speedup
estimate: setup, cache and ordering effects are not isolated. The optional guard
remains disabled by default. No model/API calls, downloads, project builds or
automatic promotion occurred. Money and electricity costs are unmeasured
(`null`). This is trusted-local native execution, not an OS sandbox.
`COMPLETE` means the bounded protocol finished, not that a refactor was found.

## What the new observations establish

The two assigned arms have identical cycle observations:

| Event | Checks | Eligible keys | Unresolved term in goal | Combined node visits | Term dereferences |
| --- | ---: | ---: | ---: | ---: | ---: |
| 13 | 14 | 2 | 12 | 1,219 | 64 |
| 14 | 15 | 2 | 13 | 1,275 | 62 |
| 17 | 14 | 7 | 7 | 2,946 | 141 |
| 2 | 8 | 6 | 2 | 1,422 | 10 |

Following existing assignments increased eligible inspections from 3 to 17.
None matches an eligible ancestor. The remaining **34/51** inspections stop at
an unresolved term metavariable in the **goal**, before completing the rest of
the context. This identifies the first obstruction only; it does not establish
that the unvisited context is free of unresolved constraints. There were no
unresolved-universe or delayed-assignment outcomes in this trial.

For example, event 13 at primitive offset 1 yields an eligible key after 489
expression visits, 33 universe visits and 19 assignment dereferences. At offset
10, inspection follows four assignments but then encounters an unresolved goal
term and abstains; it does not solve that variable or manufacture a cycle.
The other eligible inspection in this event, at offset 61, is not an exact
ancestor repeat. Partial applications and key eligibility are not proof wins.

The **entire primitive, retrieval and discharge-check traces are identical
across all three arms**, not just their totals. They also reproduce the previous
[raw-key trial](../cycle-guard-pilot-2026-09-24/README.md); the raw cycle trace
matches that trial too. The two assigned cycle traces are identical. This is
observed non-interference on these four selected events, not a general theorem
about every Lean state.

The evidence does not support loosening equality to theorem names or dropping
local hypotheses. A useful next isolated experiment is a bounded **late data
discharge** fallback: after proposition-first work, allow already-present local
data/witness terms to constrain unresolved arguments before recursive expansion.
That is a hypothesis, not an implemented result of this trial. It needs its own
rollback/admission controls and matched comparison; earlier eager data discharge
increased work, so it must not silently replace the current policy.

## Identity and retained evidence

The 12 JSON files here are byte-identical runtime outputs plus the frozen
snapshot manifest. Draft files retain the full bounded search observations.

- Plan content hash: `84fcd6b4bee7bd21afe88042e3e7bee69e81400a69851ce800d676a5216a1295`.
- Snapshot manifest SHA-256: `a1a648cea0a841ac630ef111aff6c50ee704484f2fe43952fd429cc74d44a0d9`.
- Snapshot content hash: `307b5bc1e56703efe3932192a77828476791e5c63daa633151041f318cb1f242`.
- 420 source/input files, 8,678,061 bytes; unchanged before/after execution.
- Capture SHA-256: `aaff17c0a0819281ab62a302e0fd2bccda8a60c6b6b70f8e8c4cbab8bef422ef`.

Hashes establish content identity, not truth. Full capture and reservation
journals remain in:

```text
/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/assigned-cycle-20260924-jUfzts/run
```

Reservation journal SHA-256 hashes, in stage order:

```text
reservation-000.json d772d4ddf0637fa29690b55471b93755856b2cbe1764d077f8846e25bb13061a
reservation-001.json 774ad7d7df6fb538c90c6c91b9b3f684b5300b4a6a14c1f6a78a135cafa130b2
reservation-002.json 46451cf64d690d648e7f4a922b878337ad2c679148b5630bb33193daa5dba356
reservation-003.json 34e8c60807f01d7faa46579d323ba75e4368ab1fb8d7aa19399bbf0b2de33691
reservation-004.json 2ab1a96bba960318ddd95c46717bba9f29fde90fb93dc998777aaaa5a83ecace
reservation-005.json 0e93eb571b6d80880796d9811f5c8ac7b2ab4bdce042146e5a63eddeba299461
reservation-006.json 02a3f8931aa11a0574979432b35627d9337e1471cc574fd9be22c0937bd06b5c
reservation-007.json 33873bc6212ba2023ee3e9c15e66e7e8e0b07143b91f423b60b259a6482724a8
```

The sibling `snapshot` directory retains the read-only implementation and
explicit project/nominee inputs. Eight changed code/test files were checked
byte-for-byte against that snapshot. The 50,000,000,000-byte preparation cap was
revalidated after the run (39,366,598,656 filesystem bytes used;
4,671,713,280 available). The exclusive kernel-held lock was released and
successfully reacquired for the audit. No native trials ran concurrently.

## Command used

This factors the actual command into shell variables. Its output already
exists and must not be overwritten. A new trial needs a new snapshot/output
directory and the new snapshot's manifest hash.

```bash
assigned_prep=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM
assigned_trial="$assigned_prep/work/assigned-cycle-20260924-jUfzts"
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  TMPDIR="$assigned_prep/work/tmp" JEVOPS_CAS_DIR="$assigned_trial/cas" \
  python -I -B "$assigned_trial/snapshot/papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py" \
  --execute --comparison assigned-cycle --cap 1 --max-processes 76 \
  --nominees "$assigned_trial/snapshot/inputs/nominees.json" \
  --projects "$assigned_trial/snapshot/inputs/projects.json" \
  --preparation-root "$assigned_prep" --elan-home "$assigned_prep/work/elan" \
  --snapshot-manifest-sha256 a1a648cea0a841ac630ef111aff6c50ee704484f2fe43952fd429cc74d44a0d9 \
  --output "$assigned_trial/run"
```
