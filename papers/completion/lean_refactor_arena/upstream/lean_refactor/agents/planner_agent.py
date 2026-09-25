"""
Planner Agent for planner-based proof optimization workflow.

This agent analyzes a proof and generates structured optimization plans,
each targeting a specific region of the proof with a defined strategy.
"""

import json
import re
from functools import partial

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from lean_refactor.agents.state import (
    OptimizationPlan,
    PlannerOptimizedProofState,
    PlannerOptimizedProofStates,
)
from lean_refactor.agents.util.common import LLMParsingError, TokenTracker, get_llm_response_content, load_prompt
from lean_refactor.agents.util.debug import log_llm_prompt, log_llm_response


class PlannerAgentFactory:
    """
    Factory class for creating instances of the PlannerAgent.
    """

    @staticmethod
    def create_agent(
        llm: BaseChatModel,
        token_tracker: TokenTracker | None = None,
        use_tactic_style: bool = False,
    ) -> CompiledStateGraph:
        """
        Creates a PlannerAgent instance with the passed llm.

        Parameters
        ----------
        llm : BaseChatModel
            The LLM to use for the planner agent.
        token_tracker : TokenTracker | None
            Optional token tracker for recording LLM token usage.
        use_tactic_style : bool
            Whether to enforce tactic-mode proof style.

        Returns
        -------
        CompiledStateGraph
            A CompiledStateGraph instance of the planner agent.
        """
        return _build_agent(llm=llm, token_tracker=token_tracker, use_tactic_style=use_tactic_style)


def _build_agent(
    llm: BaseChatModel,
    token_tracker: TokenTracker | None = None,
    use_tactic_style: bool = False,
) -> CompiledStateGraph:
    """
    Builds a compiled state graph for the planner agent.

    Parameters
    ----------
    llm : BaseChatModel
        The LLM to use for the planner agent.
    token_tracker : TokenTracker | None
        Optional token tracker for recording LLM token usage.

    Returns
    -------
    CompiledStateGraph
        The compiled state graph for the planner agent.
    """
    graph_builder = StateGraph(PlannerOptimizedProofStates)

    # Bind the llm and token_tracker arguments
    bound_planner = partial(_planner, llm, token_tracker, use_tactic_style)

    # Add the nodes
    graph_builder.add_node("planner_agent", bound_planner)

    # Add the edges
    graph_builder.add_conditional_edges(START, _map_edge, ["planner_agent"])
    graph_builder.add_edge("planner_agent", END)

    return graph_builder.compile()


def _map_edge(states: PlannerOptimizedProofStates) -> list[Send]:
    """
    Map edge that takes the members of the states["inputs"] list and dispatches them to the
    planner_agent nodes.

    Parameters
    ----------
    states : PlannerOptimizedProofStates
        The PlannerOptimizedProofStates containing in the "inputs" member the
        PlannerOptimizedProofState instances to plan.

    Returns
    -------
    list[Send]
        List of Send objects each indicating their target node and its input.
    """
    return [Send("planner_agent", state) for state in states["inputs"]]


def _is_replan(state: PlannerOptimizedProofState) -> bool:
    """
    Detect if this is a replan (after successful optimization).

    Parameters
    ----------
    state : PlannerOptimizedProofState
        The state to check.

    Returns
    -------
    bool
        True if this is a replan, False if initial planning.
    """
    # With hybrid history management, planner_history is cleared on replan,
    # so we only check replan_count to detect replans
    return state["replan_count"] > 0


