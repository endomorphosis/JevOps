"""Lean Client Scheduler for multi-process proof verification.

This module provides a multi-process scheduler for verifying Lean 4 proofs
using the leanclient LSP interface.
"""

import ctypes
import logging
import multiprocessing as mp
import time
from pprint import pprint
from typing import Any

from lean_refactor.util.interaction import LeanInteractor
from lean_refactor.util.scheduler import ProcessScheduler


class LeanClientProcess(mp.Process):
    """Worker process for verifying Lean 4 proofs.

    Each process maintains its own LeanInteractor instance for LSP communication.
    """

    def __init__(
        self,
        idx: int,
        task_queue: Any,
        request_statuses: Any,
        lock: Any,
        workspace_path: str,
        timeout: int = 300,
        memory_limit: int = -1,
        log_level: int = logging.WARNING,
    ):
        super().__init__()
        self.idx = idx
        self.task_queue = task_queue
        self.request_statuses = request_statuses
        self.lock = lock
        self.workspace_path = workspace_path

        self.timeout = timeout
        self.memory_limit = memory_limit
        self.log_level = log_level
        self.last_output_time = mp.Value(ctypes.c_double, time.time())
        self.complete_count = mp.Value(ctypes.c_int, 0)
        # NOTE: Don't create LeanInteractor here - it must be created in run()
        # because LSP client connections don't survive process fork
        self.lean_interactor: LeanInteractor | None = None

    def verify_lean4_file(self, task: dict[str, Any], request_id: int) -> tuple[bool, bool, list[Any], str | None]:
        """Verify a Lean 4 proof by replacing code in a temp file and checking diagnostics.

        Args:
            task: Dict with 'old_code', 'new_code', 'relative_path' keys.
                  If 'full_file_mode' is True, writes new_code as complete file content
                  instead of doing old_code/new_code replacement.
            request_id: Unique request ID for temp file naming

        Returns:
            Tuple of (check_correct, error_occurred, diagnostics, file_content)
        """
        MAX_RETRIES = 3
        attempt = 0
        temp_file_path = None
        diagnostics: list[Any] = []
        check_correct = False
        full_file_mode = False

        while attempt < MAX_RETRIES and not check_correct:
            try:
                attempt += 1
                new_code = task["new_code"]
                relative_path = task["relative_path"]
                print(
                    f"Lean Server using workspace:{relative_path}, Verifying code {task['new_code'][: min(len(new_code), 50)]}... Attempt {attempt} of {MAX_RETRIES}",
                    flush=True,
                )

                if full_file_mode:
                    # Full file mode: write new_code as complete file content
                    temp_file_path = self.lean_interactor.init_standalone_temp_file(
                        relative_path, str(request_id), new_code
                    )
                    # Get diagnostics for entire file
                    diagnostics = self.lean_interactor.get_diagnostics(
                        temp_file_path,
                        timeout=self.timeout,
                    )
                else:
                    # Replacement mode: replace old_code with new_code
                    old_code = task["old_code"]
                    temp_file_path = self.lean_interactor.init_temp_file(relative_path, request_id)
                    status, start_line, end_line = self.lean_interactor.replace_code(temp_file_path, old_code, new_code)
                    if not status:
                        print(f"Lean Server: verifier error: failed to replace code in task {relative_path}", flush=True)
                        self.lean_interactor.remove_temp_file(temp_file_path)
                        return False, True, ["failed to replace code"], None
                    diagnostics = self.lean_interactor.get_diagnostics(
                        temp_file_path,
                        start_line=start_line,
                        end_line=end_line,
                        timeout=self.timeout,
                    )

                check_correct = self.lean_interactor.check_correctness(diagnostics)
                #if not correct and there is no severity = 1 error then get diagnostics for the whole file, since errors now come from other parts of the file.
                if not check_correct and all(error["severity"] != 1 for error in diagnostics):
                    diagnostics = self.lean_interactor.get_diagnostics(temp_file_path)
                    print(f"ERROR DETECTED OUTSIDE THE TARGET: {diagnostics}", flush=True)
                file_content = self.lean_interactor.read_file(temp_file_path)
                self.lean_interactor.remove_temp_file(temp_file_path)
                return check_correct, False, diagnostics, file_content
            except Exception as e:
                print(f"Lean Server: verifier error: {e}", flush=True)
                if self.lean_interactor is not None:
                    self.lean_interactor.close()
                    self.lean_interactor = LeanInteractor(
                        project_path=self.workspace_path,
                        log_level=self.log_level,
                    )
                    if temp_file_path:
                        self.lean_interactor.remove_temp_file(temp_file_path)
                        temp_file_path = None
                    continue
                time.sleep(1)
        return False, True, diagnostics, None

    def run(self) -> None:
        """Main worker loop - process tasks from queue until shutdown."""
        # Create LeanInteractor in the child process (not in __init__)
        # because LSP client connections don't survive process fork
        self.lean_interactor = LeanInteractor(
            project_path=self.workspace_path,
            log_level=self.log_level,
        )
        while True:
            inputs = self.task_queue.get()
            if inputs is None:  # Terminate when receiving None
                break
            for _, request_id, task in inputs:
                if "timeout" not in task:
                    task["timeout"] = self.timeout
                check_correct, check_error, diagnostics, file_content = self.verify_lean4_file(task, request_id)
                result = {
                    "pass": check_correct,
                    "error_occurred": check_error,
                    "diagnostics": diagnostics,
                    "file_content": file_content,
                }
                with self.lock:
                    self.request_statuses[request_id] = result
                    self.last_output_time.value = time.time()
                    self.complete_count.value += 1

        self.lean_interactor.close()


