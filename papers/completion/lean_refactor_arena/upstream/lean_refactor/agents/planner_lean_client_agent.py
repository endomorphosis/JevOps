"""
Planner Lean Client Agent for planner-based proof optimization workflow.

This agent checks if an optimized proof compiles using the LeanClientScheduler,
specifically handling PlannerOptimizedProofState types.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from lean_refactor.agents.state import PlannerOptimizedProofState, PlannerOptimizedProofStates

if TYPE_CHECKING:
    from lean_refactor.util.verifier_lean_client import LeanClientScheduler

logger = logging.getLogger(__name__)


class PlannerLeanClientAgentFactory:
    """
    Factory class for creating instances of the PlannerLeanClientAgent.
    """

    @staticmethod
    def create_agent(lean_scheduler: LeanClientScheduler) -> CompiledStateGraph:
        """
        Creates a PlannerLeanClientAgent instance using the provided scheduler.

        Parameters
        ----------
        lean_scheduler : LeanClientScheduler
            The multi-process scheduler for proof verification.

        Returns
        -------
        CompiledStateGraph
            A CompiledStateGraph instance of the planner lean client agent.
        """
        return _build_agent(lean_scheduler=lean_scheduler)


def _build_agent(lean_scheduler: LeanClientScheduler) -> CompiledStateGraph:
    """
    Builds a compiled state graph for the planner lean client agent.

    Parameters
    ----------
    lean_scheduler : LeanClientScheduler
        The multi-process scheduler for proof verification.

    Returns
    -------
    CompiledStateGraph
        The compiled state graph for the planner lean client agent.
    """
    graph_builder = StateGraph(PlannerOptimizedProofStates)

    # Bind the scheduler
    bound_check_proofs = partial(_check_planner_proofs_batch, lean_scheduler)

    # Add the nodes - use batch processing for efficiency
    graph_builder.add_node("planner_lean_client_agent", bound_check_proofs)

    # Add the edges
    graph_builder.add_edge(START, "planner_lean_client_agent")
    graph_builder.add_edge("planner_lean_client_agent", END)

    return graph_builder.compile()


def _check_planner_proofs_batch(
    lean_scheduler: LeanClientScheduler, states: PlannerOptimizedProofStates
) -> PlannerOptimizedProofStates:
    """
    Checks multiple optimized proofs in batch using the scheduler.

    Parameters
    ----------
    lean_scheduler : LeanClientScheduler
        The multi-process scheduler for proof verification.
    states : PlannerOptimizedProofStates
        The states containing proofs to check.

    Returns
    -------
    PlannerOptimizedProofStates
        States with compilation results in the outputs field.
    """
    from lean_refactor.util.interaction import LeanInteractor

    input_states = states["inputs"]
    logger.debug(f"Checking {len(input_states)} optimized proofs in batch...")
    output_states: list[PlannerOptimizedProofState] = []

    # Separate states into those that need verification and those that don't
    states_to_verify: list[tuple[int, PlannerOptimizedProofState]] = []

    for idx, state in enumerate(input_states):
        if state["optimized_proof"] is None:
            # No proof to check - mark as failed
            state["compiled"] = False
            state["errors"] = state["errors"] or "No optimized proof to check"
            output_states.append(state)
        else:
            states_to_verify.append((idx, state))

    if not states_to_verify:
        return {"inputs": [], "outputs": output_states}

    # Create tasks for the scheduler
    tasks = []
    for idx, state in states_to_verify:
        tasks.append({
            "old_code": state["original_proof"],
            "new_code": state["optimized_proof"],
            "relative_path": state["relative_path"],
            "full_file_mode": False,
        })

    # Submit all tasks to the scheduler
    request_ids = lean_scheduler.submit_all_request(tasks)

    # Get all results
    results = lean_scheduler.get_all_request_outputs(request_ids)

    # Log summary of verification results
    logger.debug(f"Lean verification results for {len(results)} proofs:")
    for i, result in enumerate(results):
        passed = result.get("pass", False)
        has_error = result.get("error_occurred", False)
        diagnostics_count = len(result.get("diagnostics", []))
        logger.debug(f"  [{i}] pass={passed}, error_occurred={has_error}, diagnostics={diagnostics_count}")

    for (idx, state), result in zip(states_to_verify, results, strict=False):
        check_correct = result.get("pass", False)
        error_occurred = result.get("error_occurred", False)

        if error_occurred:
            # System error during verification
            state["compiled"] = False
            state["errors"] = "System error during proof verification"
        elif check_correct:
            # Proof compiles successfully
            state["compiled"] = True
            state["errors"] = None
        else:
            # Proof has compilation errors
            state["compiled"] = False
            state["errors"] = LeanInteractor.get_error_str(
                result.get("file_content", ""),
                result.get("diagnostics", []),
                error_thres=False,
            )

        output_states.append(state)

    return {"inputs": [], "outputs": output_states}