def _planner(
    llm: BaseChatModel,
    token_tracker: TokenTracker | None,
    use_tactic_style: bool,
    state: PlannerOptimizedProofState,
) -> PlannerOptimizedProofStates:
    """
    Generate optimization plans for the proof.

    Parameters
    ----------
    llm : BaseChatModel
        The LLM to use for the planner agent.
    token_tracker : TokenTracker | None
        Optional token tracker for recording LLM token usage.
    state : PlannerOptimizedProofState
        The state with the proof to plan optimizations for.

    Returns
    -------
    PlannerOptimizedProofStates
        A PlannerOptimizedProofStates with the planned state in outputs.
    """
    is_replan = _is_replan(state)

    # Build prompt kwargs
    prompt_kwargs = {"current_proof": state["current_proof"]}

    # Add optional fields if present
    if state.get("signature"):
        prompt_kwargs["signature"] = state["signature"]
    if state.get("doc_string"):
        prompt_kwargs["informalization"] = state["doc_string"]
    if state.get("dependencies"):
        prompt_kwargs["dependencies"] = state["dependencies"]

    if is_replan:
        # Include the proof BEFORE the successful optimization that triggered replan
        if state.get("previous_proof_before_replan"):
            prompt_kwargs["previous_proof"] = state["previous_proof_before_replan"]

        if state.get("last_round_plans"):
            last_round_plans_str = "\n".join(
                f"[{p['status'].upper()}] Title: {p['title']}\nLines {p['line_start']}-{p['line_end']}\nDescription: {p['description']}\n\n"
                for p in state["last_round_plans"]
            )
            prompt_kwargs["last_round_plans"] = last_round_plans_str

        # if state.get("successful_plans"):
        #     # Format all successful plans for context
        #     successful_plans_str = "\n".join(
        #         f"- Title: {p['title']}, Lines {p['line_start']}-{p['line_end']}: {p['description']}"
        #         for p in state["successful_plans"]
        #     )
        #     prompt_kwargs["successful_plans"] = successful_plans_str

        prompt_name = "planner-update"
        prompt = load_prompt(
            prompt_name, use_tactic_style=use_tactic_style or state.get("use_tactic_style", False), **prompt_kwargs
        )
        log_llm_prompt("PLANNER_AGENT", prompt, prompt_name)
    else:
        # Initial planning
        prompt_name = "planner-initial"
        prompt = load_prompt(
            prompt_name, use_tactic_style=use_tactic_style or state.get("use_tactic_style", False), **prompt_kwargs
        )
        log_llm_prompt("PLANNER_AGENT", prompt, prompt_name)

    state["planner_history"] = []  # Reset planner history for this round, we don't keep prior history

    # Add prompt to history
    state["planner_history"].append(HumanMessage(content=prompt))

    # Retry loop for parsing failures
    max_parse_retries = 30
    last_error: LLMParsingError | None = None
    response_content: str = ""

    for attempt in range(max_parse_retries):
        # Invoke LLM with current round's history only (fresh context per replan)
        raw_response = get_llm_response_content(
            llm,
            llm.invoke(state["planner_history"]),
            token_tracker=token_tracker,
            agent_name="PlannerAgent",
        )

        # Log response
        log_llm_response("PLANNER_AGENT_LLM", str(raw_response))

        # Parse plans from response
        try:
            # Extract JSON content from markdown code blocks if present
            response_content = _extract_json_content(str(raw_response))
            # print(f"response content after json extraction :\n{response_content}")
            plans = _parse_plans_response(response_content)

            state["optimization_plans"] = plans
            state["current_plan_index"] = 0
            state["previous_plans_response"] = response_content
            state["all_generated_plans_history"].append(plans)
            state["planner_history"].append(AIMessage(content=response_content))
            state["planner_history_full"].extend(state["planner_history"])

            return {"outputs": [state]}

        except LLMParsingError:
            # last_error = e
            # state["planner_history"].append(AIMessage(content=response_content))

            # # If we have retries left, add a corrective prompt
            # if attempt < max_parse_retries - 1:
            #     correction_prompt = (
            #         f"Your response could not be parsed. Error: {e!s}\n\n"
            #         "Please respond with valid JSON plans in exactly this format:\n"
            #         "```json\n"
            #         "[\n"
            #         "  {\n"
            #         '    "line_start": X,\n'
            #         '    "line_end": Y,\n'
            #         '    "title": "strategy name",\n'
            #         '    "reduction": "high|medium|low",\n'
            #         '    "description": "Description of the optimization plan."\n'
            #         "  }\n"
            #         "]\n"
            #         "```\n\n"
            #         "Ensure valid JSON syntax, escape quotes in strings if necessary."
            #     )
            #     state["planner_history"].append(HumanMessage(content=correction_prompt))
            #     log_llm_prompt("PLANNER_AGENT", correction_prompt, "planner-retry")
            print(
                f"Parsing error (attempt {attempt + 1}/{max_parse_retries}). Retrying with original prompt...",
                flush=True,
            )
            continue

    lines = state["current_proof"].split("\n")
    fallback_plan: OptimizationPlan = {
        "line_start": 1,
        "line_end": len(lines),
        "title": "general_optimization",
        "reduction": "medium",
        "description": "Unable to parse specific plans; attempting general proof optimization.",
        "status": "pending",
    }
    state["optimization_plans"] = [fallback_plan]
    state["current_plan_index"] = 0

    return {"outputs": [state]}


