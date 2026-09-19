# JevOps

TypeSafe / Jev **kernel**, split from Lean Refactor Arena and other papers.

Jev is a **gate**, not a generator. This package does **not** write Lean.
Lake (or another oracle) lives in the implementation that *uses* the kernel.

## Layout

| Module | Job |
| --- | --- |
| `jevops.hooks` | Optional consumer callbacks (`load_board`, `token_count`, …). Kernel never requires them. |
| `jevops.nca` | Cell store, tick/halt, inspect_python, mutate overlay, dispatch_tool |
| `jevops.walk` | Inner loop, compose dispatch, ptr CALL, nest/spawn, admit_step |
| `jevops.board` | Generic goal/subgoal/task grid seed, status overlay, mark_ready |
| `jevops.outer` | Outer JSON actions, `run_steps` / `route_next`, stall/stop |
| `jevops.oracle` | Candidate order, try_kind / apply_round / pack_eval |
| `jevops.pick` | Jev beam, leftover rank, shorter_bag, sample/filter records |
| `jevops.memory` | Success/failure/blacklist/research JSON memory, gap_report |
| `jevops.jev` | Choice/Score/Noul projectors, truncate_middle, FixtureClient |
| `jevops.kernel` | L0–L3 cache, CID, ARC/LRU, negative TTL, single-flight, context budget |
| `jevops.tape` | Neural tape (window, splice, mask, pop, byte trim) |
| `jevops.stack` | `ptr://` CALL/RETURN stack |
| `jevops.jsonld` | JSON-LD graph interface; DuckDB optional |
| `jevops.plan` | Goal / subgoal / task DAG + graph-of-thoughts |
| `jevops.graph` | Traverse, GraphRAG (JSON-LD first), milles message-pass |
| `jevops.skill_tree` | Hierarchical skill catalog |
| `jevops.rankers` | RF / Bayes-time / MCMC / SVD dispatch |
| `jevops.int_rankers` | Integer milles rankers |
| `jevops.more_rankers` | Markov / isotonic / AdaBoost / PageRank / contrastive |
| `jevops.temporal` | Hawkes / CRF / submodular / delayed bandit / tape conv |
| `jevops.autoencoder` | VAE milles; Jev is the batch loss |
| `jevops.program` | Closed IR compile/parse, work-ops execute (lake/board via hooks) |
| `jevops.repair` | Diagnose/heal grid, tape, stack, program_state |
| `jevops.tools` | TypeSafe tool catalog, MCP++ describe, subloops, KG |
| `jevops.turing` | TM step/run + decision-transformer window |
| `jevops.tape_tools` | Tape editor CALLs (`port_tape_*`) |

## Skills

Grok skills live in `.grok/skills/` (canonical). LRA keeps thin `lra-*` redirects.

| Skill | Module |
| --- | --- |
| `jevops-kernel` | `jevops.kernel` |
| `jevops-random-forest` / `jevops-bayes-time` / `jevops-mcmc` / `jevops-svd` / `jevops-ridge` / `jevops-thompson` | `jevops.rankers` |
| `jevops-int-rankers` / `jevops-pca` | `jevops.int_rankers` |
| `jevops-more-rankers` | `jevops.more_rankers` |
| `jevops-autoencoder` | `jevops.autoencoder` |
| `jevops-graph` | `jevops.graph` |
| `jevops-temporal` | `jevops.temporal` |
| `jevops-turing` | `jevops.turing` / `tape` / `tape_tools` |
| `jevops-plan` | `jevops.plan` |

## Consumers

Lean Refactor Arena harness re-exports these as `nca_kernel`, `nca_plan`, `typesafe_nca` cell helpers, etc.
Set `JEVOPS_CAS_DIR` for L2 CAS (LRA sets it to `evidence/canaries/nca-cas`).

Register implementation hooks instead of importing paper modules from the kernel:

```python
from jevops import hooks
hooks.register("load_board", my_board_loader)
hooks.register("token_count", my_token_count)
```

If hooks are missing, the kernel `try_import`s consumer modules that happen to be on `PYTHONPATH` (LRA harness). Missing hooks fail closed.

## Not in this package

Portable Lean folds, `lake env`, random canaries, TypeSafe Jev HTTP, Track 1/2,
LRA `tasks.json` board, harness file walking, inner TypeSafe lake walker.
