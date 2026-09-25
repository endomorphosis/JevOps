"""
Planner Optimizer Framework for planner-based proof optimization workflow.

This module provides the main framework class that orchestrates the planner-based
proof optimization multi-agent system with planning, retrieval, and step-by-step
execution of optimization plans.
"""

from __future__ import annotations

import logging
from typing import ClassVar, cast

from langchain_core.language_models.chat_models import BaseChatModel
from rich.console import Console

from lean_refactor.agents.executer_agent import ExecuterAgentFactory
from lean_refactor.agents.initial_optimizer_agent import InitialOptimizerAgentFactory
from lean_refactor.agents.lean_finder_agent import LeanFinderAgentFactory
from lean_refactor.agents.planner_agent import PlannerAgentFactory
from lean_refactor.agents.planner_corrector_agent import PlannerCorrectorAgentFactory
from lean_refactor.agents.planner_lean_client_agent import PlannerLeanClientAgentFactory
from lean_refactor.agents.planner_optimizer_supervisor_agent import (
    PlannerOptimizerSupervisorAgentFactory,
)
from lean_refactor.agents.planner_repl_agent import PlannerReplAgentFactory
from lean_refactor.agents.state import PlannerOptimizedProofStates
from lean_refactor.agents.util.common import TokenTracker
from lean_refactor.planner_optimizer_state import PlannerOptimizerStateManager
from lean_refactor.util.planner_debug import print_all_queues, print_queue_summary
from lean_refactor.util.verifier_lean_client import LeanClientScheduler
from lean_refactor.util.verifier_slow import Lean4ServerScheduler

logger = logging.getLogger(__name__)


class PlannerOptimizerConfig:
    """
    Configuration for the planner-based proof optimizer system.

    Attributes
    ----------
    planner_agent_llm : BaseChatModel
        The language model used for planning optimization steps.
    finder_agent_llm : BaseChatModel
        The language model used for generating retrieval queries.
    executer_agent_llm : BaseChatModel
        The language model used for executing optimization plans.
    retrieval_server_url : str
        URL of the Mathlib retrieval service.
    lean_workspace_path : str
        Path to the Lean project workspace (where lakefile.toml is located).
    lean_max_concurrent_workers : int
        Number of parallel worker processes for proof verification.
    lean_timeout : int
        Per-request timeout in seconds for proof verification.
    max_correction_attempts : int
        Maximum correction attempts per plan execution cycle.
    max_replans : int
        Maximum number of replans allowed.
    api_budget : int
        Maximum number of API calls allowed.
    max_results_per_query : int
        Maximum number of results to retrieve per search query.
    """

    def __init__(
        self,
        planner_agent_llm: BaseChatModel,
        finder_agent_llm: BaseChatModel,
        executer_agent_llm: BaseChatModel,
        retrieval_server_url: str,
        lean_workspace_path: str,
        initial_optimizer_agent_llm: BaseChatModel | None = None,
        lean_max_concurrent_workers: int = 4,
        lean_timeout: int = 300,
        max_correction_attempts: int = 3,
        max_replans: int = 3,
        api_budget: int = 20,
        max_results_per_query: int = 5,
        max_correction_attempts_high: int | None = None,
        max_correction_attempts_medium: int | None = None,
        max_correction_attempts_low: int | None = None,
        init_optim: bool = False,
        compiler: str = "lean_client",
        use_tactic_style: bool = False,
    ):
        """
        Initialize planner optimizer configuration.

        Parameters
        ----------
        planner_agent_llm : BaseChatModel
            The language model used for planning optimization steps.
        finder_agent_llm : BaseChatModel
            The language model used for generating retrieval queries.
        executer_agent_llm : BaseChatModel
            The language model used for executing optimization plans.
        retrieval_server_url : str
            URL of the Mathlib retrieval service.
        lean_workspace_path : str
            Path to the Lean project workspace (where lakefile.toml is located).
        initial_optimizer_agent_llm : BaseChatModel | None
            The language model used for initial direct optimization.
            Defaults to executer_agent_llm if not provided.
        lean_max_concurrent_workers : int
            Number of parallel worker processes for proof verification.
        lean_timeout : int
            Per-request timeout in seconds for proof verification.
        max_correction_attempts : int
            Maximum correction attempts per plan execution cycle.
        max_replans : int
            Maximum number of replans allowed.
        api_budget : int
            Maximum number of API calls allowed.
        max_results_per_query : int
            Maximum number of results to retrieve per search query.
        max_correction_attempts_high : int | None
            Maximum correction attempts for high reduction plans.
        max_correction_attempts_medium : int | None
            Maximum correction attempts for medium reduction plans.
        max_correction_attempts_low : int | None
            Maximum correction attempts for low reduction plans.
        init_optim : bool
            Whether to run initial direct optimization.
        compiler : str
            Compiler backend to use ("lean_client" or "repl").
        """
        self.planner_agent_llm = planner_agent_llm
        self.finder_agent_llm = finder_agent_llm
        self.executer_agent_llm = executer_agent_llm
        self.initial_optimizer_agent_llm = initial_optimizer_agent_llm or executer_agent_llm
        self.retrieval_server_url = retrieval_server_url
        self.lean_workspace_path = lean_workspace_path
        self.lean_max_concurrent_workers = lean_max_concurrent_workers
        self.lean_timeout = lean_timeout
        self.max_correction_attempts = max_correction_attempts
        self.max_replans = max_replans
        self.api_budget = api_budget
        self.max_results_per_query = max_results_per_query
        self.max_correction_attempts_high = (
            max_correction_attempts_high if max_correction_attempts_high is not None else max_correction_attempts
        )
        self.max_correction_attempts_medium = (
            max_correction_attempts_medium if max_correction_attempts_medium is not None else max_correction_attempts
        )
        self.max_correction_attempts_low = (
            max_correction_attempts_low if max_correction_attempts_low is not None else max_correction_attempts
        )
        self.init_optim = init_optim
        self.compiler = compiler
        self.use_tactic_style = use_tactic_style