class LeanClientScheduler(ProcessScheduler):
    """Multi-process scheduler for Lean 4 proof verification.

    This scheduler manages multiple worker processes, each with its own
    LeanInteractor instance for parallel proof verification.

    Args:
        workspace_path: Path to the Lean project workspace (where lakefile.toml is located)
        max_concurrent_requests: Number of parallel worker processes
        timeout: Per-request timeout in seconds
        memory_limit: Memory limit per worker (-1 for unlimited)
        log_level: Logging level for LeanInteractor
        name: Scheduler name for logging
    """

    def __init__(
        self,
        workspace_path: str,
        max_concurrent_requests: int = 64,
        timeout: int = 300,
        memory_limit: int = -1,
        log_level: int = logging.WARNING,
        name: str = "verifier",
    ):
        super().__init__(batch_size=1, name=name)
        logging.info(
            f"LeanClientScheduler init with workspace={workspace_path}, "
            f"max_concurrent_requests={max_concurrent_requests}, timeout={timeout}"
        )
        self.workspace_path = workspace_path
        self.timeout = timeout

        self.processes = [
            LeanClientProcess(
                idx=idx,
                task_queue=self.task_queue,
                request_statuses=self.request_statuses,
                lock=self.lock,
                workspace_path=workspace_path,
                timeout=timeout,
                memory_limit=memory_limit,
                log_level=log_level,
            )
            for idx in range(max_concurrent_requests)
        ]
        for p in self.processes:
            p.start()
        logging.info(f"Launched {len(self.processes)} LeanClientProcess workers")

        self._running_monitor = mp.Value(ctypes.c_bool, True)
        self._last_complete_count = mp.Value(ctypes.c_int, 0)
        self._monitor_process = mp.Process(target=self._monitor)
        self._monitor_process.start()

    def _monitor(self) -> None:
        """Background monitor process for cleanup tasks."""
        while self._running_monitor.value:
            time.sleep(1.0)

    def close(self) -> None:
        """Shutdown all worker processes and cleanup."""
        # 1. Signal workers to stop
        # Check if task_queue references exist before accessing (in case of potential double close issues, though unlikely here)
        if hasattr(self, 'task_queue') and hasattr(self.task_queue, 'all_tasks_done'):
             self.task_queue.all_tasks_done.set()

        # 2. Join workers
        for p in self.processes:
            if p.is_alive():
                p.join()
        
        # 3. Stop monitor process
        self._running_monitor.value = False
        if self._monitor_process.is_alive():
            self._monitor_process.join()

        # 4. Shutdown manager and queue (via super)
        # Note: ProcessScheduler.close() calls manager.shutdown()
        super().close()
        
        logging.info(f"All {len(self.processes)} LeanClientProcess workers stopped")


