"""
Planner Optimizer Supervisor Agent for planner-based proof optimization workflow.

This agent determines which action to take next based on the current optimization state,
managing the multi-agent workflow: plan → find → execute → compile → (correct if needed).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lean_refactor.planner_optimizer_state import PlannerOptimizerStateManager


class PlannerOptimizerSupervisorAgentFactory:
    """
    Factory class for creating instances of the PlannerOptimizerSupervisorAgent.
    """

    @staticmethod
    def create_agent(state_manager: PlannerOptimizerStateManager) -> PlannerOptimizerSupervisorAgent:
        """
        Creates a PlannerOptimizerSupervisorAgent instance.

        Parameters
        ----------
        state_manager : PlannerOptimizerStateManager
            The state manager to be used by the agent.

        Returns
        -------
        PlannerOptimizerSupervisorAgent
            An instance of the supervisor agent.
        """
        return PlannerOptimizerSupervisorAgent(state_manager=state_manager)


class PlannerOptimizerSupervisorAgent:
    """
    The supervisor that determines which action to take next based upon the current state.

    This agent orchestrates the planner-based optimization workflow:
    plan → find → execute → compile → (correct if needed) → repeat.

    The action returned is the name of the method on PlannerOptimizerFramework that should be called.
    """

    def __init__(self, state_manager: PlannerOptimizerStateManager):
        """
        Initialize the supervisor agent.

        Parameters
        ----------
        state_manager : PlannerOptimizerStateManager
            The state manager to query for determining next action.
        """
        self._state_manager = state_manager

    def get_action(self) -> str:
        """
        Gets the next action to perform based upon the current state.

        The priority order is:
        1. Check if there are proofs to compile → compile_proofs (prioritized, no budget needed)
        2. Check if there are proofs for initial optimization → initial_optimize
        3. Check if budget is exhausted → finish (after compilation completes)
        4. Check if there are proofs to execute → execute_plans
        5. Check if there are proofs to find lemmas for → find_lemmas
        6. Check if there are proofs to plan → plan_proofs
        7. Check if there are proofs to correct:
           - If correction attempts remain → correct_proofs
           - If correction exhausted → skip_to_next_plan
        8. Otherwise → finish

        Returns
        -------
        str
            The name of the action to perform.
        """
        # 1. Prioritize compilation (always complete even if budget exhausted)
        if self._state_manager.get_proofs_to_compile()["inputs"]:
            return "compile_proofs"

        # 2. Check for initial optimization (prioritized before budget check to ensure it runs)
        if self._state_manager.get_proofs_to_initial_optimize()["inputs"]:
            return "initial_optimize"

        # 3. Check if budget is exhausted
        if self._state_manager.is_budget_exhausted() or self._state_manager.shortest_proof_length <= 2:
            self._state_manager.is_finished = True
            self._state_manager.reason = "API budget exhausted. All pending compilations completed."
            return "finish"

        # 4. Check for proofs to execute
        if self._state_manager.get_proofs_to_execute()["inputs"]:
            return "execute_plans"

        # 4. Check for proofs to find lemmas for
        # if self._state_manager.get_proofs_to_find_lemmas()["inputs"]:
        #     return "find_lemmas"

        # 5. Check for proofs to plan
        plan_inputs = self._state_manager.get_proofs_to_plan()["inputs"]
        if plan_inputs:
            # Check if we actually need to plan (has no plans yet or is replanning)
            state = plan_inputs[0]
            if not state["optimization_plans"]:
                return "plan_proofs"
            else:
                # Has plans but in plan queue - might be finished
                if not self._state_manager.has_pending_plans():
                    # All plans executed, no replans possible - finish
                    self._state_manager.is_finished = True
                    self._state_manager.reason = "All optimization plans completed."
                    return "finish"
                else:
                    # Should move to find queue
                    return "plan_proofs"

        # 6. Check for proofs to correct
        if self._state_manager.get_proofs_to_correct()["inputs"]:
            if self._state_manager.should_correct():
                return "correct_proofs"
            elif self._state_manager.should_skip_to_next_plan():
                return "skip_to_next_plan"
            else:
                # Unexpected state
                self._state_manager.is_finished = True
                self._state_manager.reason = "Correction state error. This should not happen."
                return "finish"

        # 7. No pending work - finish
        self._state_manager.is_finished = True
        self._state_manager.reason = "Optimization completed successfully."
        return "finish"
