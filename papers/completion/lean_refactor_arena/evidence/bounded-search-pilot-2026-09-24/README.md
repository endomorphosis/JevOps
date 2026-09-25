# Span selection and bounded backward-search pilot

Historical exploratory evidence, **not an admission cache, official score or
demonstrated Arena improvement**. The implementation, tests and trust boundary
are described in [the search note](../../../../../ARENA_BOUNDED_BACKWARD_SEARCH.md).

## Fixed protocol and result

- Public warmup `Core.InitsUpdatesComm`, eight reference-informed library
  nominees, not held-out evaluation. Original source remains 224 Arena tokens.
- Lean 4.29.1, 4.27.0 and 4.26.0: all three original-proof controls verified.
  All eight inventory declarations and signatures agreed across pins.
- Shared fresh capture: 37 closing spans, 31 editable/ranked observations.
- Four discovery processes and one final draft slot per arm. Typed retrieval
  in all arms. Same process/deadline caps; internal primitive work is **not**
  matched. Serial discovery order: headroom, matching, backward.
- All arms produced **zero shorter drafts**, zero whole-source candidate
  screens and zero measured candidates. No confirmation or promotion.
- Actual native processes and stage reservations: **19**, versus maximum 76.
  Total measured run wall time: **573.7201 seconds**. No API calls, downloads,
  project builds, GPU, trained policy or measured monetary cost.
- `COMPLETE` means the predeclared protocol finished, not that a target improved.
  `ABSTAINED` means no checked shorter draft, not a disproved proposition.

| Arm | Attempted span IDs | Observed work | Drafts | Discovery seconds |
| --- | --- | --- | --- | --- |
| Headroom, one-step | 2, 6, 8, 11 | 4 application processes | 0 | 112.1929 |
| Matching-head, one-step | 13, 14, 17, 2 | 4 application processes | 0 | 115.8572 |
| Matching-head, backward | 13, 14, 17, 2 | 159 primitive attempts, including 92 `apply` attempts | 0 | 111.2013 |

The backward arm reserved 384 primitive attempts, observed all four processes'
internal work (zero unknown processes), and performed no extracted-term replay
because no complete path was found. These single-run timing differences are
not evidence of a speed improvement. The two single-step arms include original
baseline replay; all eight baseline replays closed and passed the local kernel
and axiom checks. This trial did **not** fail because baseline replay was broken.

## What the trace actually shows

The matching-head schedule now reaches different spans: 94, 52 and 34 source
tokens before giving its fourth slot to the largest fallback. It does not claim
that matching predicate names establishes matching arguments.

- **Event 13:** `updatedStateUpdate` has the right predicate head, but its final
  store expression does not unify with the goal's store expression. Backward
  search uses 14 primitive attempts, with no depth/step exhaustion. This is a
  candidate for a separately scoped rewrite/normalization experiment, not a
  reason to equate the two expressions heuristically.
- **Event 14:** native `updatedStateUpdate` applies, but leaves a store-lookup
  equality that `assumption` cannot close. Its four-nominee pool lacks
  `InitStatesSomeMonotone`. Backward search exhausts its permitted alternatives
  after 21 attempts without exhausting depth or steps.
- **Event 17:** actual successful primitive applications include
  `updatedStateUpdate → InitStatesSomeMonotone → updatedStatesInit`, with local
  assumptions discharging some siblings. This is a **partial proof**, not a
  checked derivation of the target. The remaining premises are not closed. The
  run hits 96 attempts and records six depth cutoffs. Its four-nominee pool lacks
  the other monotonicity/nondefinition lemmas used by the original local proof.
- **Event 2:** the fallback introduces two hypotheses and opens constructors,
  then fails at a depth boundary; 28 attempts, one cutoff, no complete path.

Next justified experiment: bounded retrieval keyed to newly created subgoals
(with explicit retrieval traces and the same scope exclusions), separately
ablated from a reviewed rewrite/normalization action set and increased depth.
Merely raising the attempt budget cannot add missing lemmas to a fixed pool or
make distinct store expressions definitionally equal. Nothing in this run
establishes how well those unimplemented extensions would perform.

## Evidence and source identity

`report.json` and `plan.json` are original runtime outputs. The three draft
reports retain rankings, exact selected work, primitive traces and one-step
baseline/rejection summaries. `inventory.json` retains per-pin export receipts.
`context.json` and the three controls bind the actual verification context.
These content hashes bind records; they do not authenticate an untrusted producer.

- Plan ID: `c6172c9bab4954f1476284a9895fb6437ccede457d8f78ebf1bec08ca5b2d891`.
- Read-only source snapshot: 239 files, 4,938,714 bytes; unchanged before/after.
- Snapshot manifest SHA-256:
  `9f8f4d52453061596f21b3ef06a5566164a244d7997a66e6913062054a429d30`.
- The additional periodic-fallback test and updated documentation were added
  after snapshot creation. Search/planner/pilot implementation bytes used by
  this run were unchanged.

The full capture and reservation journal remain at
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/backward-search-20260924-6pb2Gj/run`.
The large `capture.json` is not duplicated here; its SHA-256 is
`f1255a06ada5bc0df7cc8c453fca23eda0c365a380d46587d3b83d10842459c9`.
The readonly source bundle is the sibling `snapshot` directory. Compact reports
here are byte-for-byte copies of the original outputs, not reinterpreted receipts.

The executed command (expanded paths below; choose a fresh output directory for
a repeat because existing output directories are intentionally refused):

```bash
trial_root=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/backward-search-20260924-6pb2Gj
prep_root=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  TMPDIR="$prep_root/work/tmp" JEVOPS_CAS_DIR="$trial_root/cas" \
  python -I -B "$trial_root/snapshot/papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py" \
  --execute --comparison bounded-search --cap 1 --max-processes 76 \
  --nominees "$trial_root/snapshot/inputs/nominees.json" \
  --projects "$trial_root/snapshot/inputs/projects.json" \
  --preparation-root "$prep_root" --elan-home "$prep_root/work/elan" \
  --snapshot-manifest-sha256 9f8f4d52453061596f21b3ef06a5566164a244d7997a66e6913062054a429d30 \
  --output "$trial_root/run"
```
