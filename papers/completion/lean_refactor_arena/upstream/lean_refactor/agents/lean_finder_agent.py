"""
Lean Finder Agent for planner-based proof optimization workflow.

This agent takes the current optimization plan and retrieves relevant lemmas
from a Mathlib retrieval service that could help shorten the proof.
"""

import logging
import re
from functools import partial

import requests
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from lean_refactor.agents.state import (
    PlannerOptimizedProofState,
    PlannerOptimizedProofStates,
    RetrievedLemma,
)
from lean_refactor.agents.util.common import LLMParsingError, TokenTracker, get_llm_response_content, load_prompt
from lean_refactor.agents.util.debug import log_llm_prompt, log_llm_response

logger = logging.getLogger(__name__)


class LeanFinderAgentFactory:
    """
    Factory class for creating instances of the LeanFinderAgent.
    """

    @staticmethod
    def create_agent(
        llm: BaseChatModel,
        retrieval_server_url: str,
        max_results_per_query: int = 5,
        token_tracker: TokenTracker | None = None,
    ) -> CompiledStateGraph:
        """
        Creates a LeanFinderAgent instance.

        Parameters
        ----------
        llm : BaseChatModel
            The LLM to use for generating search queries.
        retrieval_server_url : str
            The URL of the Mathlib retrieval service.
        max_results_per_query : int
            Maximum number of results to retrieve per query (default: 5).
        token_tracker : TokenTracker | None
            Optional token tracker for recording LLM token usage.

        Returns
        -------
        CompiledStateGraph
            A CompiledStateGraph instance of the lean finder agent.
        """
        return _build_agent(
            llm=llm,
            retrieval_server_url=retrieval_server_url,
            max_results_per_query=max_results_per_query,
            token_tracker=token_tracker,
        )


def _build_agent(
    llm: BaseChatModel,
    retrieval_server_url: str,
    max_results_per_query: int,
    token_tracker: TokenTracker | None = None,
) -> CompiledStateGraph:
    """
    Builds a compiled state graph for the lean finder agent.

    Parameters
    ----------
    llm : BaseChatModel
        The LLM to use for generating search queries.
    retrieval_server_url : str
        The URL of the Mathlib retrieval service.
    max_results_per_query : int
        Maximum number of results to retrieve per query.
    token_tracker : TokenTracker | None
        Optional token tracker for recording LLM token usage.

    Returns
    -------
    CompiledStateGraph
        The compiled state graph for the lean finder agent.
    """
    graph_builder = StateGraph(PlannerOptimizedProofStates)

    # Bind the arguments
    bound_finder = partial(_finder, llm, retrieval_server_url, max_results_per_query, token_tracker)

    # Add the nodes
    graph_builder.add_node("lean_finder_agent", bound_finder)

    # Add the edges
    graph_builder.add_conditional_edges(START, _map_edge, ["lean_finder_agent"])
    graph_builder.add_edge("lean_finder_agent", END)

    return graph_builder.compile()


def _map_edge(states: PlannerOptimizedProofStates) -> list[Send]:
    """
    Map edge that dispatches states to the lean_finder_agent nodes.

    Parameters
    ----------
    states : PlannerOptimizedProofStates
        The states to process.

    Returns
    -------
    list[Send]
        List of Send objects for each input state.
    """
    return [Send("lean_finder_agent", state) for state in states["inputs"]]


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
    # Convert to 0-indexed
    start_idx = max(0, line_start - 1)
    end_idx = min(len(lines), line_end)
    return "\n".join(lines[start_idx:end_idx])


