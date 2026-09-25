<div align="center">

# Lean Refactor

[![Website](https://img.shields.io/badge/Homepage-LeanRefactor-536af5?color=536af5&logoColor=white)](https://leanrefactor.github.io/)
[![Arena](https://img.shields.io/badge/HuggingFace-Arena-yellow?logo=huggingface)](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena)
[![arXiv](https://img.shields.io/badge/arXiv-2605.20244-b31b1b.svg?style=flat)](https://arxiv.org/abs/2605.20244)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

</div>

Lean Refactor is a multi-agent system that automatically refactors and shortens Lean 4 proofs while keeping them correct. You can run against your own Lean code.

---

## 1. Setup

### 1.1 Clone the repository

```bash
git clone --recurse-submodules git@github.com:delta-lab-ai/lean-refactor.git
cd lean-refactor
```

### 1.2 Build the Python environment

Make sure `uv` is installed, then:

```bash
make install
source .venv/bin/activate
```

### 1.3 Build Mathlib

A Mathlib checkout is bundled at `lean_refactor/mathlib4` and is used as the default Lean workspace:

```bash
cd lean_refactor/mathlib4
lake exe cache get   # download prebuilt Mathlib artifacts
lake build
cd ../..
```

### 1.4 Set your API key

```bash
export ANTHROPIC_API_KEY=...   # your Anthropic API key
export GOOGLE_API_KEY=...      # or your gemini api key
export OPENAI_API_KEY=...      # or your openai api key
```

---

## 2. Running the Lean Refactor Arena Dataset

### 2.1 Download the data

Download from the Lean Refactor Arena Huggingface space:

**https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena**

It is a single `.jsonl` file. Save it anywhere convenient, for example to benchmarks/lean-refactor-arena.jsonl

### 2.2 Configure settings

Edit `lean_refactor/data/config.ini`:

* **`[PLANNER_AGENT_LLM] -> model`** and **`[EXECUTER_AGENT_LLM] -> model`**: the models used for optimization. Most of Anthropic/Gemini/Openai model works, e.g. `claude-opus-4-6`, `gemini-3-flash-preview`.
* **`[PLANNER_AGENT_LLM] -> api_budget`**: maximum API calls allowed per problem (default `30`).
* **`[LEAN_CLIENT_SERVER] -> max_concurrent_workers`**: maximum parallel Lean compiler processes.

### 2.3 Run the agent

The benchmark proofs are verified against the bundled Mathlib workspace, which is the default — so you don't need to pass `--lean-workspace-path`.

```bash
lean-refactor optimize \
  --planner \
  --proof-jsonl benchmarks/lean-refactor-arena.jsonl \
  --output-path benchmarks/out/results.jsonl \
  --num-workers 5
```

* `--output-path`: where optimized proofs and metadata are written.
* `--num-workers`: number of problems to optimize in parallel.
* `--keep-tactic-style` (optional): keep optimized proofs in tactic style. When set, only tactic-style proofs (those starting with `:= by`) are optimized.

### 2.4 Output and submission

The results are written to the file you passed to `--output-path` (`benchmarks/out/results.jsonl` above). Each line contains the optimized proof and metadata. At the end of the run you'll see a summary like:

```text
[Writer] ═══════════════════════════════════════════════════════
[Writer] Summary: 10 succeeded, 0 failed, 0 skipped
[Writer] Total reduction: 755 tokens (avg: 75.5 per theorem)
[Writer] Avg reduction percentage: 87.36%
[Writer] Results written to: benchmarks/out/results.jsonl
[Writer] ═══════════════════════════════════════════════════════
```

**Submit** the output `.jsonl` file to the Lean Refactor Arena space to record your results:
**https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena**

---

## 3. Optimizing Your Own Repositories

To optimize proofs from your own code, the following scripts will first extract them into a self-contained Lean project, then run the optimizer against that project.

### 3.1 Extract proofs

The extractor takes a directory of self-contained `.lean` files and packages them into a Lean project.

> **Note:** All theorem and definition names must be unique across all input files.

```bash
cd data_extraction

python scripts/extract_repos.py \
  --cwd "$(pwd)" \
  --lean_files_input_mode \
  --input <INPUT_LEAN_FILES_DIR> \
  --output <EXTRACTED_PROJECT_DIR> \
  --premises \
  --declarations
```

* `<INPUT_LEAN_FILES_DIR>`: absolute path to the directory containing your `.lean` files.
* `<EXTRACTED_PROJECT_DIR>`: absolute path where the packaged Lean project will be created.

Example:

```bash
cd data_extraction

python scripts/extract_repos.py \
  --cwd "$(pwd)" \
  --lean_files_input_mode \
  --input /path/to/lean_files \
  --output /path/to/example_project \
  --premises \
  --declarations
```

### 3.2 Run the optimizer

Point `--proof-jsonl` at the extracted eval file and `--lean-workspace-path` at the extracted project. Both paths are produced by the extraction step.

```bash
cd $(git rev-parse --show-toplevel)

lean-refactor optimize \
  --planner \
  --proof-jsonl <EXTRACTED_PROJECT_DIR>/eval/eval_<PROJECT_NAME>.jsonl \
  --output-path <OUTPUT_RESULTS_JSONL> \
  --lean-workspace-path <EXTRACTED_PROJECT_DIR> \
  --create-optimized-project \
  --num-workers <NUM_WORKERS> 2>&1 | tee <LOG_FILE_PATH>
```

* `--create-optimized-project` (optional): after optimizing, write a full copy of the project at `<EXTRACTED_PROJECT_DIR>_optimized` with the optimized proofs swapped in. Omit it if you only need the results JSONL.

Example:

```bash
cd $(git rev-parse --show-toplevel)

lean-refactor optimize \
  --planner \
  --proof-jsonl /path/to/example_project/eval/eval_example_project.jsonl \
  --output-path /path/to/example_project/eval/out/results.jsonl \
  --lean-workspace-path /path/to/example_project \
  --create-optimized-project \
  --num-workers 20 2>&1 | tee /path/to/example_project/eval/out.log
```

### 3.3 Outputs

1. **JSONL results** (always): a detailed file at your `--output-path` containing the optimized proofs and metadata.
2. **Optimized Lean project** (only with `--create-optimized-project`): a new directory at `<EXTRACTED_PROJECT_DIR>_optimized` containing the actual `.lean` files with optimized proofs. Each file is re-verified with `lake build` to confirm correctness. Without the flag, no copy is made and only the results JSONL is written.
