# Putnam Mathlib+Aesop lake projects

PutnamBench warm-up records (`putnam_1964_a4`, `putnam_1964_b2`, `putnam_1995_a3`) ship with **empty** `url` and `file_path`. Their JSONL `header` is:

```lean
import Mathlib
import Aesop

set_option maxHeartbeats 0

open …
```

They are compiled as modules in a **per-tag Mathlib+Aesop lake project**. They are not `Tmp.lean`, not `lake env lean Tmp.lean` without a lakefile, and not a guessed PutnamBench GitHub URL.

`harness/bake_oleans.py` generates the projects. This directory in git holds only this README. Materialized trees live under the LRA state root (or a path passed to `--materialize-putnam`):

```text
$XDG_STATE_HOME/ipfs_accelerate_py/vericodegen-2026/lean_refactor_arena/
  putnam_lake/<tag>/          # lakefile + Putnam.Candidate
  oleans/putnam/<tag>/        # baked .olean cache copied into the project
  oleans/repo/<host>/<path>/<commit>/<tag>/
  clones/                     # Strata / PhysLib / CSLib / ArkLib checkouts
```

## Per-tag layout

One lake project per Putnam Lean tag from the frozen JSONL:

| Lean tag | JSONL `version_info` pin (not a clone URL) | Mathlib rev | Aesop rev |
| --- | --- | --- | --- |
| `v4.25.0` | `1ccd71f89cbbd82ae7d097723ce1722ca7b01c33` | `v4.25.0` | `v4.25.0` |
| `v4.26.0` | `2df2f0150c275ad53cb3c90f7c98ec15a56a1a67` | `v4.26.0` | `v4.26.0` |
| `v4.27.0` | `a3a10db0e9d66acbebf76c5e6a135066525ac900` | `v4.27.0` | `v4.27.0` |

`putnam_1964_b2` lists only `v4.25.0` and `v4.26.0`. The `v4.27.0` project still exists because the other two Putnam records require it.

Each `<tag>/` tree:

```text
lakefile.lean          # require mathlib + aesop from git at the Lean tag
lean-toolchain         # leanprover/lean4:<tag>
pins.json              # recorded Mathlib/Aesop revs; putnambench_url is null
Putnam.lean            # import Putnam.Candidate
Putnam/Candidate.lean  # compile-worker module (not Tmp.lean)
```

`pins.json` stores the JSONL git commit as `jsonl_version_pin`. That value is **not** used as a PutnamBench clone. If organizers later publish Mathlib/Aesop SHAs in `evidence/run_freeze.json`, replace the tag revs and rebake.

## lakefile (v4.26.0 example)

`bake_oleans.py --dump-putnam-project --tag v4.26.0` emits this lakefile. Measurement forces a finite `maxHeartbeats` even though the JSONL header sets `maxHeartbeats 0`.

```lean
import Lake
open Lake DSL

package «putnam_lake» where
  moreLeanArgs := #["-DmaxHeartbeats=400000"]
  moreServerArgs := #["-DmaxHeartbeats=400000"]

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "v4.26.0"

require aesop from git
  "https://github.com/leanprover-community/aesop.git" @ "v4.26.0"

@[default_target]
lean_lib «Putnam» where
  globs := #[.submodules `Putnam]
```

`lean-toolchain` is the single line `leanprover/lean4:v4.26.0`.

The compile worker copies `header + statement + tactic block` into `Putnam/Candidate.lean` (`splice.lake_candidate_source`) and runs tag-pinned `{lake} env {lean} --json Putnam/Candidate.lean` inside this project. It does not write `Tmp.lean`.

## Bake order (Strata v4.26 first)

`bake_oleans.py --plan` records unique bake jobs from the frozen warm-up JSONL (SHA-256 `6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804`).

1. **Phase 0 — Strata v4.26.0 first.** One repo job: `https://github.com/strata-org/Strata` at commit `451e5f047bafa010d178856db76c00029bfa4d7f`, tag `v4.26.0`, covering `CallElimCorrect.lean` and `StatementSemanticsProps.lean`.
2. **Phase 1 — remaining `(url, commit, tag)` repo jobs** (other Strata tags, then PhysLib, CSLib, ArkLib).
3. **Phase 2 — Putnam Mathlib+Aesop projects** for `v4.25.0`, `v4.26.0`, `v4.27.0`.

Repo oleans are the `.lake` tree of a checked-out clone. Putnam oleans are the `.lake` tree of the per-tag lake project (Mathlib + Aesop). First `lake build` is hours; bake before any 48 h clock.

## `network=deny` fails closed

Official Track 2 and any sealed validation run set `LRA_NETWORK=deny` (or `--network deny`). If the olean cache for a job is missing, the harness raises `OleanCacheMissing` and does **not**:

- fall back to PATH `lean` / `lake`
- fetch Mathlib/Aesop
- guess a PutnamBench GitHub URL
- compile `Tmp.lean`

A cache hit requires both a `BAKED` marker and at least one `.olean` under `oleans/<cache_key>/`.

```text
python3 papers/completion/lean_refactor_arena/harness/bake_oleans.py --self-check
python3 papers/completion/lean_refactor_arena/harness/bake_oleans.py --plan
python3 papers/completion/lean_refactor_arena/harness/bake_oleans.py --dump-putnam-project --tag v4.26.0
python3 papers/completion/lean_refactor_arena/harness/bake_oleans.py --require-cache --network deny
```

`--self-check` plants a synthetic Strata v4.26 cache, proves a missing Putnam cache raises under `network=deny`, and materializes all three Putnam lakefiles in a temp dir. It does **not** run `lake build`. Tag-pinned elan paths follow LRA-012: `{ELAN_HOME}/toolchains/leanprover--lean4---<tag>/bin/{lean,lake}`. If those binaries are absent, that is a recorded capability gap, not PATH lake usability.

## Claim boundary

No Arena scores, token-savings percentages, or official Track 1/Track 2 rankings. Spark NVFP4 wall-clock is not the 4×A100 / 48 h envelope. A specified bake plan is not a completed olean bake.
