"""
Planner Repl Agent for planner-based proof optimization workflow.

This agent checks if an optimized proof compiles using the Lean4ServerScheduler (repl),
specifically handling PlannerOptimizedProofState types.
"""

from __future__ import annotations

import logging
import json
from functools import partial
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from lean_refactor.agents.state import PlannerOptimizedProofState, PlannerOptimizedProofStates
from lean_refactor.utils import get_error_str_goedel_style

if TYPE_CHECKING:
    from lean_refactor.util.verifier_slow import Lean4ServerScheduler

logger = logging.getLogger(__name__)


class PlannerReplAgentFactory:
    """
    Factory class for creating instances of the PlannerReplAgent.
    """

    @staticmethod
    def create_agent(lean_scheduler: Lean4ServerScheduler) -> CompiledStateGraph:
        """
        Creates a PlannerReplAgent instance using the provided scheduler.

        Parameters
        ----------
        lean_scheduler : Lean4ServerScheduler
            The multi-process scheduler for proof verification.

        Returns
        -------
        CompiledStateGraph
            A CompiledStateGraph instance of the planner repl agent.
        """
        return _build_agent(lean_scheduler=lean_scheduler)


def _build_agent(lean_scheduler: Lean4ServerScheduler) -> CompiledStateGraph:
    """
    Builds a compiled state graph for the planner repl agent.

    Parameters
    ----------
    lean_scheduler : Lean4ServerScheduler
        The multi-process scheduler for proof verification.

    Returns
    -------
    CompiledStateGraph
        The compiled state graph for the planner repl agent.
    """
    graph_builder = StateGraph(PlannerOptimizedProofStates)

    # Bind the scheduler
    bound_check_proofs = partial(_check_planner_proofs_batch, lean_scheduler)

    # Add the nodes - use batch processing for efficiency
    graph_builder.add_node("planner_repl_agent", bound_check_proofs)

    # Add the edges
    graph_builder.add_edge(START, "planner_repl_agent")
    graph_builder.add_edge("planner_repl_agent", END)

    return graph_builder.compile()


def _check_planner_proofs_batch(
    lean_scheduler: Lean4ServerScheduler, states: PlannerOptimizedProofStates
) -> PlannerOptimizedProofStates:
    """
    Checks multiple optimized proofs in batch using the scheduler.

    Parameters
    ----------
    lean_scheduler : Lean4ServerScheduler
        The multi-process scheduler for proof verification.
    states : PlannerOptimizedProofStates
        The states containing proofs to check.

    Returns
    -------
    PlannerOptimizedProofStates
        States with compilation results in the outputs field.
    """
    input_states = states["inputs"]
    logger.debug(f"Checking {len(input_states)} optimized proofs in batch (repl)...")
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
    # Keep track of the code used for verification for error reporting
    verification_codes = {}

    for idx, state in states_to_verify:
        # verifier_slow expects 'code', 'ast', 'tactics' keys in the task dict
        # or just a string as code.
        # We pass the full code to check.
        
        code_to_verify = state["optimized_proof"]
        # Prepend header if present (for REPL mode)
        header = state.get("header")
        if header:
            code_to_verify = f"{header}{code_to_verify}"
            
        verification_codes[idx] = code_to_verify
        
        tasks.append({
            "code": code_to_verify,
            "ast": True,
            "tactics": True,
            # "timeout": 600 # Default timeout, could be configurable
        })

    # Submit all tasks to the scheduler
    # Lean4ServerScheduler inherits from ProcessScheduler which supports submit_all_request
    request_ids = lean_scheduler.submit_all_request(tasks)

    # Get all results
    results = lean_scheduler.get_all_request_outputs(request_ids)

    # Log summary of verification results
    logger.debug(f"Repl verification results for {len(results)} proofs:")
    for i, result in enumerate(results):
        passed = result.get("pass", False)
        complete = result.get("complete", False)
        logger.debug(f"  [{i}] pass={passed}, complete={complete}")

    for (idx, state), result in zip(states_to_verify, results, strict=False):
        # Log result object without verified_code for debugging
        result_for_logging = {k: v for k, v in result.items() if k != 'verified_code'}
        verified_code = result.get("verified_code")
        if verified_code:
            # Find the first "theorem" and print the first 50 chars starting from there
            theorem_idx = verified_code.find('theorem')
            if theorem_idx >= 0:
                code_preview = verified_code[theorem_idx:min(theorem_idx + 50, len(verified_code))]
            else:
                code_preview = verified_code[:min(50, len(verified_code))]
            result_for_logging["verified_code"] = code_preview
        logger.debug(f"Lean repl server compilation result {idx}: {result_for_logging}")


        check_pass = result.get("pass", False)
        check_complete = result.get("complete", False)
        system_errors = result.get("system_errors")

        if system_errors:
            # System error during verification
            state["compiled"] = False
            state["errors"] = f"System error during proof verification: {system_errors}"
        elif check_pass and check_complete:
            # Proof compiles successfully
            state["compiled"] = True
            state["errors"] = None
        else:
            # Proof has compilation errors
            state["compiled"] = False
            # Use the code actually verified (potentially with header) for error reporting
            code_used = verification_codes.get(idx, state["optimized_proof"])
            state["errors"] = get_error_str_goedel_style(
                    code_used,
                    result.get("errors", []),
                    error_thres=False,
                )
            if result.get("sorries"):
                state["errors"] += f"\n\nFinal Error: \"sorry\" found in your proof. You are not allowed to use \"sorry\", and you must complete the proof."

        output_states.append(state)

    return {"inputs": [], "outputs": output_states}