class PlannerOptimizerFramework:
    """
    The framework that orchestrates the planner-based multi-agent proof optimization system.

    The framework is controlled by a supervisor agent that determines which action to take
    at each step of the optimization loop: plan → find → execute → compile → (correct if needed).
    """

    # Mapping from method names to user-friendly phase names
    _PHASE_NAMES: ClassVar[dict[str, str]] = {
        "initial_optimize": "Initial direct optimization",
        "plan_proofs": "Planning optimization",
        "find_lemmas": "Finding relevant lemmas",
        "execute_plans": "Executing optimization plan",
        "compile_proofs": "Compiling optimized proof",
        "correct_proofs": "Preparing correction",
        "skip_to_next_plan": "Skipping to next plan",
        "finish": "Finishing optimization",
    }

    def __init__(
        self,
        config: PlannerOptimizerConfig,
        state_manager: PlannerOptimizerStateManager,
        console: Console | None = None,
        lean_scheduler: LeanClientScheduler | Lean4ServerScheduler | None = None,
        token_tracker: TokenTracker | None = None,
        debug_print_queues: bool = False,
    ):
        """
        Initialize the planner optimizer framework.

        Parameters
        ----------
        config : PlannerOptimizerConfig
            Configuration for the planner optimizer.
        state_manager : PlannerOptimizerStateManager
            The state manager for tracking optimization progress.
        console : Console | None
            Rich console for output. If None, a new Console is created.
        lean_scheduler : LeanClientScheduler | Lean4ServerScheduler | None
            Optional pre-initialized scheduler for proof verification.
            If None, a new scheduler will be created and managed by this framework.
        token_tracker : TokenTracker | None
            Optional token tracker for recording LLM token usage.
            If None, a new tracker will be created.
        debug_print_queues : bool
            Whether to print queue contents after each action (default: False).
        """
        self._config = config
        self._state_manager = state_manager
        self._console = console if console is not None else Console()
        self._debug_print_queues = debug_print_queues

        self._token_tracker = token_tracker if token_tracker is not None else TokenTracker()

        if lean_scheduler is not None:
            self._lean_scheduler = lean_scheduler
            self._owns_scheduler = False
        else:
            if self._config.compiler == "repl":
                self._lean_scheduler = Lean4ServerScheduler(
                    lean_workspace=config.lean_workspace_path,
                    max_concurrent_requests=config.lean_max_concurrent_workers,
                    timeout=config.lean_timeout,
                    memory_limit=10,
                    name="verifier",
                )
            else:
                self._lean_scheduler = LeanClientScheduler(
                    workspace_path=config.lean_workspace_path,
                    max_concurrent_requests=config.lean_max_concurrent_workers,
                    timeout=config.lean_timeout,
                )
            self._owns_scheduler = True

    def run(self) -> None:
        """
        Runs the planner-based proof optimization system until API budget is exhausted
        or optimization completes.
        """
        supervisor_agent = PlannerOptimizerSupervisorAgentFactory.create_agent(state_manager=self._state_manager)

        while not self._state_manager.is_finished:
            # Get the next action from the supervisor
            action = supervisor_agent.get_action()
            logger.debug(f"Next action: {action}")

            self._state_manager.add_action(action)

            phase_name = self._PHASE_NAMES.get(action, action)

            api_status = f"[{self._state_manager.api_calls_count}/{self._state_manager.api_budget}]"
            shortest_status = f"(shortest: {self._state_manager.shortest_proof_length} tokens)"
            plan_status = self._get_plan_status()

            # Execute the action with status display
            with self._console.status(f"[bold blue]{phase_name}... {api_status} {shortest_status} {plan_status}"):
                getattr(self, action)()

            # Debug print queues after each action if enabled
            if self._debug_print_queues:
                self._console.print(f"\n[bold cyan]After action: {action}[/bold cyan]")
                print_all_queues(
                    self._state_manager._state,
                    console=self._console,
                    show_proofs=True,
                    show_histories=True,
                    show_tables=True,
                    show_empty_queues=True,
                )
        if self._state_manager._state.action_history and self._state_manager._state.action_history[-1] != "finish":
            self.finish()

    def debug_print_queues(
        self,
        show_proofs: bool = True,
        show_histories: bool = True,
        show_tables: bool = True,
        show_empty_queues: bool = True,
    ) -> None:
        """
        Print the contents of all queues for debugging purposes.

        This method can be called at any time to inspect the current state
        of all queues in the optimization workflow.

        Parameters
        ----------
        show_proofs : bool
            Whether to show proof content (truncated). Default True.
        show_histories : bool
            Whether to show history information. Default True.
        show_tables : bool
            Whether to show detailed tables for list fields. Default True.
        show_empty_queues : bool
            Whether to show empty queues. Default True.
        """
        print_all_queues(
            self._state_manager._state,
            console=self._console,
            show_proofs=show_proofs,
            show_histories=show_histories,
            show_tables=show_tables,
            show_empty_queues=show_empty_queues,
        )

    def debug_print_queue_summary(self) -> None:
        """
        Print a compact summary of all queues (just counts, no details).

        This is a lightweight alternative to debug_print_queues() for quick
        status checks.
        """
        print_queue_summary(self._state_manager._state, console=self._console)

    def _get_plan_status(self) -> str:
        """Get a string describing current plan progress."""
        state = self._state_manager._get_active_state()
        if not state or not state["optimization_plans"]:
            return ""
        idx = state["current_plan_index"]
        total = len(state["optimization_plans"])
        replan = state["replan_count"]
        return f"[Plan {idx + 1}/{total}, Replan {replan}/{self._config.max_replans}]"

    @property
    def token_tracker(self) -> TokenTracker:
        """Get the token tracker for this framework."""
        return self._token_tracker

    def initial_optimize(self) -> None:
        """
        Run the initial direct optimization agent.
        """
        # Create initial optimizer agent
        initial_optimizer_agent = InitialOptimizerAgentFactory.create_agent(
            llm=self._config.initial_optimizer_agent_llm,
            token_tracker=self._token_tracker,
            use_tactic_style=self._config.use_tactic_style,
        )

        # Get proofs to optimize
        states = self._state_manager.get_proofs_to_initial_optimize()

        # Invoke the agent
        states = cast(PlannerOptimizedProofStates, initial_optimizer_agent.invoke(states))

        # Update state manager
        self._state_manager.set_initial_optimized_proofs(states)

    def plan_proofs(self) -> None:
        """
        Generate optimization plans for proofs in the plan queue.
        """
        # Create planner agent
        planner_agent = PlannerAgentFactory.create_agent(
            llm=self._config.planner_agent_llm,
            token_tracker=self._token_tracker,
            use_tactic_style=self._config.use_tactic_style,
        )

        # Get proofs to plan
        states = self._state_manager.get_proofs_to_plan()

        # Invoke the planner agent
        states = cast(PlannerOptimizedProofStates, planner_agent.invoke(states))

        # Update state manager
        self._state_manager.set_planned_proofs(states)

        # Log plan summary
        for state in states["outputs"]:
            length = len(state["signature"])
            logger.warning(
                f"Generated {len(state['optimization_plans'])} optimization plans for {state['signature'][: min(length, 50)]}..."
            )

    def find_lemmas(self) -> None:
        """
        Find relevant lemmas for the current optimization plan.
        """
        # Create finder agent
        finder_agent = LeanFinderAgentFactory.create_agent(
            llm=self._config.finder_agent_llm,
            retrieval_server_url=self._config.retrieval_server_url,
            max_results_per_query=self._config.max_results_per_query,
            token_tracker=self._token_tracker,
        )

        # Get proofs to find lemmas for
        states = self._state_manager.get_proofs_to_find_lemmas()

        # Invoke the finder agent
        states = cast(PlannerOptimizedProofStates, finder_agent.invoke(states))

        # Update state manager
        self._state_manager.set_found_lemmas(states)

    def execute_plans(self) -> None:
        """
        Execute the current optimization plan.
        """
        # Create executer agent
        executer_agent = ExecuterAgentFactory.create_agent(
            llm=self._config.executer_agent_llm,
            token_tracker=self._token_tracker,
            compiler=self._config.compiler,
            use_tactic_style=self._config.use_tactic_style,
        )

        # Get proofs to execute
        states = self._state_manager.get_proofs_to_execute()

        # Invoke the executer agent
        states = cast(PlannerOptimizedProofStates, executer_agent.invoke(states))

        # Update state manager
        self._state_manager.set_executed_proofs(states)

    def compile_proofs(self) -> None:
        """
        Compile optimized proofs to check for validity.
        """
        if self._config.compiler == "repl":
            # Create repl agent with shared scheduler
            lean_client_agent = PlannerReplAgentFactory.create_agent(
                lean_scheduler=self._lean_scheduler,
            )
        else:
            # Create lean client agent with shared scheduler
            lean_client_agent = PlannerLeanClientAgentFactory.create_agent(
                lean_scheduler=self._lean_scheduler,
            )

        # Get proofs to compile
        states = self._state_manager.get_proofs_to_compile()

        states = cast(PlannerOptimizedProofStates, lean_client_agent.invoke(states))

        self._state_manager.set_compiled_proofs(states)

    def correct_proofs(self) -> None:
        """
        Prepare correction prompts for proofs that failed compilation.
        """
        # Create corrector agent
        corrector_agent = PlannerCorrectorAgentFactory.create_agent()

        # Get proofs to correct
        states = self._state_manager.get_proofs_to_correct()

        # Invoke the corrector agent
        states = cast(PlannerOptimizedProofStates, corrector_agent.invoke(states))

        # Update state manager (re-queues to executer)
        self._state_manager.set_corrected_proofs(states)

    def skip_to_next_plan(self) -> None:
        """
        Skip the current plan and advance to the next one.

        This is called when correction attempts are exhausted for a plan.
        """
        self._state_manager.skip_current_plan_and_advance()

    def finish(self) -> None:
        """
        Finalize the optimization and log results.
        """
        self._state_manager.cache_final_state()

        shortest_proof, shortest_length = self._state_manager.get_final_result()

        self._console.print("\n[bold green]Optimization finished![/bold green]")
        self._console.print(f"  Reason: {self._state_manager.reason}")
        self._console.print(f"  API calls used: {self._state_manager.api_calls_count}/{self._state_manager.api_budget}")
        self._console.print(f"  Shortest proof: {shortest_length} tokens")

        self._state_manager._state.final_optimized_proof = self._state_manager.reconstruct_complete_proof()

        if self._owns_scheduler and self._lean_scheduler is not None:
            self._lean_scheduler.close()