def _extract_json_content(response: str) -> str:
    """
    Extract JSON content from markdown code blocks if present.

    Handles formats like:
    ```json
    [ ... ]
    ```

    Parameters
    ----------
    response : str
        The raw LLM response.

    Returns
    -------
    str
        The extracted JSON content string.
    """
    # Pattern to match ```json ... ``` code blocks
    code_block_pattern = r"```json\s*\n?(.*?)\n?```"
    matches = re.findall(code_block_pattern, response, re.DOTALL | re.IGNORECASE)

    if matches:
        return matches[0].strip()

    # Fallback: look for the first '[' and last ']'
    # This helps if the LLM forgets the code block markers but outputs valid JSON
    stripped = response.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped

    raise LLMParsingError(
        "Failed to extract JSON content from LLM response. Expected JSON content within ```json ... ``` code blocks.",
        response,
    )


def _parse_plans_response(response: str) -> list[OptimizationPlan]:
    """
    Extract optimization plans from the LLM response.

    Expected format: JSON list of objects
    [
      {
        "line_start": X,
        "line_end": Y,
        "title": "strategy name",
        "reduction": "high|medium|low",
        "description": "..."
      }
    ]

    Parameters
    ----------
    response : str
        The LLM response containing optimization plans (JSON string).

    Returns
    -------
    list[OptimizationPlan]
        List of parsed optimization plans.

    Raises
    ------
    LLMParsingError
        If JSON is invalid or structure is incorrect.
    """
    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        raise LLMParsingError(f"Failed to parse JSON response: {e}", response) from e

    if not isinstance(data, list):
        raise LLMParsingError("Expected JSON response to be a list of plans.", response)

    plans: list[OptimizationPlan] = []

    for i, item in enumerate(data):
        try:
            if not isinstance(item, dict):
                raise ValueError("Plan item must be a dictionary/object")

            # Extract and validate fields
            line_start = int(item.get("line_start", 0))
            line_end = int(item.get("line_end", 0))
            title = str(item.get("title", "unspecified"))
            reduction = str(item.get("reduction", "medium"))
            description = str(item.get("description", "")).strip()

            if line_start <= 0 or line_end <= 0:
                raise ValueError("Line numbers must be positive integers")

            plan: OptimizationPlan = {
                "line_start": line_start,
                "line_end": line_end,
                "title": title,
                "reduction": reduction,
                "description": description,
                "status": "pending",
            }
            plans.append(plan)

        except (ValueError, TypeError) as e:
            raise LLMParsingError(f"Failed to parse plan #{i + 1}: {e}", response) from e

    if not plans:
        raise LLMParsingError("No optimization plans found in the response.", response)

    return plans


def _print_plans_nicely(plans: list[OptimizationPlan]) -> None:
    """
    Print optimization plans in a nicely formatted way.

    Parameters
    ----------
    plans : list[OptimizationPlan]
        The plans to print.
    """
    if not plans:
        print("  No plans to display.")
        return

    print()
    for i, plan in enumerate(plans, 1):
        print(f"📋 Plan {i}: {plan['title']}")
        print(f"   📍 Lines: {plan['line_start']}-{plan['line_end']}")
        print(f"   🎯 Reduction: {plan['reduction'].upper()}")
        print(f"   📊 Status: {plan['status'].upper()}")
        print(f"   📝 Description: {plan['description']}")
        print("   " + "─" * 60)
