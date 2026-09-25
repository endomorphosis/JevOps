# Lean Refactor Arena competition report

Competition-track report for the NeurIPS 2026 VeriCodeGen workshop, built from:

- Warm-up JSONL: `data/benchmark_data_warmup.jsonl` (SHA-256 `6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804`)
- Arena Space: https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena
- Workshop: https://vericodegen.github.io/
- Competition site: https://leanrefactor.github.io/

This is **not** one of the three research-track boards (`autoformalization`, `law_to_action`, `neurosymbolic_supervision`). It is not registered in `scripts/paper_supervisors.py`. It does **not** claim Arena leaderboard scores, official 4×A100 Track 2 results, or token savings.

## What is measured

The public 15-problem warm-up subset (3 each from Strata, PhysLib, CSLib, ArkLib, PutnamBench). Regenerate the census with:

```
python3 papers/completion/lean_refactor_arena/tools/summarize_warmup.py
```

The script fails closed if the JSONL hash drifts.

## JevOps integration

The executable warm-up harness is now imported into this checkout. Its
correctness boundary remains the frozen `LRA/v1` protocol: the JSONL statement
must stay byte-for-byte at the candidate prefix, every listed version pin is a
Lake compile target, and failures are retained. Run the deterministic checks
with:

```
python papers/completion/lean_refactor_arena/harness/run_warmup.py --plan
python papers/completion/lean_refactor_arena/harness/run_warmup.py --offline-self-check
python papers/completion/lean_refactor_arena/tools/verify_lra_batch.py --schedule
```

Local Leanstral generation now uses the in-tree `jevops.llm_router` client,
not an implicit `ipfs_accelerate_py` import. The offline check uses both fixture
generators and synthetic compilers; it probes no server. `--self-check` retains
its historical optional-live behavior, and `--no-live` alone still probes health.
See the [migration, live commands and tested boundaries](../../../LEANSTRAL_INTEGRATION.md).

`harness/autoencoder_bridge.py` is an explicitly experimental adapter for the
JevOps text → Lean IR → text model and the strict `codex_cli` /
`gpt-5.6-luna` router loop. It records the verified search winner separately
from the autoencoder's actual prediction and keeps cross-entropy/cosine loss
separate from the candidate-target diagnostic. It writes no Arena score:

```
python papers/completion/lean_refactor_arena/harness/autoencoder_bridge.py --plan
```

The complete upstream Lean Refactor source snapshot is also vendored at
[`upstream/`](upstream/), including its optimizer agents, prompts, configs,
and data-extraction project. Its provenance and the retained Mathlib gitlink
are recorded in [`upstream/UPSTREAM_IMPORT.md`](upstream/UPSTREAM_IMPORT.md).
This does not install the upstream LangChain/LangGraph/model/LeanClient
dependencies or copy the large Mathlib checkout into the JevOps core. The
snapshot is therefore available for inspection and optional execution, while
the in-tree warm-up harness remains the reproducible offline path.

The public Arena Space application is vendored separately at [`space/`](space/)
with its Gradio/FastAPI UI, benchmark metadata, leaderboard client, assets,
and Docker metadata. Its `space/UPSTREAM_IMPORT.md` records the source commit
and makes the boundary explicit: the Space is UI-only, while Lean compilation
and official scoring happen in a separate worker that is not part of the
public repository. Web UI dependencies remain optional and are not installed
by JevOps core.

## Corpus readiness

The complete corpus currently available from the public Arena is the frozen
15-problem warm-up: three rows each from Strata, PhysLib, CSLib, ArkLib, and
PutnamBench. It is ready to pass to an optimizer as:

```bash
python papers/completion/lean_refactor_arena/tools/check_corpus.py
```

The checker validates every JSONL row, exact statement-prefix binding,
version pins, uniqueness, source coverage, and the frozen SHA-256. Use a
future corpus without changing the checker with:

```bash
python papers/completion/lean_refactor_arena/tools/check_corpus.py \
  --jsonl /path/to/benchmark_data_full.jsonl --require-full
```

As of this snapshot, the official full benchmark is not public; the Space
announces November 1, 2026 as its release date. The manifest at
[`data/corpus_manifest.json`](data/corpus_manifest.json) records that boundary
explicitly. The warm-up file is therefore the complete *available* offline
fixture, not a claim that it is the unreleased full benchmark.

An actual refactoring run is measured only when the repository clones,
tag-pinned elan toolchains, olean caches, per-problem receipts, and hardware
logs are available. Missing capability is a retained failure, never a PATH
Lean fallback or a claimed Arena result.

## What is unrun

The Leanstral refactoring harness specified in `manuscript/main.tex` (Approach / Models / Budget accounting / Reproduction). No candidate proofs, no elaboration scores, no Space submission.

## Build the PDF

```
cd papers/completion/lean_refactor_arena/manuscript
latexmk -pdf -interaction=nonstopmode main.tex
```

Template: `neurips_2026_vericode_competition.sty` (competition track, not the research workshop style). Reports are single-blind: author name and email are real.

## Layout

| Path | Role |
| --- | --- |
| `typesafe_nca.md` | TypeSafe NCA architecture for agents and harness engineers |
| `harness/nca_*.py` (kernel shims) | Adapters → `~/lift_coding/JevOps` (`jevops.{kernel,tape,stack,jsonld,plan,graph,skill_tree,rankers,int_rankers,more_rankers,temporal,autoencoder,turing,tape_tools,nca}`) |
| `harness/typesafe_nca.py` | LRA walker (tick/feed/mutate/halt); cell store is `jevops.nca` |
| `harness/portable_rewrites.py` | Keep-structure Lean folds (implementation, not kernel) |
| `harness/autoencoder_bridge.py` | Experimental JevOps autoencoder/router adapter; no official score |
| `harness/lean_toolchain.py` | Optional `ipfs_datasets_py` frontend adapter plus local tag-pinned fallback |
| `data/benchmark_data_warmup.jsonl` | Frozen organizer warm-up |
| `data/warmup_summary.json` | Machine-readable census |
| `tools/summarize_warmup.py` | Hash check + table + receipt |
| `manuscript/main.tex` | Competition report |
| `evidence/import_receipt.json` | Import provenance |
| `protocol.md` | Frozen claim boundary |