def _finder(
    llm: BaseChatModel,
    retrieval_server_url: str,
    max_results_per_query: int,
    token_tracker: TokenTracker | None,
    state: PlannerOptimizedProofState,
) -> PlannerOptimizedProofStates:
    """
    Generate search queries and retrieve relevant lemmas for the current plan.

    Parameters
    ----------
    llm : BaseChatModel
        The LLM to use for generating search queries.
    retrieval_server_url : str
        The URL of the Mathlib retrieval service.
    max_results_per_query : int
        Maximum number of results to retrieve per query.
    token_tracker : TokenTracker | None
        Optional token tracker for recording LLM token usage.
    state : PlannerOptimizedProofState
        The state with the current plan to find lemmas for.

    Returns
    -------
    PlannerOptimizedProofStates
        A PlannerOptimizedProofStates with retrieved lemmas.
    """
    # Get current plan
    plans = state["optimization_plans"]
    idx = state["current_plan_index"]

    if idx >= len(plans):
        # No current plan - return empty retrievals
        state["plan_retrievals"] = []
        return {"outputs": [state]}  # type: ignore[typeddict-item]

    current_plan = plans[idx]

    # Extract the relevant proof section
    proof_section = _get_proof_section(
        state["current_proof"],
        current_plan["line_start"],
        current_plan["line_end"],
    )

    # Build prompt for query generation
    prompt_kwargs = {
        "current_proof": state["current_proof"],
        "proof_section": proof_section,
        "line_start": str(current_plan["line_start"]),
        "line_end": str(current_plan["line_end"]),
        "title": current_plan["title"],
        "plan_description": current_plan["description"],
    }

    prompt = load_prompt("lean-finder", **prompt_kwargs)
    log_llm_prompt("LEAN_FINDER_AGENT", prompt, "lean-finder")

    # Generate search queries
    response_content = get_llm_response_content(
        llm,
        llm.invoke([HumanMessage(content=prompt)]),
        token_tracker=token_tracker,
        agent_name="LeanFinderAgent",
    )
    log_llm_response("LEAN_FINDER_AGENT_LLM", str(response_content))

    # Parse search queries
    try:
        search_queries = _parse_search_queries(str(response_content))
        logger.debug(f"Extracted search queries: {search_queries}")
    except LLMParsingError:
        # Use plan description as fallback query
        search_queries = []

    if not search_queries:
        state["plan_retrievals"] = []
        logger.info(f"No search queries generated for plan {idx + 1}")
        return {"outputs": [state]}  # type: ignore[typeddict-item]

    # Query the retrieval service
    all_lemmas: list[RetrievedLemma] = []
    seen_names: set[str] = set()

    for query in search_queries:
        try:
            results = _query_retrieval_service(
                retrieval_server_url,
                query,
                max_results_per_query,
            )
            logger.debug(f"Retrieved {len(results)} lemmas for query '{query}'")

            for result in results:
                # Deduplicate by full_name
                if result["full_name"] not in seen_names:
                    seen_names.add(result["full_name"])
                    all_lemmas.append(result)
        except Exception as e:
            logger.warning(f"Retrieval query failed for '{query}': {e}")
            continue

    state["plan_retrievals"] = all_lemmas
    logger.info(f"Retrieved {len(all_lemmas)} unique lemmas for plan {idx + 1}")

    return {"outputs": [state]}  # type: ignore[typeddict-item]


def _parse_search_queries(response: str) -> list[str]:
    """
    Extract search queries from the LLM response using <search> tags.

    Parameters
    ----------
    response : str
        The LLM response containing search queries.

    Returns
    -------
    list[str]
        List of search queries.

    Raises
    ------
    LLMParsingError
        If no queries are found.
    """
    pattern = r"<search>(.*?)</search>"
    matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)

    if not matches:
        return []
        # raise LLMParsingError(
        #     "Failed to extract search queries from LLM response. "
        #     "Expected queries in <search>query</search> format.",
        #     response,
        # )

    queries = [match.strip() for match in matches if match.strip()]
    # Remove duplicates while preserving order
    queries = list(dict.fromkeys(queries))

    if not queries:
        return []
        # raise LLMParsingError("Found <search> tags but all were empty", response)

    return queries


def _query_retrieval_service(
    server_url: str,
    query: str,
    max_results: int,
) -> list[RetrievedLemma]:
    """
    Query the Mathlib retrieval service.

    Parameters
    ----------
    server_url : str
        The URL of the retrieval service.
    query : str
        The search query.
    max_results : int
        Maximum number of results to retrieve.

    Returns
    -------
    list[RetrievedLemma]
        List of retrieved lemmas.

    Raises
    ------
    requests.RequestException
        If the request fails.
    """
    # Build request payload
    payload = {
        "inputs": query,
        "top_k": int(max_results),
    }

    # Make request
    response = requests.post(
        server_url,
        json=payload,
        timeout=30,
    )
    response.raise_for_status()

    # Parse response
    data = response.json()

    # Filter and extract results
    lemmas: list[RetrievedLemma] = []

    for result in data.get("results", []):
        # Only include mathlib4 results
        if "https://leanprover-community.github.io/mathlib4_docs" not in result.get("url", ""):
            continue

        # Extract full_name from URL
        match = re.search(r"pattern=(.*?)#doc", result.get("url", ""))
        if not match:
            continue

        lemma: RetrievedLemma = {
            "full_name": match.group(1),
            "module": None,
            "signature": None,
            "source_code": result.get("formal_statement"),
            "doc_string": result.get("informal_statement"),
        }
        lemmas.append(lemma)

    return lemmas


def format_retrieved_lemmas(lemmas: list[RetrievedLemma]) -> str:
    """
    Format retrieved lemmas for inclusion in a prompt.

    Parameters
    ----------
    lemmas : list[RetrievedLemma]
        The lemmas to format.

    Returns
    -------
    str
        Formatted string representation of the lemmas.
    """
    if not lemmas:
        return "No relevant lemmas found."

    formatted_parts = []
    for idx, lemma in enumerate(lemmas, start=1):
        parts = [f"### Lemma {idx}: `{lemma['full_name']}`"]

        # parts.append(f"**Signature:**\n```lean4\n{lemma['signature']}\n```")

        if lemma.get("doc_string"):
            parts.append(f"**Documentation:** {lemma['doc_string']}")

        if lemma.get("source_code"):
            parts.append(f"**Source:**\n```lean4\n{lemma['source_code']}\n```")

        formatted_parts.append("\n".join(parts))

    return "\n\n".join(formatted_parts)


