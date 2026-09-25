"""
Planner Corrector Agent for planner-based proof optimization workflow.

This agent prepares correction prompts for proofs that failed compilation,
adding error context to the optimization history for the executer agent to retry.
"""

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from lean_refactor.agents.state import PlannerOptimizedProofState, PlannerOptimizedProofStates
from lean_refactor.agents.util.common import load_prompt
from lean_refactor.agents.util.debug import log_llm_prompt


class PlannerCorrectorAgentFactory:
    """
    Factory class for creating instances of the PlannerCorrectorAgent.
    """

    @staticmethod
    def create_agent() -> CompiledStateGraph:
        """
        Creates a PlannerCorrectorAgent instance.

        Returns
        -------
        CompiledStateGraph
            A CompiledStateGraph instance of the planner corrector agent.
        """
        return _build_agent()


def _build_agent() -> CompiledStateGraph:
    """
    Builds a compiled state graph for the planner corrector agent.

    Returns
    -------
    CompiledStateGraph
        The compiled state graph for the planner corrector agent.
    """
    graph_builder = StateGraph(PlannerOptimizedProofStates)

    # Add the nodes
    graph_builder.add_node("planner_corrector_agent", _corrector)

    # Add the edges
    graph_builder.add_conditional_edges(START, _map_edge, ["planner_corrector_agent"])
    graph_builder.add_edge("planner_corrector_agent", END)

    return graph_builder.compile()


def _map_edge(states: PlannerOptimizedProofStates) -> list[Send]:
    """
    Map edge that dispatches states to planner_corrector_agent nodes.

    Parameters
    ----------
    states : PlannerOptimizedProofStates
        The states containing proofs to correct.

    Returns
    -------
    list[Send]
        List of Send objects for each proof to correct.
    """
    return [Send("planner_corrector_agent", state) for state in states["inputs"]]


def _corrector(state: PlannerOptimizedProofState) -> PlannerOptimizedProofStates:
    """
    Adds a HumanMessage to the optimization_history indicating a request for correction
    with error details. This prepares the state for the executer agent to retry.

    Parameters
    ----------
    state : PlannerOptimizedProofState
        The state with compilation errors to correct.

    Returns
    -------
    PlannerOptimizedProofStates
        States with updated optimization_history in the outputs field.
    """
    # Increment correction attempts
    state["self_correction_attempts"] += 1

    # Construct the correction prompt (reuse existing optimizer-corrector template)
    prompt = load_prompt(
        "optimizer-corrector",
        prev_round_num=str(state["self_correction_attempts"]),
        error_message=str(state["errors"]),
        use_tactic_style=state.get("use_tactic_style", False),
    )

    # Log debug prompt
    log_llm_prompt("PLANNER_CORRECTOR_AGENT", prompt, "optimizer-corrector")

    # Add correction request to the optimization history
    state["optimization_history"].append(HumanMessage(content=prompt))

    return {"outputs": [state]}  # type: ignore[typeddict-item]
