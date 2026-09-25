"""
State TypedDicts for the Planner-Based Optimizer Workflow.

This module contains TypedDict definitions used by the planner optimization agents.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any

from langchain_core.messages import AnyMessage
from typing_extensions import NotRequired, Required, TypedDict


class APISearchResponseTypedDict(TypedDict):
    """
    TypedDict representation of APISearchResponse from lean_explore.shared.models.api.

    This TypedDict matches the structure of APISearchResponse to enable type checking
    while maintaining compatibility with the lean_explore API.

    Attributes
    ----------
    query: Required[str]
        The search query that was executed
    packages_applied: Required[list[str]]
        List of package filters that were applied to the search
    results: Required[list[dict[str, Any]]]
        List of search results, where each result is a dictionary containing
        theorem information (name, type, code, etc.)
    count: Required[int]
        Number of results returned
    total_candidates_considered: Required[int]
        Total number of candidates that were considered during the search
    processing_time_ms: Required[int]
        Time taken to process the search query in milliseconds
    """

    query: Required[str]
    packages_applied: Required[list[str]]
    results: Required[list[dict[str, Any]]]
    count: Required[int]
    total_candidates_considered: Required[int]
    processing_time_ms: Required[int]


class CompiledProofRecord(TypedDict):
    """
    A record of a successfully compiled proof during optimization.

    Attributes
    ----------
    proof : str
        The full proof text including imports/preamble.
    length : int
        The token count of the proof.
    api_call_count : int
        The API call count when this proof was discovered.
    """

    proof: Required[str]
    length: Required[int]
    api_call_count: Required[int]


class OptimizationPlan(TypedDict):
    """
    A single optimization plan targeting a specific region of the proof.

    Attributes
    ----------
    line_start : int
        The starting line number (1-indexed) of the proof region to optimize.
    line_end : int
        The ending line number (1-indexed, inclusive) of the proof region to optimize.
    title : str
        A short descriptive name that summarizes the optimization strategy.
    reduction : str
        The potential reduction from this strategy: "high", "medium", or "low".
    description : str
        A detailed description of the planned optimization.
    status : str
        The status of this plan: "pending", "in_progress", "completed", "failed", "skipped".
    """

    line_start: Required[int]
    line_end: Required[int]
    title: Required[str]
    reduction: Required[str]
    description: Required[str]
    status: Required[str]


class RetrievedLemma(TypedDict):
    """
    A lemma retrieved from the Mathlib retrieval service.

    Attributes
    ----------
    full_name : str
        The fully qualified name of the lemma (e.g., "Nat.add_comm").
    module : str
        The module where the lemma is defined (e.g., "Mathlib.Algebra.Group.Basic").
    signature : str
        The type signature of the lemma.
    source_code : str
        The source code of the lemma definition.
    doc_string : str | None
        The documentation string of the lemma, if available.
    """

    full_name: Required[str]
    module: Required[str | None]
    signature: Required[str | None]
    source_code: Required[str | None]
    doc_string: Required[str | None]


class PlannerOptimizedProofState(TypedDict):
    """
    State for a proof in the planner-based optimization workflow.

    This extends the concept of OptimizedProofState with planning and retrieval fields
    for the multi-agent workflow.

    Attributes
    ----------
    original_proof : str
        The original proof that was provided for optimization (immutable reference).
    current_proof : str
        The current version of the proof being optimized.
    optimized_proof : str | None
        The most recently generated optimized proof from the executer agent.
    compiled : bool
        Whether the optimized_proof compiles successfully.
    errors : str | None
        Compilation errors from the lean client, if any.
    self_correction_attempts : int
        Number of correction attempts for the current plan execution.
    optimization_history : list[AnyMessage]
        Message history for the current plan execution cycle.
    shortest_proof : str
        The shortest valid proof found so far during optimization.
    shortest_proof_length : int
        Token count of the shortest proof found so far.
    compiled_proofs_history : list[CompiledProofRecord]
        History of all successfully compiled proofs.
    improvements_history : list[CompiledProofRecord]
        History of proofs that were shorter than previous best.
    relative_path : str
        The relative path within the Lean workspace for this proof file.
    optimization_plans : list[OptimizationPlan]
        The ordered list of optimization plans generated by the planner agent.
    current_plan_index : int
        Index of the current plan being executed (0-indexed).
    plan_retrievals : list[RetrievedLemma]
        Retrieved lemmas from the finder agent for the current plan.
    planner_history : list[AnyMessage]
        Message history for the current planning round only (cleared on replan).
    replan_count : int
        Number of times the planner has been asked to replan.
    previous_plans_response : str
        Raw LLM XML response from previous planning round.
    successful_plans : list[OptimizationPlan]
        All plans that led to improvements across all rounds.
    total_plans_tried : int
        Total plans tried across all rounds.
    total_plans_improved : int
        Total plans that led to improvement.
    current_round_plans_tried : int
        Plans tried in current planning round.
    planner_history_full : list[AnyMessage]
        Full accumulated history for logging/debugging only (not fed to LLM).
    previous_proof_before_replan : str | None
        The proof before the successful optimization that triggered replan.
    last_round_plans : list[OptimizationPlan]
        Plans from previous round with their final status (completed/failed/pending/skipped).
    signature : str (optional)
        The elaborated type signature of the theorem.
    doc_string : str (optional)
        The documentation/informalization of the theorem.
    dependencies : str (optional)
        Formatted dependency information for the theorem.
    header: str (optional)
        The header information (imports, etc.) for the theorem, used in REPL compiler mode.
    """

    original_proof: Required[str]
    current_proof: Required[str]
    optimized_proof: Required[str | None]
    compiled: Required[bool]
    errors: Required[str | None]
    self_correction_attempts: Required[int]
    optimization_history: Required[Annotated[list[AnyMessage], add]]
    shortest_proof: Required[str]
    shortest_proof_length: Required[int]
    compiled_proofs_history: Required[list[CompiledProofRecord]]
    improvements_history: Required[list[CompiledProofRecord]]
    relative_path: Required[str]
    optimization_plans: Required[list[OptimizationPlan]]
    current_plan_index: Required[int]
    plan_retrievals: Required[list[RetrievedLemma]]
    planner_history: Required[Annotated[list[AnyMessage], add]]
    replan_count: Required[int]
    # Plan tracking fields for replan context
    previous_plans_response: Required[str]  # Raw LLM XML response from previous planning
    successful_plans: Required[list[OptimizationPlan]]  # All plans that led to improvements
    total_plans_tried: Required[int]  # Total plans tried across all rounds
    total_plans_improved: Required[int]  # Total plans that led to improvement
    current_round_plans_tried: Required[int]  # Plans tried in current planning round
    # Hybrid history management fields
    planner_history_full: Required[list[AnyMessage]]  # Full history for logging/debugging only
    previous_proof_before_replan: Required[str | None]  # Proof before successful optimization that triggered replan
    last_round_plans: Required[list[OptimizationPlan]]  # Plans from previous round with final status
    all_generated_plans_history: Required[
        list[list[OptimizationPlan]]
    ]  # History of all generated plans (one list per round)
    signature: NotRequired[str]
    doc_string: NotRequired[str]
    dependencies: NotRequired[str]
    header: NotRequired[str]
    use_tactic_style: NotRequired[bool]


class PlannerOptimizedProofStates(TypedDict):
    """
    A list of PlannerOptimizedProofState for map-reduce processing.

    Attributes
    ----------
    inputs : list[PlannerOptimizedProofState]
        List of states to process using map reduce.
    outputs : list[PlannerOptimizedProofState]
        List of states that are the results of the map reduce.
    """

    inputs: Required[list[PlannerOptimizedProofState]]
    outputs: Required[Annotated[list[PlannerOptimizedProofState], add]]
