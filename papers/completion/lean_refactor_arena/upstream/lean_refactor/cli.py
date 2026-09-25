import os

os.environ["TQDM_DISABLE"] = "1"
import json
import logging
import multiprocessing as mp
import signal
import time
import traceback
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from lean_refactor.agents.util.common import TokenTracker
from lean_refactor.util.verifier_lean_client import LeanClientScheduler
from lean_refactor.utils import (
    extract_doc_string,
    is_tactic_style_proof,
    proof_length,
    remove_initial_comments_and_attr,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Suppress noisy third-party loggers
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("anthropic").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("vllm").setLevel(logging.WARNING)
logging.getLogger("swift").setLevel(logging.WARNING)

app = typer.Typer()

DEFAULT_LEAN_WORKSPACE_PATH = str(Path(__file__).parent / "mathlib4")


@app.callback()
def callback():
    """
    Lean Refactor System.
    """
    pass


console = Console()


# =============================================================================
# Planner Optimizer Workflow Utilities
# =============================================================================


def _format_dependencies_for_prompt(contexts: list[dict]) -> str:
    """
    Format context dependencies for the optimizer prompt.

    Args:
        contexts: List of context dictionaries with name, kind, signature, and src fields

    Returns:
        Formatted dependency string for prompt
    """
    if not contexts:
        return ""

    formatted_parts = []
    for idx, context in enumerate(contexts, start=1):
        name = context.get("name", "Unknown")
        kind = context.get("kind", "")
        signature = context.get("signature", "")
        src = context.get("src", "")

        # Format based on kind
        dependency_str = f"Dependency {idx}:\n**full name**: {name}\n**signature**: {signature}"

        # If not a theorem, include source code
        if kind != "theorem":
            dependency_str += f"\n**source code**: {remove_initial_comments_and_attr(src)}"

        formatted_parts.append(dependency_str)

    return "\n\n".join(formatted_parts)


# =============================================================================
# Shared Parallel Processing Utilities
# =============================================================================


def _result_writer(
    result_queue: Any,  # mp.Queue[dict | None]
    output_path: Path,
    total_count: int,
    stop_event: Any,  # mp.Event
) -> None:
    """
    Writer process that collects results and writes them to the output JSONL file.

    Stops when:
    1. Receives exactly total_count results, OR
    2. Receives None sentinel value (signals all workers done), OR
    3. stop_event is set (graceful shutdown requested)

    Args:
        result_queue: Queue containing result dicts or None as sentinel
        output_path: Path to the output JSONL file
        total_count: Total number of theorems to process
        stop_event: Event to signal graceful shutdown
    """
    import queue as queue_module  # For queue.Empty exception

    # Ignore SIGINT in writer process - let main process handle it
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    written_count = 0
    success_count = 0
    error_count = 0
    skip_count = 0
    total_reduction = 0
    total_reduction_percentage = 0.0

    try:
        with output_path.open("a", encoding="utf-8") as f:
            while written_count < total_count and not stop_event.is_set():
                try:
                    # Use timeout to allow checking stop_event periodically
                    result_dict = result_queue.get(timeout=1.0)
                except queue_module.Empty:
                    continue

                if result_dict is None:
                    # Sentinel value - early shutdown requested
                    print(
                        f"[Writer] Received completion signal. Processed {written_count}/{total_count} results.",
                        flush=True,
                    )
                    break

                # Write result to JSONL file and flush immediately
                f.write(json.dumps(result_dict, ensure_ascii=False) + "\n")
                f.flush()

                written_count += 1

                # Track statistics
                if result_dict.get("skipped"):
                    skip_count += 1
                elif result_dict.get("error"):
                    error_count += 1
                else:
                    success_count += 1
                    orig = result_dict.get("original_proof_length", 0)
                    opt = result_dict.get("optimized_proof_length", 0)
                    total_reduction += orig - opt
                    total_reduction_percentage += result_dict.get("reduction_percentage", 0)

                # Print token usage for this result
                name = result_dict.get("name", "unknown")
                token_usage = result_dict.get("token_usage", {})
                if token_usage:
                    total_input = token_usage.get("total_input_tokens", 0)
                    total_output = token_usage.get("total_output_tokens", 0)
                    total_tokens = token_usage.get("total_tokens", 0)
                    print(
                        f"[Writer] ({written_count}/{total_count}) {name}: "
                        f"tokens={total_tokens:,} (in={total_input:,}, out={total_output:,})",
                        flush=True,
                    )
                else:
                    print(f"[Writer] ({written_count}/{total_count}) {name}", flush=True)

    except Exception as e:
        print(f"[Writer] Fatal error: {e}", flush=True)
        traceback.print_exc()
        raise

    # Print final summary
    print("\n\n\n[Writer] ═══════════════════════════════════════════════════════", flush=True)
    print(f"[Writer] Summary: {success_count} succeeded, {error_count} failed, {skip_count} skipped", flush=True)
    if success_count > 0:
        avg_reduction = total_reduction / success_count
        avg_reduction_pct = total_reduction_percentage / success_count
        print(f"[Writer] Total reduction: {total_reduction} tokens (avg: {avg_reduction:.1f} per theorem)", flush=True)
        print(f"[Writer] Avg reduction percentage: {avg_reduction_pct:.2f}%", flush=True)
    print(f"[Writer] Results written to: {output_path}", flush=True)
    print("[Writer] ═══════════════════════════════════════════════════════\n\n\n", flush=True)


# =============================================================================
# Planner-Based Optimizer Workflow Functions
# =============================================================================


def _process_single_planner_theorem_optimization(
    theorem_data: dict[str, Any],
    scheduler: "LeanClientScheduler",
    config_params: dict[str, Any],
    debug: bool = False,
) -> dict[str, Any]:
    """
    Process a single theorem for planner optimization and return the result dict.

    This is the core processing logic extracted for use by parallel workers.
    """
    from lean_refactor.config.config import parsed_config
    from lean_refactor.config.llm import _create_anthropic_llm, _create_gemini_llm, _create_vllm_openai_llm
    from lean_refactor.planner_optimizer_framework import (
        PlannerOptimizerConfig,
        PlannerOptimizerFramework,
    )
    from lean_refactor.planner_optimizer_state import (
        PlannerOptimizerState,
        PlannerOptimizerStateManager,
    )
    start_time = time.time()

    # Extract fields from theorem_data
    name = theorem_data.get("name")
    src = theorem_data.get("src")
    relative_path = theorem_data.get("path")
    signature = theorem_data.get("signature")
    contexts = theorem_data.get("contexts", [])
    initial_length = theorem_data.get("proof_length")
    header = theorem_data.get("header")

    # Validate required fields
    if not name or not src or not relative_path or not signature:
        return {
            "name": name or "unknown",
            "error": "Missing required fields (name, src, path, signature)",
            "skipped": True,
        }

    try:
        # Clean up signature if present
        clean_signature = None
        if signature:
            clean_signature = remove_initial_comments_and_attr(signature)

        # Extract doc string from src
        doc_string = extract_doc_string(src)

        cleaned_proof = remove_initial_comments_and_attr(src)

        # Pre-filter: skip non-tactic-style proofs when --use-tactic-style is enabled
        use_tactic_style = config_params.get("use_tactic_style", False)
        if use_tactic_style and not is_tactic_style_proof(cleaned_proof):
            print(
                f"[WARNING] Skipping '{name}': proof is not in tactic-style "
                f"(does not start with ':= by'). Use --use-tactic-style only with tactic-mode proofs.",
                flush=True,
            )
            return {
                "name": name,
                "path": relative_path,
                "skipped": True,
                "skip_reason": "Proof is not in tactic-style (does not start with ':= by')",
            }

        # Format dependencies
        formatted_deps = None
        if contexts:
            formatted_deps = _format_dependencies_for_prompt(contexts)

        # Extract config parameters
        budget = config_params["api_budget"]
        max_correction_attempts = config_params["max_correction_attempts"]
        max_replans = config_params["max_replans"]
        min_replans = config_params.get("min_replans", 1)
        max_results_per_query = config_params["max_results_per_query"]
        retrieval_server_url = config_params["retrieval_server_url"]
        lean_workspace_path = config_params["lean_workspace_path"]
        lean_max_concurrent_workers = config_params["lean_max_concurrent_workers"]
        lean_timeout = config_params["lean_timeout"]
        max_correction_attempts_high = config_params.get("max_correction_attempts_high")
        max_correction_attempts_medium = config_params.get("max_correction_attempts_medium")
        max_correction_attempts_low = config_params.get("max_correction_attempts_low")
        init_optim = config_params.get("init_optim", False)
        compiler = config_params.get("compiler", "lean_client")
        use_tactic_style = config_params.get("use_tactic_style", False)

        # Create planner optimizer state
        initial_state = PlannerOptimizerState(
            proof=cleaned_proof,
            api_budget=budget,
            relative_path=relative_path,
            signature=clean_signature,
            doc_string=doc_string,
            dependencies=formatted_deps,
            initial_proof_length=initial_length,
            max_correction_attempts=max_correction_attempts,
            max_replans=max_replans,
            min_replans=min_replans,
            max_correction_attempts_high=max_correction_attempts_high,
            max_correction_attempts_medium=max_correction_attempts_medium,
            max_correction_attempts_low=max_correction_attempts_low,
            init_optim=init_optim,
            header=header,
            use_tactic_style=use_tactic_style,
        )
        state_manager = PlannerOptimizerStateManager(state=initial_state)

        # Create fresh LLM instances for worker process
        planner_provider = parsed_config.get(section="PLANNER_AGENT_LLM", option="provider", fallback="gemini")
        if planner_provider == "vllm":
            print("Using vllm for planner agent", flush=True)
            planner_agent_llm = _create_vllm_openai_llm(section="PLANNER_AGENT_LLM")
        elif planner_provider == "anthropic":
            print("Using anthropic for planner agent", flush=True)
            planner_agent_llm = _create_anthropic_llm(
                section="PLANNER_AGENT_LLM",
                max_retries=parsed_config.getint(section="PLANNER_AGENT_LLM", option="max_remote_retries", fallback=5),
            )
        else:
            print("Using gemini for planner agent", flush=True)
            planner_agent_llm = _create_gemini_llm(
                section="PLANNER_AGENT_LLM",
                max_retries=parsed_config.getint(section="PLANNER_AGENT_LLM", option="max_remote_retries", fallback=5),
            )

        finder_provider = parsed_config.get(section="FINDER_AGENT_LLM", option="provider", fallback="gemini")
        if finder_provider == "vllm":
            finder_agent_llm = _create_vllm_openai_llm(section="FINDER_AGENT_LLM")
        elif finder_provider == "anthropic":
            finder_agent_llm = _create_anthropic_llm(
                section="FINDER_AGENT_LLM",
                max_retries=parsed_config.getint(section="FINDER_AGENT_LLM", option="max_remote_retries", fallback=5),
            )
        else:
            finder_agent_llm = _create_gemini_llm(
                section="FINDER_AGENT_LLM",
                max_retries=parsed_config.getint(section="FINDER_AGENT_LLM", option="max_remote_retries", fallback=5),
            )

        executer_provider = parsed_config.get(section="EXECUTER_AGENT_LLM", option="provider", fallback="gemini")
        if executer_provider == "vllm":
            print("Using vllm for executer agent", flush=True)
            executer_agent_llm = _create_vllm_openai_llm(section="EXECUTER_AGENT_LLM")
        elif executer_provider == "anthropic":
            print("Using anthropic for executer agent", flush=True)
            executer_agent_llm = _create_anthropic_llm(
                section="EXECUTER_AGENT_LLM",
                max_retries=parsed_config.getint(section="EXECUTER_AGENT_LLM", option="max_remote_retries", fallback=5),
            )
        else:
            print("Using gemini for executer agent", flush=True)
            executer_agent_llm = _create_gemini_llm(
                section="EXECUTER_AGENT_LLM",
                max_retries=parsed_config.getint(section="EXECUTER_AGENT_LLM", option="max_remote_retries", fallback=5),
            )

        config = PlannerOptimizerConfig(
            planner_agent_llm=planner_agent_llm,
            finder_agent_llm=finder_agent_llm,
            executer_agent_llm=executer_agent_llm,
            initial_optimizer_agent_llm=executer_agent_llm,
            retrieval_server_url=retrieval_server_url,
            lean_workspace_path=lean_workspace_path,
            lean_max_concurrent_workers=lean_max_concurrent_workers,
            lean_timeout=lean_timeout,
            max_correction_attempts=max_correction_attempts,
            max_replans=max_replans,
            api_budget=budget,
            max_results_per_query=max_results_per_query,
            max_correction_attempts_high=max_correction_attempts_high,
            max_correction_attempts_medium=max_correction_attempts_medium,
            max_correction_attempts_low=max_correction_attempts_low,
            init_optim=init_optim,
            compiler=compiler,
            use_tactic_style=use_tactic_style,
        )

        # Create token tracker for this theorem
        token_tracker = TokenTracker()

        # Use a simple Console that writes to devnull for worker processes
        worker_console = Console(force_terminal=False, quiet=True)  # Console(width=220, force_terminal=True)

        framework = PlannerOptimizerFramework(
            config,
            state_manager,
            worker_console,
            lean_scheduler=scheduler,
            token_tracker=token_tracker,
            debug_print_queues=debug,
        )

        framework.run()

        elapsed_time = time.time() - start_time

        # Collect results
        complete_proof, shortest_length = state_manager.get_final_result()
        # Calculate original length if not provided
        original_length = initial_length if initial_length else proof_length(cleaned_proof)

        result_record = {
            "name": name,
            "path": relative_path,
            "original_proof_length": original_length,
            "optimized_proof_length": shortest_length,
            "reduction_percentage": round((1 - shortest_length / original_length) * 100, 2)
            if original_length > 0
            else 0,
            "original_proof": cleaned_proof,
            "proof": complete_proof,
        }

        return result_record

    except Exception as e:
        elapsed_time = time.time() - start_time
        return {
            "name": name,
            "path": relative_path,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "elapsed_time": elapsed_time,
        }


def _process_single_planner_task(
    theorem_data: dict[str, Any],
    idx: int,
    scheduler: "LeanClientScheduler",
    config_params: dict[str, Any],
    result_queue: Any,  # mp.Queue
    debug: bool = False,
) -> None:
    """
    Process a single theorem (planner mode) and put the result in the queue.
    """
    name = theorem_data.get("name", "unknown")
    print(f"[Process {idx}] Processing theorem: {name}", flush=True)

    result = _process_single_planner_theorem_optimization(
        theorem_data=theorem_data,
        scheduler=scheduler,
        config_params=config_params,
        debug=debug,
    )

    result_queue.put(result)

    # Log completion
    if "error" in result:
        print(
            f"[Process {idx}] Failed: {name} - {result.get('error', 'unknown error')[:100]}",
            flush=True,
        )
    else:
        orig = result.get("original_proof_length", 0)
        opt = result.get("optimized_proof_length", 0)
        print(f"[Process {idx}] Completed: {name} ({orig} → {opt} tokens)", flush=True)


def _post_process_optimized_proofs(
    output_jsonl_path: Path,
    lean_workspace_path: str,
) -> None:
    """
    Post-process optimized proofs by creating a new Lean project with swapped proofs.

    Steps:
    1. Copy lean_workspace_path to lean_workspace_path_optimized
    2. For each result in output JSONL:
       - Replace original_proof with optimized_proof in the file
       - Rename file to include "_optimized" suffix
    3. Update LeanProject.lean imports
    4. Build project file-by-file, tracking failures
    5. Print summary

    Args:
        output_jsonl_path: Path to the JSONL file containing optimization results
        lean_workspace_path: Path to the original Lean workspace directory
    """
    import re
    import shutil
    import subprocess

    workspace_path = Path(lean_workspace_path)
    optimized_workspace_path = Path(f"{lean_workspace_path}_optimized")

    console.print("\n[bold blue]Starting post-processing of optimized proofs...[/bold blue]")

    # Step 1: Copy workspace to new directory
    console.print(f"[bold blue]Copying workspace to {optimized_workspace_path}...[/bold blue]")
    if optimized_workspace_path.exists():
        shutil.rmtree(optimized_workspace_path)
    shutil.copytree(workspace_path, optimized_workspace_path)
    console.print("[bold green]✓ Workspace copied successfully[/bold green]")

    # Step 2 & 3: Read JSONL and swap proofs, rename files
    console.print(f"[bold blue]Processing optimization results from {output_jsonl_path}...[/bold blue]")

    renamed_files: dict[str, str] = {}  # Maps old module name to new module name
    processed_count = 0
    error_count = 0

    # Collect all replacements per file first (to handle multiple theorems per file)
    file_replacements: dict[str, list[tuple[str, str]]] = {}  # path -> [(original, optimized), ...]

    with output_jsonl_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                result = json.loads(line)
            except json.JSONDecodeError as e:
                console.print(f"[bold yellow]Warning: Malformed JSON at line {line_num}: {e}[/bold yellow]")
                error_count += 1
                continue

            # Skip entries with errors or that were skipped
            if result.get("error") or result.get("skipped"):
                continue

            relative_path = result.get("path")
            original_proof = result.get("original_proof")
            optimized_proof = result.get("optimized_proof")

            # Fallback: use 'src' field if original_proof/optimized_proof not present (for testing)
            if not original_proof and result.get("src"):
                original_proof = result.get("src")
            if not optimized_proof and result.get("src"):
                optimized_proof = result.get("src")

            if not relative_path or not original_proof or not optimized_proof:
                console.print(f"[bold yellow]Warning: Missing required fields at line {line_num}[/bold yellow]")
                error_count += 1
                continue

            # Collect replacement for this file
            if relative_path not in file_replacements:
                file_replacements[relative_path] = []
            file_replacements[relative_path].append((original_proof, optimized_proof))

    # Now apply all replacements for each file and rename once
    for relative_path, replacements in file_replacements.items():
        file_path = optimized_workspace_path / relative_path

        if not file_path.exists():
            console.print(f"[bold yellow]Warning: File not found: {file_path}[/bold yellow]")
            error_count += len(replacements)
            continue

        try:
            # Read file content
            content = file_path.read_text(encoding="utf-8")

            # Apply all replacements for this file
            replacements_applied = 0
            for original_proof, optimized_proof in replacements:
                if original_proof in content:
                    # This prevents merging theorems if the original capture included the separator
                    orig_ws = original_proof[len(original_proof.rstrip()) :]
                    opt_ws = optimized_proof[len(optimized_proof.rstrip()) :]

                    if orig_ws and not opt_ws:
                        optimized_proof += orig_ws
                    elif orig_ws and opt_ws and "\n" in orig_ws:
                        num_orig_nl = orig_ws.count("\n")
                        num_opt_nl = opt_ws.count("\n")
                        if num_orig_nl > num_opt_nl:
                            optimized_proof += "\n" * (num_orig_nl - num_opt_nl)

                    content = content.replace(original_proof, optimized_proof, 1)
                    replacements_applied += 1
                else:
                    console.print(f"[bold yellow]Warning: Original proof not found in {file_path}[/bold yellow]")
                    error_count += 1

            # Write the modified content back
            file_path.write_text(content, encoding="utf-8")

            # Rename file to include "_optimized" suffix (only once per file)
            # e.g., LeanProject/problem1.lean -> LeanProject/problem1_optimized.lean
            stem = file_path.stem  # e.g., "problem1"
            new_name = f"{stem}_optimized{file_path.suffix}"  # e.g., "problem1_optimized.lean"
            new_file_path = file_path.parent / new_name

            file_path.rename(new_file_path)

            # Track for import updates
            # Extract module name from relative path (e.g., "LeanProject/problem1.lean" -> "LeanProject.problem1")
            old_module = relative_path.replace("/", ".").replace(".lean", "")
            new_module = f"{old_module}_optimized"
            renamed_files[old_module] = new_module

            processed_count += replacements_applied
            console.print(f"[dim]  Processed: {relative_path} -> {new_name} ({replacements_applied} theorem(s))[/dim]")

        except Exception as e:
            console.print(f"[bold red]Error processing {file_path}: {e}[/bold red]")
            error_count += len(replacements)
            continue

    console.print(
        f"[bold green]✓ Processed {processed_count} theorems in {len(file_replacements)} files, {error_count} errors[/bold green]"
    )

    # Step 4: Update LeanProject.lean imports
    lean_project_file = optimized_workspace_path / "LeanProject.lean"
    if lean_project_file.exists():
        console.print("[bold blue]Updating imports in LeanProject.lean...[/bold blue]")
        try:
            content = lean_project_file.read_text(encoding="utf-8")

            # Replace each import statement
            for old_module, new_module in renamed_files.items():
                # Match "import LeanProject.problem1" and replace with "import LeanProject.problem1_optimized"
                pattern = rf"import\s+{re.escape(old_module)}\b"
                replacement = f"import {new_module}"
                content = re.sub(pattern, replacement, content)

            lean_project_file.write_text(content, encoding="utf-8")
            console.print(f"[bold green]✓ Updated {len(renamed_files)} import statements[/bold green]")
        except Exception as e:
            console.print(f"[bold red]Error updating LeanProject.lean: {e}[/bold red]")
    else:
        console.print(f"[bold yellow]Warning: LeanProject.lean not found at {lean_project_file}[/bold yellow]")

    # Step 5: Run lake update and build
    cwd = str(optimized_workspace_path)

    # Clean lake artifacts
    console.print("[bold blue]Cleaning lake artifacts...[/bold blue]")
    for artifact in [".lake", "lake-packages", "lake-manifest.json"]:
        artifact_path = optimized_workspace_path / artifact
        if artifact_path.exists():
            if artifact_path.is_dir():
                shutil.rmtree(artifact_path)
            else:
                artifact_path.unlink()

    # Run lake update
    console.print("[bold blue]Running lake update...[/bold blue]")
    try:
        subprocess.run(["lake", "update"], cwd=cwd, check=True, capture_output=True, text=True)
        console.print("[bold green]✓ lake update completed[/bold green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]Error running lake update: {e.stderr}[/bold red]")
        return

    # Try to get mathlib cache (may fail if not using mathlib)
    console.print("[bold blue]Running lake exe cache get...[/bold blue]")
    try:
        subprocess.run(["lake", "exe", "cache", "get"], cwd=cwd, check=True, capture_output=True, text=True)
        console.print("[bold green]✓ lake exe cache get completed[/bold green]")
    except subprocess.CalledProcessError:
        console.print(
            "[bold yellow]'lake exe cache get' failed (mathlib may not be a dependency). Continuing...[/bold yellow]"
        )

    # Build each file individually
    console.print("[bold blue]Building files individually...[/bold blue]")
    lean_project_dir = optimized_workspace_path / "LeanProject"

    if not lean_project_dir.exists():
        console.print(f"[bold red]Error: LeanProject directory not found at {lean_project_dir}[/bold red]")
        return

    lean_files = list(lean_project_dir.glob("*.lean"))
    build_results: dict[str, bool] = {}
    build_errors: dict[str, str] = {}

    for lean_file in lean_files:
        file_name = lean_file.name
        # Convert file path to module path for lake build
        # e.g., "problem1_optimized.lean" -> "LeanProject.problem1_optimized"
        module_name = f"LeanProject.{lean_file.stem}"

        console.print(f"[dim]  Building: {module_name}...[/dim]", end=" ")
        try:
            result = subprocess.run(
                ["lake", "build", module_name],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout per file
            )
            if result.returncode == 0:
                build_results[file_name] = True
                console.print("[bold green]✓[/bold green]")
            else:
                build_results[file_name] = False
                build_errors[file_name] = result.stderr
                console.print("[bold red]✗[/bold red]")
        except subprocess.TimeoutExpired:
            build_results[file_name] = False
            build_errors[file_name] = "Build timed out (5 minutes)"
            console.print("[bold red]✗ (timeout)[/bold red]")
        except Exception as e:
            build_results[file_name] = False
            build_errors[file_name] = str(e)
            console.print("[bold red]✗ (error)[/bold red]")

    # Step 6: Print summary
    success_files = [f for f, success in build_results.items() if success]
    failed_files = [f for f, success in build_results.items() if not success]

    console.print("\n[bold blue]═══════════════════════════════════════════════════════[/bold blue]")
    console.print("[bold blue]Build Summary[/bold blue]")
    console.print("[bold blue]═══════════════════════════════════════════════════════[/bold blue]")
    console.print(f"[bold green]Succeeded: {len(success_files)}/{len(build_results)}[/bold green]")
    console.print(f"[bold red]Failed: {len(failed_files)}/{len(build_results)}[/bold red]")

    if success_files:
        console.print("\n[bold green]Successful builds:[/bold green]")
        for f in success_files:
            console.print(f"  [green]✓ {f}[/green]")

    if failed_files:
        console.print("\n[bold red]Failed builds:[/bold red]")
        for f in failed_files:
            console.print(f"  [red]✗ {f}[/red]")
            if f in build_errors:
                # Print first few lines of error
                error_lines = build_errors[f].strip().split("\n")[:5]
                for line in error_lines:
                    console.print(f"    [dim]{line}[/dim]")

    console.print(f"\n[bold blue]Optimized project created at: {optimized_workspace_path}[/bold blue]")
    console.print("[bold blue]═══════════════════════════════════════════════════════[/bold blue]")
    console.print("ENDED, use ctrl+c to exit")


def process_planner_optimizations_from_jsonl_parallel(
    jsonl_file: Path,
    api_budget: int | None = None,
    output_path: Path | None = None,
    num_workers: int = 20,
    debug: bool = False,
    lean_workspace_path: str | None = None,
    init_optim: bool = False,
    compiler: str = "lean_client",
    use_tactic_style: bool = False,
    create_optimized_project: bool = False,
) -> None:
    """
    Process all theorems from a JSONL file for planner-based optimization in parallel.
    """
    from lean_refactor.config.lean_client_server import LEAN_CLIENT_SERVER
    from lean_refactor.config.llm import (
        MATHLIB_RETRIEVAL_SERVER_URL,
        PLANNER_API_BUDGET,
        PLANNER_MAX_CORRECTION_ATTEMPTS,
        PLANNER_MAX_CORRECTION_ATTEMPTS_HIGH,
        PLANNER_MAX_CORRECTION_ATTEMPTS_LOW,
        PLANNER_MAX_CORRECTION_ATTEMPTS_MEDIUM,
        PLANNER_MAX_REPLANS,
        PLANNER_MAX_RESULTS_PER_QUERY,
        PLANNER_MIN_REPLANS,
    )

    print("Running planner optimizations from JSONL file in parallel...")

    if not jsonl_file.exists():
        console.print(f"[bold red]Error:[/bold red] File {jsonl_file} does not exist")
        raise typer.Exit(code=1)

    # Use provided budget or config default
    budget = api_budget if api_budget is not None else PLANNER_API_BUDGET

    # Read and parse JSONL file
    theorems: list[dict[str, Any]] = []
    error_count = 0

    with jsonl_file.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                theorem_data = json.loads(line)
                theorems.append(theorem_data)
            except json.JSONDecodeError as e:
                error_count += 1
                console.print(f"[bold yellow]Warning:[/bold yellow] Malformed JSON at line {line_num}: {e}")
                continue

    if error_count > 0:
        console.print(f"[bold yellow]Skipped {error_count} malformed JSON line(s)[/bold yellow]")

    if not theorems:
        console.print(f"[bold yellow]Warning:[/bold yellow] No valid theorems found in {jsonl_file}")
        return

    console.print(f"[bold blue]Found {len(theorems)} theorem(s) in input file (planner mode)[/bold blue]")

    # Determine output path for results
    if output_path is None:
        output_path = jsonl_file.parent / "planner_optimization_results.jsonl"

    # Check for already-completed tasks (resume support)
    completed_tasks: set[tuple[str, str]] = set()
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    result = json.loads(line)
                    # Use (name, path) as unique identifier
                    name = result.get("name")
                    path = result.get("path")
                    if name and path:
                        completed_tasks.add((name, path))
                except json.JSONDecodeError:
                    continue
        if completed_tasks:
            console.print(
                f"[bold blue]Found {len(completed_tasks)} already-completed task(s) in output file[/bold blue]"
            )

    # Filter out already-completed theorems
    tasks_to_process = []
    for theorem_data in theorems:
        name = theorem_data.get("name")
        path = theorem_data.get("path")
        if name and path and (name, path) in completed_tasks:
            continue
        tasks_to_process.append(theorem_data)

    if not tasks_to_process:
        console.print("[bold green]All theorems already processed![/bold green]")
        return

    console.print(
        f"[bold blue]Tasks to process: {len(tasks_to_process)} (skipping {len(theorems) - len(tasks_to_process)} completed)[/bold blue]"
    )
    console.print(f"[bold blue]Max concurrent processes: {num_workers}[/bold blue]")
    console.print(f"[bold blue]Results will be written to: {output_path}[/bold blue]")

    workspace_path = lean_workspace_path

    # Limit Lean workers to num_workers to prevent excessive memory usage
    lean_workers = min(LEAN_CLIENT_SERVER["max_concurrent_workers"], num_workers)

    # Prepare config parameters
    config_params = {
        "api_budget": budget,
        "max_correction_attempts": PLANNER_MAX_CORRECTION_ATTEMPTS,
        "max_replans": PLANNER_MAX_REPLANS,
        "min_replans": PLANNER_MIN_REPLANS,
        "max_results_per_query": PLANNER_MAX_RESULTS_PER_QUERY,
        "retrieval_server_url": MATHLIB_RETRIEVAL_SERVER_URL,
        "lean_workspace_path": workspace_path,
        "lean_max_concurrent_workers": lean_workers,
        "lean_timeout": LEAN_CLIENT_SERVER["timeout"],
        "max_correction_attempts_high": PLANNER_MAX_CORRECTION_ATTEMPTS_HIGH,
        "max_correction_attempts_medium": PLANNER_MAX_CORRECTION_ATTEMPTS_MEDIUM,
        "max_correction_attempts_low": PLANNER_MAX_CORRECTION_ATTEMPTS_LOW,
        "init_optim": init_optim,
        "compiler": compiler,
        "use_tactic_style": use_tactic_style,
    }

    # Create shared LeanClientScheduler in main process
    if compiler == "repl":
        from lean_refactor.util.verifier_slow import Lean4ServerScheduler

        scheduler = Lean4ServerScheduler(
            lean_workspace=workspace_path,
            max_concurrent_requests=lean_workers,
            timeout=LEAN_CLIENT_SERVER["timeout"],
            memory_limit=10,
            name="verifier",
        )
    else:
        scheduler = LeanClientScheduler(
            workspace_path=workspace_path,
            max_concurrent_requests=lean_workers,
            timeout=LEAN_CLIENT_SERVER["timeout"],
        )

    # Create result queue and stop event
    result_queue = mp.Queue()
    stop_event = mp.Event()

    processes: list[mp.Process] = []
    writer: mp.Process | None = None

    try:
        # Start writer process first
        writer = mp.Process(
            target=_result_writer,
            args=(result_queue, output_path, len(tasks_to_process), stop_event),
            name="Writer",
        )
        writer.start()
        console.print("[bold blue]Started writer process[/bold blue]")

        # Process tasks with concurrency limit
        for idx, theorem_data in enumerate(tasks_to_process, start=1):
            # Wait until we have room for another process
            while len(processes) >= num_workers:
                # Clean up finished processes
                for p in list(processes):
                    if not p.is_alive():
                        p.join()
                        processes.remove(p)

                if len(processes) >= num_workers:
                    time.sleep(0.1)

            # Spawn a new process for this task
            p = mp.Process(
                target=_process_single_planner_task,
                args=(
                    theorem_data,
                    idx,
                    scheduler,
                    config_params,
                    result_queue,
                    debug,
                ),
                name=f"Planner-Task-{idx}",
            )
            p.start()
            processes.append(p)

        # Wait for all task processes to complete
        for p in processes:
            p.join()

        console.print("[bold blue]All task processes completed[/bold blue]")

        # Signal writer to finish and wait
        result_queue.put(None)
        writer.join(timeout=30)

        if writer.is_alive():
            console.print(
                "[bold yellow]Warning: Writer process did not terminate gracefully, forcing...[/bold yellow]"
            )
            writer.terminate()
            writer.join(timeout=5)

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Interrupted! Terminating all processes...[/bold yellow]")
        stop_event.set()

        # Terminate all task processes
        for p in processes:
            if p.is_alive():
                p.terminate()

        # Wait briefly for processes
        for p in processes:
            p.join(timeout=5)

        # Terminate writer
        if writer is not None and writer.is_alive():
            writer.terminate()
            writer.join(timeout=5)

    finally:
        # Close the shared scheduler
        scheduler.close()

        # Clean up any remaining processes
        for p in processes:
            if p.is_alive():
                p.kill()
        if writer is not None and writer.is_alive():
            writer.kill()

    console.print("\n[bold blue]Finished parallel planner optimization of all theorems from JSONL[/bold blue]")

    # Post-process: Create new Lean project with optimized proofs (only when requested)
    if create_optimized_project:
        _post_process_optimized_proofs(output_path, workspace_path)
    else:
        console.print(
            "[dim]Skipping optimized Lean project creation "
            "(pass --create-optimized-project to enable).[/dim]"
        )


@app.command()
def optimize(
    proof_file: Path | None = typer.Option(
        None,
        "--proof-file",
        "-pf",
        help="A single .lean file containing a proof to optimize",
    ),
    proof_directory: Path | None = typer.Option(
        None,
        "--proof-directory",
        "-pd",
        help="Directory containing .lean files with proofs to optimize",
    ),
    proof_jsonl: Path | None = typer.Option(
        None,
        "--proof-jsonl",
        "-pj",
        help="JSONL file containing theorems with metadata (name, src, signature, contexts) to optimize",
    ),
    api_budget: int | None = typer.Option(
        None,
        "--api-budget",
        "-ab",
        help="Maximum number of API calls allowed (overrides config default)",
    ),
    output_path: Path | None = typer.Option(
        None,
        "--output-path",
        "-o",
        help="Path for optimization results JSONL file (defaults to optimization_results.jsonl in input directory)",
    ),
    num_workers: int = typer.Option(
        1,
        "--num-workers",
        "-nw",
        help="Number of parallel worker processes for JSONL processing (default: 1 = sequential)",
    ),
    planner: bool = typer.Option(
        False,
        "--planner",
        "-p",
        help="Use the planner-based multi-agent optimizer (plan → find → execute) instead of the simple optimizer",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        "-d",
        help="Enable debug logging",
    ),
    lean_workspace_path: str | None = typer.Option(
        DEFAULT_LEAN_WORKSPACE_PATH,
        "--lean-workspace-path",
        "-lwp",
        help="Path to the Lean workspace directory",
    ),
    init_optim: bool = typer.Option(
        False,
        "--init-optim",
        "-io",
        help="Run initial direct optimization phase before planning",
    ),
    compiler: str = typer.Option(
        "lean_client",
        "--compiler",
        "-c",
        help="Compiler backend to use: 'lean_client' (default) or 'repl'",
    ),
    use_tactic_style: bool = typer.Option(
        False,
        "--keep-tactic-style",
        "-kts",
        help="Enforce tactic-mode proof style (:= by) in optimized proofs",
    ),
    create_optimized_project: bool = typer.Option(
        False,
        "--create-optimized-project",
        "-cop",
        help="After optimizing, copy the Lean workspace to <workspace>_optimized with the "
        "optimized proofs swapped in and re-verify each file via lake build",
    ),
) -> None:
    """
    Proof Optimizer: Iteratively optimize Lean 4 proofs to reduce their length.

    The optimizer will repeatedly attempt to shorten the proof until the API budget
    is exhausted, returning the shortest valid proof found.

    Provide one of: --proof-file for a single proof, --proof-directory for batch
    processing, or --proof-jsonl for processing theorems from a JSONL file with metadata.

    Use --planner/-p to enable the planner-based multi-agent workflow which:
    1. Plans optimization steps targeting specific proof regions
    2. Retrieves relevant Mathlib lemmas for each plan
    3. Executes optimizations step-by-step according to the plan

    Use --init-optim/-io with --planner to enable an initial direct optimization pass
    before entering the planning loop.

    Use --num-workers/-nw with --proof-jsonl to enable parallel processing with
    multiple worker processes. Each worker processes one theorem at a time and
    shares the Lean verification scheduler for efficiency.
    """
    # Configure debug logging if requested
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate num_workers
    if num_workers < 1:
        console.print("[bold red]Error:[/bold red] --num-workers must be at least 1")
        raise typer.Exit(code=1)

    # Count how many input options were provided
    options_provided = sum([
        proof_file is not None,
        proof_directory is not None,
        proof_jsonl is not None,
    ])

    # Ensure exactly one input option is provided
    if options_provided == 0:
        console.print("[bold red]Error:[/bold red] You must provide exactly one of the following options:")
        console.print("  --proof-file (-pf): A single .lean file to optimize")
        console.print("  --proof-directory (-pd): Directory of .lean files to optimize")
        console.print("  --proof-jsonl (-pj): JSONL file with theorem metadata to optimize")
        raise typer.Exit(code=1)

    if options_provided > 1:
        console.print("[bold red]Error:[/bold red] Only one input option can be provided at a time")
        raise typer.Exit(code=1)

    # Check for unsupported planner mode with proof_directory
    if planner and proof_directory:
        console.print(
            "[bold yellow]Warning:[/bold yellow] Planner mode with --proof-directory is not yet supported. "
            "Using simple optimizer instead."
        )
        planner = False

    # Check for unsupported parallel mode combinations
    if num_workers > 1 and not proof_jsonl:
        console.print(
            "[bold yellow]Warning:[/bold yellow] --num-workers only applies to --proof-jsonl. "
            "Ignoring --num-workers for single file/directory processing."
        )
        num_workers = 1

    if proof_jsonl:
        if output_path:
            os.makedirs(output_path.parent, exist_ok=True)
        else:
            raise Exception("No output path provided")
        process_planner_optimizations_from_jsonl_parallel(
            proof_jsonl,
            api_budget=api_budget,
            output_path=output_path,
            num_workers=num_workers,
            debug=debug,
            lean_workspace_path=lean_workspace_path,
            init_optim=init_optim,
            compiler=compiler,
            use_tactic_style=use_tactic_style,
            create_optimized_project=create_optimized_project,
        )
    else:
        raise Exception("No valid input proof option provided: only support --proof-jsonl for now")


if __name__ == "__main__":
    app()
