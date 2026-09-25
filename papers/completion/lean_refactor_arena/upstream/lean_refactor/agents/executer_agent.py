"""
Executer Agent for planner-based proof optimization workflow.

This agent takes the current optimization plan with retrieved lemmas and
generates a targeted proof modification according to the plan.
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
from lean_refactor.utils import (
    extract_code,
    is_tactic_style_proof,
    replace_statement_in_proof_goedel_style,
    replace_statement_in_proof_mathlib_style,
)


class ExecuterAgentFactory:
    """
    Factory class for creating instances of the ExecuterAgent.
    """

    @staticmethod
    def create_agent(
        llm: BaseChatModel,
        token_tracker: TokenTracker | None = None,
        compiler: str = "lean_client",
        use_tactic_style: bool = False,
    ) -> CompiledStateGraph:
        """
        Creates an ExecuterAgent instance with the passed llm.

        Parameters
        ----------
        llm : BaseChatModel
            The LLM to use for the executer agent.
        token_tracker : TokenTracker | None
            Optional token tracker for recording LLM token usage.
        compiler : str
            The compiler backend being used ("lean_client" or "repl").
        use_tactic_style : bool
            Whether to enforce tactic-mode proof style.

        Returns
        -------
        CompiledStateGraph
            A CompiledStateGraph instance of the executer agent.
        """
        return _build_agent(llm=llm, token_tracker=token_tracker, compiler=compiler, use_tactic_style=use_tactic_style)


def _build_agent(
    llm: BaseChatModel,
    token_tracker: TokenTracker | None = None,
    compiler: str = "lean_client",
    use_tactic_style: bool = False,
) -> CompiledStateGraph:
    """
    Builds a compiled state graph for the executer agent.

    Parameters
    ----------
    llm : BaseChatModel
        The LLM to use for the executer agent.
    token_tracker : TokenTracker | None
        Optional token tracker for recording LLM token usage.
    compiler : str
        The compiler backend being used.

    Returns
    -------
    CompiledStateGraph
        The compiled state graph for the executer agent.
    """
    graph_builder = StateGraph(PlannerOptimizedProofStates)

    # Bind the llm and token_tracker arguments
    bound_executer = partial(_executer, llm, token_tracker, compiler, use_tactic_style)

    # Add the nodes
    graph_builder.add_node("executer_agent", bound_executer)

    # Add the edges
    graph_builder.add_conditional_edges(START, _map_edge, ["executer_agent"])
    graph_builder.add_edge("executer_agent", END)

    return graph_builder.compile()


def _map_edge(states: PlannerOptimizedProofStates) -> list[Send]:
    """
    Map edge that dispatches states to the executer_agent nodes.

    Parameters
    ----------
    states : PlannerOptimizedProofStates
        The states to process.

    Returns
    -------
    list[Send]
        List of Send objects for each input state.
    """
    return [Send("executer_agent", state) for state in states["inputs"]]


def _get_proof_section(proof: str, line_start: int, line_end: int) -> str:
    """
    Extract a section of the proof by line numbers.

    Parameters
    ----------
    proof : str
        The full proof text.
    line_start : int
        Starting line number (1-indexed).
    line_end : int
        Ending line number (1-indexed, inclusive).

    Returns
    -------
    str
        The extracted proof section.
    """
    lines = proof.split("\n")
    start_idx = max(0, line_start - 1)
    end_idx = min(len(lines), line_end)
    return "\n".join(lines[start_idx:end_idx])


def _executer(
    llm: BaseChatModel,
    token_tracker: TokenTracker | None,
    compiler: str,
    use_tactic_style: bool,
    state: PlannerOptimizedProofState,
) -> PlannerOptimizedProofStates:
    """
    Execute the current optimization plan.

    Parameters
    ----------
    llm : BaseChatModel
        The LLM to use for the executer agent.
    token_tracker : TokenTracker | None
        Optional token tracker for recording LLM token usage.
    compiler : str
        The compiler backend being used.
    state : PlannerOptimizedProofState
        The state with the plan to execute.

    Returns
    -------
    PlannerOptimizedProofStates
        A PlannerOptimizedProofStates with the executed state in outputs.
    """
    # Get current plan
    plans = state["optimization_plans"]
    idx = state["current_plan_index"]

    if idx >= len(plans):
        # No current plan - return unchanged
        state["optimized_proof"] = None
        state["errors"] = "No optimization plan to execute"
        return {"outputs": [state]}  # type: ignore[typeddict-item]

    current_plan = plans[idx]

    # Extract the relevant proof section
    # proof_section = _get_proof_section(
    #     state["current_proof"],
    #     current_plan["line_start"],
    #     current_plan["line_end"],
    # )

    # Format retrieved lemmas
    # formatted_lemmas = format_retrieved_lemmas(state["plan_retrievals"])

    # Check if this is a fresh execution or correction attempt
    if state["errors"] is None or not state["optimization_history"]:
        # Fresh execution - build initial prompt
        prompt_kwargs = {
            "current_proof": state["current_proof"],
            # "proof_section": proof_section,
            "line_start": str(current_plan["line_start"]),
            "line_end": str(current_plan["line_end"]),
            "title": current_plan["title"],
            "plan_description": current_plan["description"],
            # "retrieved_lemmas": formatted_lemmas,
        }

        # Add optional fields if present
        if state.get("signature"):
            prompt_kwargs["signature"] = state["signature"]
        if state.get("doc_string"):
            prompt_kwargs["informalization"] = state["doc_string"]
        if state.get("dependencies"):
            prompt_kwargs["dependencies"] = state["dependencies"]

        prompt = load_prompt(
            "executer-initial",
            use_tactic_style=use_tactic_style or state.get("use_tactic_style", False),
            **prompt_kwargs,
        )
        log_llm_prompt("EXECUTER_AGENT", prompt, "executer-initial")

        # Start fresh history with the prompt
        state["optimization_history"] = [HumanMessage(content=prompt)]
    # else: correction prompt was already added by the corrector agent

    # Invoke the LLM
    response_content = get_llm_response_content(
        llm,
        llm.invoke(state["optimization_history"]),
        token_tracker=token_tracker,
        agent_name="ExecuterAgent",
    )
    log_llm_response("EXECUTER_AGENT_LLM", str(response_content))

    # Parse executer response
    try:
        extracted_code = _parse_executer_response(str(response_content))

        # Protect the statement from being changed by the LLM
        if compiler == "repl":
            protected_proof = replace_statement_in_proof_goedel_style(
                statement=state["original_proof"],
                proof=extracted_code,
            )
        else:
            protected_proof = replace_statement_in_proof_mathlib_style(
                statement=state["original_proof"],
                proof=extracted_code,
            )
        log_llm_response("EXECUTER_AGENT", protected_proof, f"protected_optimized_proof_{compiler}_style")

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
                    "The proof is compiled correctly, but Tactic-mode constraint violated: the optimized proof does not start with ':= by'. "
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


def _parse_executer_response(response: str) -> str:
    """
    Extract the optimized proof from the LLM response.

    Parameters
    ----------
    response : str
        The LLM response containing the optimized proof.

    Returns
    -------
    str
        The extracted optimized proof.

    Raises
    ------
    LLMParsingError
        If no code block is found in the response.
    """
    extracted = extract_code(response)
    if extracted == "None":
        raise LLMParsingError("Failed to extract code block from LLM response", response)
    return extracted
