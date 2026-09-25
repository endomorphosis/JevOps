"""
State management for the planner-based proof optimization workflow.

This module provides state classes for tracking proof optimization progress
using a multi-agent system with planning, retrieval, and step-by-step execution.
"""

from __future__ import annotations

import logging

from lean_refactor.agents.state import (
    CompiledProofRecord,
    OptimizationPlan,
    PlannerOptimizedProofState,
    PlannerOptimizedProofStates,
)
from lean_refactor.utils import proof_length

logger = logging.getLogger(__name__)


class PlannerOptimizerState:
    """
    State for the planner-based proof optimization workflow.

    This class manages the optimization state for a multi-agent workflow that
    includes planning, lemma retrieval, and step-by-step execution of optimization
    plans.

    Attributes
    ----------
    is_finished : bool
        Whether the optimization workflow has completed.
    reason : str | None
        The reason for finishing (success or failure description).
    api_budget : int
        Maximum number of API calls allowed.
    api_calls_count : int
        Current number of API calls made.
    action_history : list[str]
        History of actions taken during optimization.
    """

    def __init__(
        self,
        proof: str,
        api_budget: int,
        relative_path: str,
        signature: str | None = None,
        doc_string: str | None = None,
        dependencies: str | None = None,
        initial_proof_length: int | None = None,
        max_correction_attempts: int = 3,
        max_replans: int = 3,
        min_replans: int = 1,
        max_correction_attempts_high: int | None = None,
        max_correction_attempts_medium: int | None = None,
        max_correction_attempts_low: int | None = None,
        init_optim: bool = False,
        header: str | None = None,
        use_tactic_style: bool = False,
    ):
        """
        Initialize planner optimizer state with a proof to optimize.

        Parameters
        ----------
        proof : str
            The full proof to optimize, including imports/preamble.
        api_budget : int
            Maximum number of API calls allowed.
        relative_path : str
            The relative path within the Lean workspace for this proof file.
        signature : str | None
            Optional elaborated type signature of the theorem.
        doc_string : str | None
            Optional documentation/informalization.
        dependencies : str | None
            Optional formatted dependency information.
        initial_proof_length : int | None
            Optional pre-calculated proof length. If None, will be calculated from proof.
        max_correction_attempts : int
            Maximum correction attempts per plan execution (default: 3).
        max_replans : int
            Maximum number of replans allowed (default: 3).
        min_replans : int
             Minimum number of replans to attempt (default: 1).
        max_correction_attempts_high : int | None
            Maximum correction attempts for high reduction plans (default: max_correction_attempts).
        max_correction_attempts_medium : int | None
            Maximum correction attempts for medium reduction plans (default: max_correction_attempts).
        max_correction_attempts_low : int | None
            Maximum correction attempts for low reduction plans (default: max_correction_attempts).
        init_optim : bool
            Whether to run initial direct optimization (default: False).
        header : str | None
            Optional header information (imports, etc.) for the theorem, used in REPL compiler mode.
        """
        initial_length = initial_proof_length if initial_proof_length is not None else proof_length(proof)

        initial_state: PlannerOptimizedProofState = {
            "original_proof": proof,
            "current_proof": proof,
            "optimized_proof": None,
            "compiled": False,
            "errors": None,
            "self_correction_attempts": 0,
            "optimization_history": [],
            "shortest_proof": proof,
            "shortest_proof_length": initial_length,
            "compiled_proofs_history": [{"proof": proof, "length": initial_length, "api_call_count": 0}],
            "improvements_history": [{"proof": proof, "length": initial_length, "api_call_count": 0}],
            "relative_path": relative_path,
            "optimization_plans": [],
            "current_plan_index": 0,
            "plan_retrievals": [],
            "planner_history": [],
            "replan_count": 0,
            "previous_plans_response": "",
            "successful_plans": [],
            "total_plans_tried": 0,
            "total_plans_improved": 0,
            "current_round_plans_tried": 0,
            "planner_history_full": [],
            "previous_proof_before_replan": None,
            "last_round_plans": [],
            "all_generated_plans_history": [],
            "use_tactic_style": use_tactic_style,
        }

        # Conditionally add optional metadata fields
        if signature is not None:
            initial_state["signature"] = signature
        if doc_string is not None:
            initial_state["doc_string"] = doc_string
        if dependencies is not None:
            initial_state["dependencies"] = dependencies
        if header is not None:
            initial_state["header"] = header

        # Workflow state
        self.is_finished: bool = False
        self.reason: str | None = None
        self.final_optimized_proof: str | None = None
        self.final_state: PlannerOptimizedProofState | None = None

        # API budget tracking
        self.api_budget: int = api_budget
        self.api_calls_count: int = 0

        # Correction and replan limits
        self.max_correction_attempts: int = max_correction_attempts
        self.max_replans: int = max_replans
        self.min_replans: int = min_replans

        # Dynamic correction limits based on reduction level
        self.max_correction_attempts_high = (
            max_correction_attempts_high if max_correction_attempts_high is not None else max_correction_attempts
        )
        self.max_correction_attempts_medium = (
            max_correction_attempts_medium if max_correction_attempts_medium is not None else max_correction_attempts
        )
        self.max_correction_attempts_low = (
            max_correction_attempts_low if max_correction_attempts_low is not None else max_correction_attempts
        )

        # Action history
        self.action_history: list[str] = []

        # Initialize queues for the planner workflow
        # Queue naming: planner_<stage>_queue
        self.planner_plan_queue: list[PlannerOptimizedProofState] = []
        self.planner_initial_optim_queue: list[PlannerOptimizedProofState] = []
        self.planner_find_queue: list[PlannerOptimizedProofState] = []
        self.planner_execute_queue: list[PlannerOptimizedProofState] = []
        self.planner_compile_queue: list[PlannerOptimizedProofState] = []
        self.planner_correct_queue: list[PlannerOptimizedProofState] = []

        # Logic for initial optimization
        self.in_initial_optimization = init_optim
        if init_optim:
            self.planner_initial_optim_queue.append(initial_state)
            # Use high correction attempts for initial optimization as requested
            self.max_correction_attempts = self.max_correction_attempts_high
        else:
            self.planner_plan_queue.append(initial_state)


