"""
Debug printing utilities for the planner-based proof optimization workflow.

This module provides self-contained functions for printing queue contents
and PlannerOptimizedProofState with all nested types in a clear, formatted way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import AnyMessage
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

if TYPE_CHECKING:
    from lean_refactor.agents.state import (
        CompiledProofRecord,
        OptimizationPlan,
        OptimizedProofState,
        PlannerOptimizedProofState,
        RetrievedLemma,
    )
    from lean_refactor.optimizer_state import OptimizerState
    from lean_refactor.planner_optimizer_state import PlannerOptimizerState


# Status color mapping for OptimizationPlan status
STATUS_COLORS: dict[str, str] = {
    "pending": "dim",
    "in_progress": "yellow",
    "completed": "green",
    "failed": "red",
    "skipped": "dim cyan",
}

# Reduction level color mapping
REDUCTION_COLORS: dict[str, str] = {
    "high": "green",
    "medium": "yellow",
    "low": "dim",
}


def truncate_text(text: str | None, max_length: int = 1000) -> str:
    """
    Truncate text to a maximum length with ellipsis.

    This function is safe for any max_length value - Python's string slicing
    never raises IndexError, it simply returns up to the available length.
    """
    if text is None:
        return "[dim]None[/dim]"
    if len(text) <= max_length:
        return escape(text)
    # Safe: if max_length > len(text), returns entire text
    return escape(text[:max_length]) + "[dim]...[/dim]"


def truncate_proof(proof: str | None, max_lines: int = 50, max_chars: int = 5000) -> str:
    """
    Truncate proof text showing first/last lines.

    This function is safe for any max_lines or max_chars value - Python's string/list
    slicing operations never raise IndexError, they simply return up to the available length.
    """
    if proof is None:
        return "[dim]None[/dim]"

    lines = proof.split("\n")
    total_lines = len(lines)

    # If proof fits within limits, return as-is
    if total_lines <= max_lines and len(proof) <= max_chars:
        return escape(proof)

    # Show first few and last few lines (safe even if half > total_lines)
    half = max_lines // 2
    first_lines = lines[:half]  # Safe: returns up to available lines
    last_lines = lines[-half:] if total_lines > max_lines and half > 0 else []

    result = "\n".join(first_lines)
    if last_lines:
        # Calculate actual omitted lines (could be 0 if very short)
        omitted_count = max(0, total_lines - max_lines)
        result += f"\n[dim]... ({omitted_count} lines omitted) ...[/dim]\n"
        result += "\n".join(last_lines)

    # Truncate by characters if still too long (safe: returns up to available chars)
    if len(result) > max_chars:
        result = result[:max_chars] + "[dim]...[/dim]"

    # Escape the result, handling rich markup properly
    return (
        escape(result.replace("[dim]", "<<<DIM>>>").replace("[/dim]", "<<<ENDDIM>>>"))
        .replace("<<<DIM>>>", "[dim]")
        .replace("<<<ENDDIM>>>", "[/dim]")
    )


def format_message(msg: AnyMessage, max_content_length: int = 1000) -> str:
    """Format a LangChain message for display."""
    msg_type = getattr(msg, "type", "unknown")
    content = getattr(msg, "content", str(msg))

    if msg_type == "human":
        prefix = "[cyan]Human[/cyan]"
    elif msg_type == "ai":
        prefix = "[magenta]AI[/magenta]"
    else:
        prefix = f"[dim]{msg_type}[/dim]"

    if isinstance(content, str):
        content_str = truncate_text(content, max_content_length)
    else:
        content_str = truncate_text(str(content), max_content_length)

    return f"{prefix}: {content_str}"


def format_compiled_proof_record(record: CompiledProofRecord) -> str:
    """Format a CompiledProofRecord as a single-line summary."""
    return f"[green]length={record['length']}[/green], api_call={record['api_call_count']}"


def format_compiled_proof_record_full(record: CompiledProofRecord, max_proof_chars: int = 1000) -> str:
    """Format a CompiledProofRecord with proof snippet."""
    proof_snippet = truncate_text(record["proof"], max_proof_chars)
    return (
        f"  • length: [green]{record['length']}[/green], "
        f"api_call_count: {record['api_call_count']}\n"
        f"    proof: {proof_snippet}"
    )


def create_optimization_plans_table(plans: list[OptimizationPlan], current_index: int = -1) -> Table:
    """Create a rich Table for optimization plans."""
    table = Table(
        title="Optimization Plans",
        show_header=True,
        header_style="bold",
        border_style="dim",
        expand=False,
    )

    table.add_column("#", style="dim", width=3)
    table.add_column("Lines", width=10)
    table.add_column("Title", width=60)
    table.add_column("Reduction", width=8)
    table.add_column("Status", width=12)
    table.add_column("Description", width=100)

    for i, plan in enumerate(plans):
        status_color = STATUS_COLORS.get(plan["status"], "white")
        reduction_color = REDUCTION_COLORS.get(plan["reduction"], "white")

        # Mark current plan with arrow
        index_marker = "→" if i == current_index else str(i)
        row_style = "bold" if i == current_index else ""

        table.add_row(
            index_marker,
            f"{plan['line_start']}-{plan['line_end']}",
            truncate_text(plan["title"], 1000),
            f"[{reduction_color}]{plan['reduction']}[/{reduction_color}]",
            f"[{status_color}]{plan['status']}[/{status_color}]",
            truncate_text(plan["description"], 1000),
            style=row_style,
        )

    return table


def create_retrieved_lemmas_table(lemmas: list[RetrievedLemma]) -> Table:
    """Create a rich Table for retrieved lemmas."""
    table = Table(
        title="Retrieved Lemmas",
        show_header=True,
        header_style="bold",
        border_style="dim",
        expand=False,
    )

    table.add_column("#", style="dim", width=3)
    table.add_column("Full Name", width=80)
    table.add_column("Module", width=80)
    table.add_column("Signature", width=150)

    for i, lemma in enumerate(lemmas):
        table.add_row(
            str(i),
            truncate_text(lemma["full_name"], 1000),
            truncate_text(lemma["module"], 1000),
            truncate_text(lemma["signature"], 1000),
        )

    return table


def create_compiled_proofs_table(records: list[CompiledProofRecord], title: str = "Compiled Proofs History") -> Table:
    """Create a rich Table for compiled proof records."""
    table = Table(
        title=title,
        show_header=True,
        header_style="bold",
        border_style="dim",
        expand=False,
    )

    table.add_column("#", style="dim", width=3)
    table.add_column("Length", width=10)
    table.add_column("API Call", width=10)
    table.add_column("Proof Snippet", width=200)

    for i, record in enumerate(records):
        table.add_row(
            str(i),
            f"[green]{record['length']}[/green]",
            str(record["api_call_count"]),
            truncate_text(record["proof"], 1000),
        )

    return table


def create_messages_table(messages: list[AnyMessage], title: str = "Message History") -> Table:
    """Create a rich Table for message history."""
    table = Table(
        title=title,
        show_header=True,
        header_style="bold",
        border_style="dim",
        expand=False,
    )

    table.add_column("#", style="dim", width=3)
    table.add_column("Type", width=8)
    table.add_column("Content", width=200)

    for i, msg in enumerate(messages):
        msg_type = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", str(msg))

        if msg_type == "human":
            type_styled = "[cyan]Human[/cyan]"
        elif msg_type == "ai":
            type_styled = "[magenta]AI[/magenta]"
        else:
            type_styled = f"[dim]{msg_type}[/dim]"

        content_str = truncate_text(str(content) if not isinstance(content, str) else content, 1000)

        table.add_row(str(i), type_styled, content_str)

    return table


def format_planner_state(
    state: PlannerOptimizedProofState,
    state_index: int = 0,
    show_proofs: bool = True,
    show_histories: bool = True,
    console: Console | None = None,
) -> Panel:
    """
    Format a single PlannerOptimizedProofState as a rich Panel.

    Parameters
    ----------
    state : PlannerOptimizedProofState
        The state to format.
    state_index : int
        Index of this state in the queue (for display).
    show_proofs : bool
        Whether to show full proof content (truncated).
    show_histories : bool
        Whether to show full history tables.
    console : Console | None
        Optional console for rendering (not used directly, for future extensions).

    Returns
    -------
    Panel
        A rich Panel containing the formatted state.
    """
    # Build the content tree
    tree = Tree(f"[bold]State #{state_index}[/bold]")

    # === Summary Branch ===
    summary = tree.add("[bold cyan]Summary[/bold cyan]")
    summary.add(f"relative_path: [blue]{state['relative_path']}[/blue]")
    summary.add(f"compiled: {'[green]True[/green]' if state['compiled'] else '[red]False[/red]'}")
    summary.add(f"shortest_proof_length: [green]{state['shortest_proof_length']}[/green] tokens")
    summary.add(f"current_plan_index: {state['current_plan_index']}")
    summary.add(f"replan_count: {state['replan_count']}")
    summary.add(f"self_correction_attempts: {state['self_correction_attempts']}")
    summary.add(f"total_plans_tried: {state['total_plans_tried']}")
    summary.add(f"total_plans_improved: {state['total_plans_improved']}")
    summary.add(f"current_round_plans_tried: {state['current_round_plans_tried']}")

    # === Optional Fields ===
    optional = tree.add("[bold cyan]Optional Metadata[/bold cyan]")
    if "signature" in state:
        optional.add(f"signature: {truncate_text(state.get('signature'), 1000)}")
    else:
        optional.add("[dim]signature: (not set)[/dim]")
    if "doc_string" in state:
        optional.add(f"doc_string: {truncate_text(state.get('doc_string'), 1000)}")
    else:
        optional.add("[dim]doc_string: (not set)[/dim]")
    if "dependencies" in state:
        optional.add(f"dependencies: {truncate_text(state.get('dependencies'), 1000)}")
    else:
        optional.add("[dim]dependencies: (not set)[/dim]")

    # === Errors ===
    errors_branch = tree.add("[bold cyan]Errors[/bold cyan]")
    if state["errors"]:
        errors_branch.add(f"[red]{truncate_text(state['errors'], 1000)}[/red]")
    else:
        errors_branch.add("[dim]None[/dim]")

    # === Proofs ===
    if show_proofs:
        proofs = tree.add("[bold cyan]Proofs[/bold cyan]")

        original_proof = proofs.add("original_proof:")
        original_proof.add(truncate_proof(state["original_proof"], max_lines=50, max_chars=5000))

        current_proof = proofs.add("current_proof:")
        current_proof.add(truncate_proof(state["current_proof"], max_lines=50, max_chars=5000))

        optimized_proof = proofs.add("optimized_proof:")
        optimized_proof.add(truncate_proof(state["optimized_proof"], max_lines=50, max_chars=5000))

        shortest_proof = proofs.add("shortest_proof:")
        shortest_proof.add(truncate_proof(state["shortest_proof"], max_lines=50, max_chars=5000))

        if state["previous_proof_before_replan"]:
            prev_proof = proofs.add("previous_proof_before_replan:")
            prev_proof.add(truncate_proof(state["previous_proof_before_replan"], max_lines=50, max_chars=5000))

    # === Previous Plans Response ===
    if state["previous_plans_response"]:
        prev_response = tree.add("[bold cyan]Previous Plans Response[/bold cyan]")
        prev_response.add(truncate_text(state["previous_plans_response"], 1000))

    # Return the panel
    return Panel(
        tree,
        title=f"[bold]PlannerOptimizedProofState #{state_index}[/bold]",
        border_style="blue",
        expand=False,
    )


def format_planner_state_tables(
    state: PlannerOptimizedProofState,
    console: Console,
) -> None:
    """
    Print tables for list-based fields of a PlannerOptimizedProofState.

    This prints tables for:
    - optimization_plans
    - plan_retrievals
    - compiled_proofs_history
    - improvements_history
    - successful_plans
    - last_round_plans
    - optimization_history
    - planner_history
    - planner_history_full

    Parameters
    ----------
    state : PlannerOptimizedProofState
        The state whose tables to print.
    console : Console
        The rich console to print to.
    """
    # Optimization Plans
    if state["optimization_plans"]:
        table = create_optimization_plans_table(state["optimization_plans"], state["current_plan_index"])
        console.print(table)
    else:
        console.print("[dim]optimization_plans: (empty)[/dim]")

    # Plan Retrievals
    if state["plan_retrievals"]:
        table = create_retrieved_lemmas_table(state["plan_retrievals"])
        console.print(table)
    else:
        console.print("[dim]plan_retrievals: (empty)[/dim]")

    # Compiled Proofs History
    if state["compiled_proofs_history"]:
        table = create_compiled_proofs_table(state["compiled_proofs_history"], "Compiled Proofs History")
        console.print(table)
    else:
        console.print("[dim]compiled_proofs_history: (empty)[/dim]")

    # Improvements History
    if state["improvements_history"]:
        table = create_compiled_proofs_table(state["improvements_history"], "Improvements History")
        console.print(table)
    else:
        console.print("[dim]improvements_history: (empty)[/dim]")

    # Successful Plans
    if state["successful_plans"]:
        table = create_optimization_plans_table(state["successful_plans"])
        table.title = "Successful Plans"
        console.print(table)
    else:
        console.print("[dim]successful_plans: (empty)[/dim]")

    # Last Round Plans
    if state["last_round_plans"]:
        table = create_optimization_plans_table(state["last_round_plans"])
        table.title = "Last Round Plans"
        console.print(table)
    else:
        console.print("[dim]last_round_plans: (empty)[/dim]")

    # Note: Optimization History, Planner History, and Planner History Full are not printed to reduce verbosity


def print_queue(
    queue: list[PlannerOptimizedProofState],
    queue_name: str,
    console: Console,
    show_proofs: bool = True,
    show_histories: bool = True,
    show_tables: bool = True,
) -> None:
    """
    Print the contents of a single queue.

    Parameters
    ----------
    queue : list[PlannerOptimizedProofState]
        The queue to print.
    queue_name : str
        Name of the queue for display.
    console : Console
        The rich console to print to.
    show_proofs : bool
        Whether to show proof content.
    show_histories : bool
        Whether to show history information.
    show_tables : bool
        Whether to show detailed tables for list fields.
    """
    if not queue:
        console.print(f"[dim]{queue_name}: (empty)[/dim]")
        return

    console.print(f"\n[bold yellow]━━━ {queue_name} ({len(queue)} items) ━━━[/bold yellow]")

    for i, state in enumerate(queue):
        # Print the main state panel
        panel = format_planner_state(
            state,
            state_index=i,
            show_proofs=show_proofs,
            show_histories=show_histories,
            console=console,
        )
        console.print(panel)

        # Print detailed tables if requested
        if show_tables:
            console.print("[dim]──── Tables ────[/dim]")
            format_planner_state_tables(state, console)

        console.print()


def print_all_queues(
    state: PlannerOptimizerState,
    console: Console | None = None,
    show_proofs: bool = True,
    show_histories: bool = True,
    show_tables: bool = True,
    show_empty_queues: bool = True,
) -> None:
    """
    Print the contents of all queues in the PlannerOptimizerState.

    This is the main entry point for debug printing. It prints all 5 queues:
    - planner_plan_queue
    - planner_find_queue
    - planner_execute_queue
    - planner_compile_queue
    - planner_correct_queue

    Parameters
    ----------
    state : PlannerOptimizerState
        The optimizer state containing the queues.
    console : Console | None
        The rich console to print to. If None, creates a new Console.
    show_proofs : bool
        Whether to show proof content (truncated).
    show_histories : bool
        Whether to show history information.
    show_tables : bool
        Whether to show detailed tables for list fields.
    show_empty_queues : bool
        Whether to show empty queues.
    """
    if console is None:
        console = Console()

    console.print("\n[bold magenta]╔══════════════════════════════════════════════════════════════╗[/bold magenta]")
    console.print("[bold magenta]║           PLANNER OPTIMIZER QUEUE DEBUG DUMP                 ║[/bold magenta]")
    console.print("[bold magenta]╚══════════════════════════════════════════════════════════════╝[/bold magenta]")

    # Print workflow status
    console.print("\n[bold]Workflow Status:[/bold]")
    console.print(f"  is_finished: {'[green]True[/green]' if state.is_finished else '[yellow]False[/yellow]'}")
    console.print(f"  reason: {state.reason or '[dim]None[/dim]'}")
    console.print(f"  api_calls_count: {state.api_calls_count}/{state.api_budget}")
    console.print(f"  max_correction_attempts: {state.max_correction_attempts}")
    console.print(f"  max_replans: {state.max_replans}")

    # Print action history
    if state.action_history:
        console.print(f"\n[bold]Action History:[/bold] {' → '.join(state.action_history[-10:])}")
        if len(state.action_history) > 10:
            console.print(f"  [dim]({len(state.action_history) - 10} earlier actions omitted)[/dim]")

    # Define queues to print
    queues = [
        ("planner_plan_queue", state.planner_plan_queue),
        ("planner_find_queue", state.planner_find_queue),
        ("planner_execute_queue", state.planner_execute_queue),
        ("planner_compile_queue", state.planner_compile_queue),
        ("planner_correct_queue", state.planner_correct_queue),
    ]

    # Print each queue
    for queue_name, queue in queues:
        if queue or show_empty_queues:
            print_queue(
                queue,
                queue_name,
                console,
                show_proofs=show_proofs,
                show_histories=show_histories,
                show_tables=show_tables,
            )

    console.print("\n[bold magenta]════════════════════════════════════════════════════════════════[/bold magenta]\n")


def print_queue_summary(
    state: PlannerOptimizerState,
    console: Console | None = None,
) -> None:
    """
    Print a compact summary of all queues (just counts, no details).

    Parameters
    ----------
    state : PlannerOptimizerState
        The optimizer state containing the queues.
    console : Console | None
        The rich console to print to. If None, creates a new Console.
    """
    if console is None:
        console = Console()

    table = Table(
        title="Queue Summary",
        show_header=True,
        header_style="bold",
        border_style="dim",
    )

    table.add_column("Queue", width=25)
    table.add_column("Count", width=10)
    table.add_column("Status", width=20)

    queues = [
        ("planner_plan_queue", state.planner_plan_queue),
        ("planner_find_queue", state.planner_find_queue),
        ("planner_execute_queue", state.planner_execute_queue),
        ("planner_compile_queue", state.planner_compile_queue),
        ("planner_correct_queue", state.planner_correct_queue),
    ]

    for queue_name, queue in queues:
        count = len(queue)
        if count == 0:
            status = "[dim]empty[/dim]"
        else:
            status = "[green]has items[/green]"

        table.add_row(queue_name, str(count), status)

    console.print(table)


# =============================================================================
# Simple Optimizer Queue Debug Functions
# =============================================================================

# Truncation limit for optimizer debug output (user-specified)
OPTIMIZER_MAX_CHARS = 1500


def format_optimizer_state(
    state: OptimizedProofState,
    state_index: int = 0,
    show_proofs: bool = True,
    console: Console | None = None,
) -> Panel:
    """
    Format a single OptimizedProofState as a rich Panel.

    Parameters
    ----------
    state : OptimizedProofState
        The state to format.
    state_index : int
        Index of this state in the queue (for display).
    show_proofs : bool
        Whether to show full proof content (truncated to 1500 chars).
    console : Console | None
        Optional console for rendering (for future extensions).

    Returns
    -------
    Panel
        A rich Panel containing the formatted state.
    """
    # Build the content tree
    tree = Tree(f"[bold]State #{state_index}[/bold]")

    # === Summary Branch ===
    summary = tree.add("[bold cyan]Summary[/bold cyan]")
    summary.add(f"relative_path: [blue]{state['relative_path']}[/blue]")
    summary.add(f"compiled: {'[green]True[/green]' if state['compiled'] else '[red]False[/red]'}")
    summary.add(f"shortest_proof_length: [green]{state['shortest_proof_length']}[/green] tokens")
    summary.add(f"self_correction_attempts: {state['self_correction_attempts']}")

    # === Optional Metadata Fields ===
    optional = tree.add("[bold cyan]Optional Metadata[/bold cyan]")
    if "signature" in state:
        optional.add(f"signature: {truncate_text(state.get('signature'), OPTIMIZER_MAX_CHARS)}")
    else:
        optional.add("[dim]signature: (not set)[/dim]")
    if "doc_string" in state:
        optional.add(f"doc_string: {truncate_text(state.get('doc_string'), OPTIMIZER_MAX_CHARS)}")
    else:
        optional.add("[dim]doc_string: (not set)[/dim]")
    if "dependencies" in state:
        optional.add(f"dependencies: {truncate_text(state.get('dependencies'), OPTIMIZER_MAX_CHARS)}")
    else:
        optional.add("[dim]dependencies: (not set)[/dim]")

    # === Errors ===
    errors_branch = tree.add("[bold cyan]Errors[/bold cyan]")
    if state["errors"]:
        errors_branch.add(f"[red]{truncate_text(state['errors'], OPTIMIZER_MAX_CHARS)}[/red]")
    else:
        errors_branch.add("[dim]None[/dim]")

    # === Proofs ===
    if show_proofs:
        proofs = tree.add("[bold cyan]Proofs[/bold cyan]")

        original_proof = proofs.add("original_proof:")
        original_proof.add(truncate_proof(state["original_proof"], max_lines=30, max_chars=OPTIMIZER_MAX_CHARS))

        current_proof = proofs.add("current_proof:")
        current_proof.add(truncate_proof(state["current_proof"], max_lines=30, max_chars=OPTIMIZER_MAX_CHARS))

        optimized_proof = proofs.add("optimized_proof:")
        optimized_proof.add(truncate_proof(state["optimized_proof"], max_lines=30, max_chars=OPTIMIZER_MAX_CHARS))

        shortest_proof = proofs.add("shortest_proof:")
        shortest_proof.add(truncate_proof(state["shortest_proof"], max_lines=30, max_chars=OPTIMIZER_MAX_CHARS))

    # Return the panel
    return Panel(
        tree,
        title=f"[bold]OptimizedProofState #{state_index}[/bold]",
        border_style="blue",
        expand=False,
    )


def format_optimizer_state_tables(
    state: OptimizedProofState,
    console: Console,
) -> None:
    """
    Print tables for list-based fields of an OptimizedProofState.

    This prints tables for:
    - compiled_proofs_history
    - improvements_history

    Parameters
    ----------
    state : OptimizedProofState
        The state whose tables to print.
    console : Console
        The rich console to print to.
    """
    # Compiled Proofs History
    if state["compiled_proofs_history"]:
        table = create_compiled_proofs_table(state["compiled_proofs_history"], "Compiled Proofs History")
        console.print(table)
    else:
        console.print("[dim]compiled_proofs_history: (empty)[/dim]")

    # Improvements History
    if state["improvements_history"]:
        table = create_compiled_proofs_table(state["improvements_history"], "Improvements History")
        console.print(table)
    else:
        console.print("[dim]improvements_history: (empty)[/dim]")

    # Note: optimization_history (LLM message history) is not printed to reduce verbosity


def print_optimizer_queue(
    queue: list[OptimizedProofState],
    queue_name: str,
    console: Console,
    show_proofs: bool = True,
    show_tables: bool = True,
) -> None:
    """
    Print the contents of a single optimizer queue.

    Parameters
    ----------
    queue : list[OptimizedProofState]
        The queue to print.
    queue_name : str
        Name of the queue for display.
    console : Console
        The rich console to print to.
    show_proofs : bool
        Whether to show proof content.
    show_tables : bool
        Whether to show detailed tables for list fields.
    """
    if not queue:
        console.print(f"[dim]{queue_name}: (empty)[/dim]")
        return

    console.print(f"\n[bold yellow]━━━ {queue_name} ({len(queue)} items) ━━━[/bold yellow]")

    for i, state in enumerate(queue):
        # Print the main state panel
        panel = format_optimizer_state(
            state,
            state_index=i,
            show_proofs=show_proofs,
            console=console,
        )
        console.print(panel)

        # Print detailed tables if requested
        if show_tables:
            console.print("[dim]──── Tables ────[/dim]")
            format_optimizer_state_tables(state, console)

        console.print()


def print_all_optimizer_queues(
    state: OptimizerState,
    console: Console | None = None,
    show_proofs: bool = True,
    show_tables: bool = True,
    show_empty_queues: bool = True,
) -> None:
    """
    Print the contents of all queues in the OptimizerState.

    This is the main entry point for debug printing. It prints all 3 queues:
    - optimizer_optimize_queue
    - optimizer_compile_queue
    - optimizer_correct_queue

    Parameters
    ----------
    state : OptimizerState
        The optimizer state containing the queues.
    console : Console | None
        The rich console to print to. If None, creates a new Console.
    show_proofs : bool
        Whether to show proof content (truncated to 1500 chars).
    show_tables : bool
        Whether to show detailed tables for list fields.
    show_empty_queues : bool
        Whether to show empty queues.
    """
    if console is None:
        console = Console()

    console.print("\n[bold magenta]╔══════════════════════════════════════════════════════════════╗[/bold magenta]")
    console.print("[bold magenta]║              OPTIMIZER QUEUE DEBUG DUMP                       ║[/bold magenta]")
    console.print("[bold magenta]╚══════════════════════════════════════════════════════════════╝[/bold magenta]")

    # Print workflow status
    console.print("\n[bold]Workflow Status:[/bold]")
    console.print(f"  is_finished: {'[green]True[/green]' if state.is_finished else '[yellow]False[/yellow]'}")
    console.print(f"  reason: {state.reason or '[dim]None[/dim]'}")
    console.print(f"  api_calls_count: {state.api_calls_count}/{state.api_budget}")

    # Print action history
    if state.action_history:
        console.print(f"\n[bold]Action History:[/bold] {' → '.join(state.action_history[-10:])}")
        if len(state.action_history) > 10:
            console.print(f"  [dim]({len(state.action_history) - 10} earlier actions omitted)[/dim]")

    # Define queues to print
    queues = [
        ("optimizer_optimize_queue", state.optimizer_optimize_queue),
        ("optimizer_compile_queue", state.optimizer_compile_queue),
        ("optimizer_correct_queue", state.optimizer_correct_queue),
    ]

    # Print each queue
    for queue_name, queue in queues:
        if queue or show_empty_queues:
            print_optimizer_queue(
                queue,
                queue_name,
                console,
                show_proofs=show_proofs,
                show_tables=show_tables,
            )

    console.print("\n[bold magenta]════════════════════════════════════════════════════════════════[/bold magenta]\n")


def print_optimizer_queue_summary(
    state: OptimizerState,
    console: Console | None = None,
) -> None:
    """
    Print a compact summary of all optimizer queues (just counts, no details).

    Parameters
    ----------
    state : OptimizerState
        The optimizer state containing the queues.
    console : Console | None
        The rich console to print to. If None, creates a new Console.
    """
    if console is None:
        console = Console()

    table = Table(
        title="Optimizer Queue Summary",
        show_header=True,
        header_style="bold",
        border_style="dim",
    )

    table.add_column("Queue", width=25)
    table.add_column("Count", width=10)
    table.add_column("Status", width=20)

    queues = [
        ("optimizer_optimize_queue", state.optimizer_optimize_queue),
        ("optimizer_compile_queue", state.optimizer_compile_queue),
        ("optimizer_correct_queue", state.optimizer_correct_queue),
    ]

    for queue_name, queue in queues:
        count = len(queue)
        if count == 0:
            status = "[dim]empty[/dim]"
        else:
            status = "[green]has items[/green]"

        table.add_row(queue_name, str(count), status)

    console.print(table)
