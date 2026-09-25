"""
Initial Optimizer Agent for planner-based proof optimization workflow.

This agent attempts to directly simplify the proof using a specific prompt
before the main planning loop begins.
"""

from functools import partial

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from lean_refactor.agents.state import (
    PlannerOptimizedProofState,
    PlannerOptimizedProofStates,
)
from lean_refactor.agents.util.common import LLMParsingError, TokenTracker, get_llm_response_content, load_prompt
from lean_refactor.agents.util.debug import log_llm_prompt, log_llm_response
from lean_refactor.utils import extract_code, is_tactic_style_proof, replace_statement_in_proof_mathlib_style


class InitialOptimizerAgentFactory:
    """
    Factory class for creating instances of the InitialOptimizerAgent.
    """

    @staticmethod
    def create_agent(
        llm: BaseChatModel,
        token_tracker: TokenTracker | None = None,
        use_tactic_style: bool = False,
    ) -> CompiledStateGraph:
        """
        Creates an InitialOptimizerAgent instance with the passed llm.

        Parameters
        ----------
        llm : BaseChatModel
            The LLM to use for the initial optimizer agent.
        token_tracker : TokenTracker | None
            Optional token tracker for recording LLM token usage.
        use_tactic_style : bool
            Whether to enforce tactic-mode proof style.

        Returns
        -------
        CompiledStateGraph
            A CompiledStateGraph instance of the initial optimizer agent.
        """
        return _build_agent(llm=llm, token_tracker=token_tracker, use_tactic_style=use_tactic_style)


def _build_agent(
    llm: BaseChatModel,
    token_tracker: TokenTracker | None = None,
    use_tactic_style: bool = False,
) -> CompiledStateGraph:
    """
    Builds a compiled state graph for the initial optimizer agent.

    Parameters
    ----------
    llm : BaseChatModel
        The LLM to use for the agent.
    token_tracker : TokenTracker | None
        Optional token tracker for recording LLM token usage.

    Returns
    -------
    CompiledStateGraph
        The compiled state graph for the agent.
    """
    graph_builder = StateGraph(PlannerOptimizedProofStates)

    # Bind the llm and token_tracker arguments
    bound_agent = partial(_initial_optimizer, llm, token_tracker, use_tactic_style)

    # Add the nodes
    graph_builder.add_node("initial_optimizer_agent", bound_agent)

    # Add the edges
    graph_builder.add_conditional_edges(START, _map_edge, ["initial_optimizer_agent"])
    graph_builder.add_edge("initial_optimizer_agent", END)

    return graph_builder.compile()


def _map_edge(states: PlannerOptimizedProofStates) -> list[Send]:
    """
    Map edge that dispatches states to the initial_optimizer_agent nodes.
    """
    return [Send("initial_optimizer_agent", state) for state in states["inputs"]]


def _initial_optimizer(
    llm: BaseChatModel,
    token_tracker: TokenTracker | None,
    use_tactic_style: bool,
    state: PlannerOptimizedProofState,
) -> PlannerOptimizedProofStates:
    """
    Attempt to directly simplify the proof.

    Parameters
    ----------
    llm : BaseChatModel
        The LLM to use.
    token_tracker : TokenTracker | None
        Optional token tracker.
    state : PlannerOptimizedProofState
        The state with the proof to optimize.

    Returns
    -------
    PlannerOptimizedProofStates
        A PlannerOptimizedProofStates with the optimized state in outputs.
    """
    # Check if this is a fresh execution or correction attempt
    # For initial optimization, optimization_history tracks the conversation for this phase
    if not state.get("optimization_history"):
        # Fresh execution - build initial prompt
        prompt_kwargs = {
            "current_proof": state["current_proof"],
        }

        # Add optional fields if present
        if state.get("signature"):
            prompt_kwargs["signature"] = state["signature"]
        if state.get("doc_string"):
            prompt_kwargs["informalization"] = state["doc_string"]
        if state.get("dependencies"):
            prompt_kwargs["dependencies"] = state["dependencies"]

        prompt = load_prompt(
            "planner-optimizer-direct",
            use_tactic_style=use_tactic_style or state.get("use_tactic_style", False),
            **prompt_kwargs,
        )
        log_llm_prompt("INITIAL_OPTIMIZER_AGENT", prompt, "planner-optimizer-direct")

        # Start fresh history with the prompt
        state["optimization_history"] = [HumanMessage(content=prompt)]
    # else: correction prompt was already added by the corrector agent

    # Invoke the LLM
    response_content = get_llm_response_content(
        llm,
        llm.invoke(state["optimization_history"]),
        token_tracker=token_tracker,
        agent_name="InitialOptimizerAgent",
    )
    log_llm_response("INITIAL_OPTIMIZER_AGENT_LLM", str(response_content))

    # Parse response
    try:
        extracted_code = _parse_response(str(response_content))

        # Protect the statement from being changed by the LLM
        protected_proof = replace_statement_in_proof_mathlib_style(
            statement=state["original_proof"],
            proof=extracted_code,
        )
        log_llm_response("INITIAL_OPTIMIZER_AGENT", protected_proof, "protected_optimized_proof")

        # Check if the replacement function returned an error
        if protected_proof.startswith("**Error**"):
            state["optimized_proof"] = None
            state["errors"] = f"Output Lean 4 code error: {protected_proof}"
        else:
            # Successfully protected - use the protected proof
            state["optimized_proof"] = protected_proof
            state["errors"] = None

            # Validate tactic-mode style if required
            effective_tactic_style = use_tactic_style or state.get("use_tactic_style", False)
            if effective_tactic_style and not is_tactic_style_proof(protected_proof):
                state["optimized_proof"] = None
                state["errors"] = (
                    "The proof is compiled correctly, butTactic-mode constraint violated: the optimized proof does not start with ':= by'. "
                    "Please rewrite the proof in tactic mode, ensuring the proof body begins with ':= by' "
                    "followed by tactic commands."
                )

        # Add the response to history
        state["optimization_history"].append(AIMessage(content=str(response_content)))

    except LLMParsingError:
        # Set parse failure markers
        state["optimized_proof"] = None
        state["errors"] = (
            "Malformed LLM response: unable to parse optimized proof from LLM output. "
            "The response did not contain a valid Lean4 code block."
        )

    return {"outputs": [state]}  # type: ignore[typeddict-item]


def _parse_response(response: str) -> str:
    """
    Extract the optimized proof from the LLM response.
    """
    extracted = extract_code(response)
    if extracted == "None":
        raise LLMParsingError("Failed to extract code block from LLM response", response)
    return extracted