class PlannerOptimizerStateManager:
    """
    Manager class for coordinating operations on PlannerOptimizerState.

    This class provides higher-level operations for managing the flow of the
    planner-based proof optimization pipeline, including plan management,
    queue routing, and API budget tracking.
    """

    def __init__(self, state: PlannerOptimizerState):
        """
        Initialize the state manager.

        Parameters
        ----------
        state : PlannerOptimizerState
            The planner optimizer state to manage.
        """
        self._state = state

    @property
    def is_finished(self) -> bool:
        """Check if the optimization workflow has finished."""
        return self._state.is_finished

    @is_finished.setter
    def is_finished(self, value: bool) -> None:
        """Set the finished state."""
        self._state.is_finished = value

    @property
    def reason(self) -> str | None:
        """Get the reason for finishing."""
        return self._state.reason

    @reason.setter
    def reason(self, value: str | None) -> None:
        """Set the reason for finishing."""
        self._state.reason = value

    @property
    def api_calls_count(self) -> int:
        """Get current API calls count."""
        return self._state.api_calls_count

    @property
    def api_budget(self) -> int:
        """Get the API budget."""
        return self._state.api_budget

    @property
    def max_correction_attempts(self) -> int:
        """Get maximum correction attempts."""
        return self._state.max_correction_attempts

    @property
    def max_replans(self) -> int:
        """Get maximum replans allowed."""
        return self._state.max_replans

    @property
    def min_replans(self) -> int:
        """Get minimum replans to attempt."""
        return self._state.min_replans

    @property
    def shortest_proof(self) -> str:
        """Get the shortest proof found so far."""
        state = self._get_active_state()
        if state:
            return state["shortest_proof"]
        return ""

    @property
    def shortest_proof_length(self) -> int:
        """Get the length of the shortest proof."""
        state = self._get_active_state()
        if state:
            return state["shortest_proof_length"]
        return 0

    def add_action(self, action: str) -> None:
        """
        Add an action to the action history.

        Parameters
        ----------
        action : str
            The action name to record.
        """
        self._state.action_history.append(action)

    def increment_api_calls(self, count: int = 1) -> None:
        """
        Increment the API calls counter.

        Parameters
        ----------
        count : int
            Number of API calls to add (default: 1).
        """
        self._state.api_calls_count += count
        logger.debug(f"API calls: {self._state.api_calls_count}/{self._state.api_budget}")

    def _update_max_correction_attempts(self, state: PlannerOptimizedProofState | None = None) -> None:
        """
        Update max correction attempts based on the current plan's reduction level.

        Parameters
        ----------
        state : PlannerOptimizedProofState | None
            Optional state to check plan from. If None, gets from active state.
        """
        plan = self.get_current_plan(state)
        if not plan:
            return

        reduction = plan.get("reduction", "medium").lower()
        if reduction == "high":
            self._state.max_correction_attempts = self._state.max_correction_attempts_high
        elif reduction == "medium":
            self._state.max_correction_attempts = self._state.max_correction_attempts_medium
        else:
            # Default to medium for "medium" or any unknown value
            self._state.max_correction_attempts = self._state.max_correction_attempts_low

        logger.debug(
            f"Updated max correction attempts to {self._state.max_correction_attempts} "
            f"for '{reduction}' reduction plan: {plan['title']}"
        )

    def is_budget_exhausted(self) -> bool:
        """
        Check if the API budget has been exhausted.

        Returns
        -------
        bool
            True if api_calls_count >= api_budget.
        """
        return self._state.api_calls_count >= self._state.api_budget

    def get_current_plan(self, state: PlannerOptimizedProofState | None = None) -> OptimizationPlan | None:
        """
        Get the current optimization plan being executed.

        Parameters
        ----------
        state : PlannerOptimizedProofState | None
            Optional state to get plan from. If None, gets from active state.

        Returns
        -------
        OptimizationPlan | None
            The current plan, or None if no plans exist or all are done.
        """
        if state is None:
            state = self._get_active_state()
        if not state or not state["optimization_plans"]:
            return None
        idx = state["current_plan_index"]
        if idx >= len(state["optimization_plans"]):
            return None
        return state["optimization_plans"][idx]

    def has_pending_plans(self) -> bool:
        """
        Check if there are pending optimization plans.

        Returns
        -------
        bool
            True if there are plans yet to be executed.
        """
        state = self._get_active_state()
        if not state or not state["optimization_plans"]:
            return False
        idx = state["current_plan_index"]
        return idx < len(state["optimization_plans"])

    def advance_to_next_plan(self) -> bool:
        """
        Advance to the next optimization plan.

        This marks the current plan as completed (or skipped) and moves to the next.

        Returns
        -------
        bool
            True if advanced to a new plan, False if no more plans.
        """
        state = self._get_active_state()
        if not state:
            return False

        plans = state["optimization_plans"]
        idx = state["current_plan_index"]

        if idx < len(plans):
            # Mark current plan status if still pending
            if plans[idx]["status"] == "in_progress":
                plans[idx]["status"] = "completed"

        state["current_plan_index"] = idx + 1

        # Reset execution state for new plan
        state["self_correction_attempts"] = 0
        state["optimization_history"] = []
        state["plan_retrievals"] = []
        state["errors"] = None
        state["optimized_proof"] = None

        if state["current_plan_index"] < len(plans):
            # Update max correction attempts for the new plan
            self._update_max_correction_attempts(state)

        return state["current_plan_index"] < len(plans)

    def mark_current_plan_in_progress(self, state: PlannerOptimizedProofState | None = None) -> None:
        """Mark the current plan as in progress.

        Parameters
        ----------
        state : PlannerOptimizedProofState | None
            Optional state to mark plan in. If None, gets from active state.
        """
        plan = self.get_current_plan(state)
        if plan:
            plan["status"] = "in_progress"

    def mark_current_plan_failed(self, state: PlannerOptimizedProofState | None = None) -> None:
        """Mark the current plan as failed.

        Parameters
        ----------
        state : PlannerOptimizedProofState | None
            Optional state to mark plan in. If None, gets from active state.
        """
        plan = self.get_current_plan(state)
        if plan:
            plan["status"] = "failed"

    def mark_current_plan_completed(self, state: PlannerOptimizedProofState | None = None) -> None:
        """Mark the current plan as completed.

        Parameters
        ----------
        state : PlannerOptimizedProofState | None
            Optional state to mark plan in. If None, gets from active state.
        """
        plan = self.get_current_plan(state)
        if plan:
            plan["status"] = "completed"

    def should_replan(self, state: PlannerOptimizedProofState | None = None) -> bool:
        """
        Check if replanning should be triggered.

        Replanning happens when an improvement was made and replan count is under limit.

        Parameters
        ----------
        state : PlannerOptimizedProofState | None
            Optional state to check. If None, gets from active state.

        Returns
        -------
        bool
            True if replanning should be triggered.
        """
        if state is None:
            state = self._get_active_state()
        if not state:
            return False
        return state["replan_count"] < self._state.max_replans

    def increment_replan_count(self, state: PlannerOptimizedProofState | None = None) -> None:
        """Increment the replan counter.

        Parameters
        ----------
        state : PlannerOptimizedProofState | None
            Optional state to increment counter in. If None, gets from active state.
        """
        if state is None:
            state = self._get_active_state()
        if state:
            state["replan_count"] += 1
            logger.debug(f"Replan count: {state['replan_count']}/{self._state.max_replans}")

    def get_proofs_to_initial_optimize(self) -> PlannerOptimizedProofStates:
        """
        Get proofs waiting for initial direct optimization.

        Returns
        -------
        PlannerOptimizedProofStates
            States with proofs to optimize in the inputs field.
        """
        return {"inputs": list(self._state.planner_initial_optim_queue), "outputs": []}

    def set_initial_optimized_proofs(self, states: PlannerOptimizedProofStates) -> None:
        """
        Process proofs after initial optimization and move to compile queue.

        Parameters
        ----------
        states : PlannerOptimizedProofStates
            The optimized proof states.
        """
        self._state.planner_initial_optim_queue.clear()

        # Increment API calls for optimization
        for _ in states["outputs"]:
            self.increment_api_calls()

        # Move to compile queue
        self._state.planner_compile_queue.extend(states["outputs"])

    def get_proofs_to_plan(self) -> PlannerOptimizedProofStates:
        """
        Get proofs waiting for plan generation.

        Returns
        -------
        PlannerOptimizedProofStates
            States with proofs to plan in the inputs field.
        """
        return {"inputs": list(self._state.planner_plan_queue), "outputs": []}

    def set_planned_proofs(self, states: PlannerOptimizedProofStates) -> None:
        """
        Process proofs after planning and move to finder queue.

        Parameters
        ----------
        states : PlannerOptimizedProofStates
            The planned proof states.
        """
        self._state.planner_plan_queue.clear()

        for _ in states["outputs"]:
            self.increment_api_calls()

        for state in states["outputs"]:
            if state["optimization_plans"]:
                state["current_plan_index"] = 0
                state["optimization_plans"][0]["status"] = "in_progress"

                self._update_max_correction_attempts(state)

            self._state.planner_execute_queue.append(state)

    def get_proofs_to_find_lemmas(self) -> PlannerOptimizedProofStates:
        """
        Get proofs waiting for lemma retrieval.

        Returns
        -------
        PlannerOptimizedProofStates
            States with proofs needing retrieval in the inputs field.
        """
        return {"inputs": list(self._state.planner_find_queue), "outputs": []}

    def set_found_lemmas(self, states: PlannerOptimizedProofStates) -> None:
        """
        Process proofs after lemma retrieval and move to execute queue.

        Parameters
        ----------
        states : PlannerOptimizedProofStates
            The states with retrieved lemmas.
        """
        self._state.planner_find_queue.clear()
        self._state.planner_execute_queue.extend(states["outputs"])

    def get_proofs_to_execute(self) -> PlannerOptimizedProofStates:
        """
        Get proofs waiting for plan execution.

        Returns
        -------
        PlannerOptimizedProofStates
            States with proofs to execute in the inputs field.
        """
        return {"inputs": list(self._state.planner_execute_queue), "outputs": []}

    def set_executed_proofs(self, states: PlannerOptimizedProofStates) -> None:
        """
        Process proofs after execution and move to compile queue.

        Parameters
        ----------
        states : PlannerOptimizedProofStates
            The executed proof states.
        """
        self._state.planner_execute_queue.clear()

        # Increment API calls for execution
        for _ in states["outputs"]:
            self.increment_api_calls()

        # Move to compile queue
        self._state.planner_compile_queue.extend(states["outputs"])

    def get_proofs_to_compile(self) -> PlannerOptimizedProofStates:
        """
        Get proofs waiting to be compiled.

        Returns
        -------
        PlannerOptimizedProofStates
            States with proofs to compile in the inputs field.
        """
        return {"inputs": list(self._state.planner_compile_queue), "outputs": []}

    def set_compiled_proofs(self, states: PlannerOptimizedProofStates) -> None:
        """
        Process compiled proofs and route based on compilation result.

        If compilation succeeded:
        - Update shortest proof if this is shorter
        - If improvement made, trigger replan (go back to planner)
        - If no improvement, advance to next plan (go to finder)

        If compilation failed:
        - Queue for correction

        Parameters
        ----------
        states : PlannerOptimizedProofStates
            The compiled proof states.
        """
        self._state.planner_compile_queue.clear()

        for state in states["outputs"]:
            if state["compiled"]:
                # Compilation succeeded
                optimized = state["optimized_proof"]
                made_improvement = False

                if optimized:
                    new_length = proof_length(optimized)

                    # Record this compiled proof in history
                    compiled_record: CompiledProofRecord = {
                        "proof": optimized,
                        "length": new_length,
                        "api_call_count": self._state.api_calls_count,
                    }
                    state["compiled_proofs_history"].append(compiled_record)

                    # Update shortest if this is shorter and record improvement
                    if new_length < state["shortest_proof_length"]:
                        print(
                            f"New shortest proof: {state['shortest_proof_length']} --> {new_length} tokens", flush=True
                        )
                        # Capture the proof BEFORE this optimization for replan context
                        state["previous_proof_before_replan"] = state["current_proof"]
                        state["shortest_proof"] = optimized
                        state["shortest_proof_length"] = new_length
                        state["improvements_history"].append(compiled_record)
                        made_improvement = True
                        # Update current_proof to the improved version for next round
                        state["current_proof"] = optimized
                        # Track the successful plan (copy to avoid mutation)
                        current_plan = self.get_current_plan(state)
                        if current_plan:
                            # Create a copy and mark it as completed before adding to successful_plans
                            successful_plan = dict(current_plan)
                            successful_plan["status"] = "completed"
                            state["successful_plans"].append(successful_plan)  # type: ignore[arg-type]
                            state["total_plans_improved"] += 1
                        else:
                            logger.warning(
                                f"{state['original_proof'][: min(50, len(state['original_proof']))]}...: Improvement made during initial optimization, but current plan not found"
                            )

                if getattr(self._state, "in_initial_optimization", False):
                    self._state.in_initial_optimization = False

                    if not made_improvement:
                        state["current_proof"] = state["shortest_proof"]

                    # Reset execution state
                    state["self_correction_attempts"] = 0
                    state["errors"] = None
                    state["optimization_history"] = []

                    # Move to planning queue
                    self._state.planner_plan_queue.append(state)
                    logger.info("Initial optimization complete - moving to planning phase")
                    continue

                # Track plan execution count
                state["total_plans_tried"] += 1
                state["current_round_plans_tried"] += 1

                # Mark current plan completed
                self.mark_current_plan_completed(state)

                # Reset execution state
                state["self_correction_attempts"] = 0
                state["errors"] = None
                state["optimization_history"] = []
                state["plan_retrievals"] = []

                if made_improvement and self.should_replan(state):
                    self.increment_replan_count(state)

                    state["last_round_plans"] = [dict(plan) for plan in state["optimization_plans"]]
                    state["planner_history"] = []
                    state["optimization_plans"] = []
                    state["current_plan_index"] = 0
                    state["current_round_plans_tried"] = 0
                    self._state.planner_plan_queue.append(state)
                    logger.info("Improvement made - triggering replan")
                else:
                    state["current_plan_index"] += 1
                    if state["current_plan_index"] < len(state["optimization_plans"]):
                        state["optimization_plans"][state["current_plan_index"]]["status"] = "in_progress"

                        self._state.planner_execute_queue.append(state)
                    else:
                        # All plans exhausted without improvement
                        if state["replan_count"] < self.min_replans:
                            # Force replan if under min limit
                            self.increment_replan_count(state)

                            state["last_round_plans"] = [
                                dict(plan)
                                for plan in state["optimization_plans"]  # type: ignore[arg-type]
                            ]
                            state["planner_history"] = []
                            state["optimization_plans"] = []
                            state["current_plan_index"] = 0
                            state["current_round_plans_tried"] = 0  # Reset round counter
                            self._state.planner_plan_queue.append(state)
                            logger.warning(
                                f"Triggering forced replan (attempt {state['replan_count']}/{self.min_replans})"
                            )
                        else:
                            # All plans exhausted without improvement - cache final state and finish
                            # Don't replan - we only replan after making an improvement
                            # Don't add to any queue - supervisor will detect empty queues and finish
                            if not self._state.final_state:
                                self._state.final_state = state.copy()
                            logger.warning("All plans exhausted without further improvements - finishing")
            else:
                # Compilation failed - queue for correction
                self._state.planner_correct_queue.append(state)

    # =========================================================================
    # Queue Access Methods - Corrector Agent
    # =========================================================================

    def get_proofs_to_correct(self) -> PlannerOptimizedProofStates:
        """
        Get proofs with compilation errors waiting to be corrected.

        Returns
        -------
        PlannerOptimizedProofStates
            States with proofs to correct in the inputs field.
        """
        return {"inputs": list(self._state.planner_correct_queue), "outputs": []}

    def set_corrected_proofs(self, states: PlannerOptimizedProofStates) -> None:
        """
        Process corrected proofs and route for re-execution.

        Parameters
        ----------
        states : PlannerOptimizedProofStates
            The corrected proof states.
        """
        self._state.planner_correct_queue.clear()

        # Check if we are in initial optimization
        if getattr(self._state, "in_initial_optimization", False):
            self._state.planner_initial_optim_queue.extend(states["outputs"])
        else:
            # Re-queue for execution (not optimize - for targeted plan execution)
            self._state.planner_execute_queue.extend(states["outputs"])

    def should_correct(self) -> bool:
        """
        Check if correction should be attempted.

        Returns
        -------
        bool
            True if there are proofs to correct and attempts remain.
        """
        if not self._state.planner_correct_queue:
            return False
        state = self._state.planner_correct_queue[0]
        return state["self_correction_attempts"] < self._state.max_correction_attempts

    def should_skip_to_next_plan(self) -> bool:
        """
        Check if we should skip to the next plan after correction exhaustion.

        Returns
        -------
        bool
            True if correction attempts exhausted and we should skip to next plan.
        """
        if not self._state.planner_correct_queue:
            return False
        state = self._state.planner_correct_queue[0]
        return state["self_correction_attempts"] >= self._state.max_correction_attempts

    def skip_current_plan_and_advance(self) -> None:
        """
        Skip the current plan after correction exhaustion and advance to next.

        This is called when correction attempts are exhausted for a plan.
        The state is reset to the most recent correct proof and we try the next plan.
        """
        if not self._state.planner_correct_queue:
            return

        state = self._state.planner_correct_queue.pop(0)

        # Check if we are in initial optimization
        if getattr(self._state, "in_initial_optimization", False):
            self._state.in_initial_optimization = False

            # Revert to shortest proof (since correction failed)
            state["current_proof"] = state["shortest_proof"]

            # Reset execution state
            state["optimized_proof"] = None
            state["compiled"] = False
            state["errors"] = None
            state["self_correction_attempts"] = 0
            state["optimization_history"] = []

            # Move to planning queue
            self._state.planner_plan_queue.append(state)
            logger.warning("Initial optimization failed after corrections - moving to planning phase")
            return

        # Mark current plan as failed
        self.mark_current_plan_failed(state)

        # Reset to current_proof (most recent correct version)
        # Note: current_proof should already be the last correct state
        state["optimized_proof"] = None
        state["compiled"] = False
        state["errors"] = None
        state["self_correction_attempts"] = 0
        state["optimization_history"] = []
        state["plan_retrievals"] = []

        # Advance to next plan
        state["current_plan_index"] += 1

        if state["current_plan_index"] < len(state["optimization_plans"]):
            # More plans to try
            state["optimization_plans"][state["current_plan_index"]]["status"] = "in_progress"

            # Update max correction attempts for the new plan
            self._update_max_correction_attempts(state)

            # self._state.planner_find_queue.append(state)
            self._state.planner_execute_queue.append(state)
            logger.debug(f"Skipping to plan {state['current_plan_index'] + 1}/{len(state['optimization_plans'])}")
        else:
            # All plans exhausted
            if state["replan_count"] < self.min_replans:
                # Force replan if under min limit
                self.increment_replan_count(state)

                state["last_round_plans"] = [
                    dict(plan)
                    for plan in state["optimization_plans"]  # type: ignore[arg-type]
                ]
                state["planner_history"] = []

                state["optimization_plans"] = []
                state["current_plan_index"] = 0
                state["current_round_plans_tried"] = 0  # Reset round counter
                self._state.planner_plan_queue.append(state)
                logger.info(f"Triggering forced replan (attempt {state['replan_count']}/{self.min_replans})")
            else:
                # All plans exhausted - no replanning, just finish
                if not self._state.final_state:
                    self._state.final_state = state.copy()
                logger.info("All plans exhausted - correction phase done")

    def _get_active_state(self) -> PlannerOptimizedProofState | None:
        """
        Get the active state from any queue, or the cached final state.

        Returns
        -------
        PlannerOptimizedProofState | None
            The active state, or None if no state exists.
        """
        for queue in [
            self._state.planner_plan_queue,
            self._state.planner_initial_optim_queue,
            self._state.planner_find_queue,
            self._state.planner_execute_queue,
            self._state.planner_compile_queue,
            self._state.planner_correct_queue,
        ]:
            if queue:
                return queue[0]
        return self._state.final_state

    def get_final_result(self) -> tuple[str, int]:
        """
        Get the final optimization result.

        Returns
        -------
        tuple[str, int]
            A tuple of (shortest_proof, shortest_proof_length).
        """
        state = self._get_active_state()
        if state:
            return state["shortest_proof"], state["shortest_proof_length"]
        return "", 0

    def reconstruct_complete_proof(self) -> str:
        """
        Get the complete optimized proof.

        Returns
        -------
        str
            The shortest valid proof found during optimization.
        """
        shortest, _ = self.get_final_result()
        return shortest

    def get_compiled_proofs_history(self) -> list[CompiledProofRecord]:
        """
        Get the history of all successfully compiled proofs.

        Returns
        -------
        list[CompiledProofRecord]
            List of all compiled proofs in discovery order.
        """
        state = self._get_active_state()
        if state:
            return state["compiled_proofs_history"]
        return []

    def get_improvements_history(self) -> list[CompiledProofRecord]:
        """
        Get the history of proofs that were improvements.

        Returns
        -------
        list[CompiledProofRecord]
            List of improvement proofs in discovery order.
        """
        state = self._get_active_state()
        if state:
            return state["improvements_history"]
        return []

    def get_successful_plans(self) -> list[OptimizationPlan]:
        """
        Get all plans that led to improvements across all rounds.

        Returns
        -------
        list[OptimizationPlan]
            List of successful plans.
        """
        state = self._get_active_state()
        if state:
            return state["successful_plans"]
        return []

    def get_all_generated_plans_history(self) -> list[list[OptimizationPlan]]:
        """
        Get the history of all generated plans from every round.

        Returns
        -------
        list[list[OptimizationPlan]]
            List of lists of plans, one list per planning round.
        """
        state = self._get_active_state()
        if state:
            return state["all_generated_plans_history"]
        return []

    def cache_final_state(self) -> None:
        """
        Cache the current state for post-workflow access.
        """
        state = self._get_active_state()
        if state and not self._state.final_state:
            self._state.final_state = state.copy()

    def has_any_pending_work(self) -> bool:
        """
        Check if there is any pending work in any queue.

        Returns
        -------
        bool
            True if any queue has items.
        """
        return bool(
            self._state.planner_plan_queue
            or self._state.planner_initial_optim_queue
            or self._state.planner_find_queue
            or self._state.planner_execute_queue
            or self._state.planner_compile_queue
            or self._state.planner_correct_queue
        )
