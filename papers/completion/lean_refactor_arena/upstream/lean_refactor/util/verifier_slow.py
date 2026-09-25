import os
import time
import json
import ctypes
import resource
import tempfile
import traceback
import threading
import subprocess
import multiprocessing as mp
from pprint import pprint
from lean_refactor.utils import get_error_str_goedel_style


import numpy as np

#from worker.ast_parser import lean4_parser
from .scheduler import ProcessScheduler
from easydict import EasyDict as AttrDict

HOME_DIR = os.path.expanduser('~')
DEFAULT_LAKE_PATH = f'{HOME_DIR}/.elan/bin/lake'

def verify_lean4_file(code, lean_workspace, lake_path=DEFAULT_LAKE_PATH, last_env=None, verbose=False, timeout=300, allTactics=False, ast=False, premises=False, tactics=False):
    theorem_idx = code.find('theorem')
    if theorem_idx >= 0:
        code_preview = code[theorem_idx:min(theorem_idx + 50, len(code))]
    else:
        code_preview = code[:min(50, len(code))]
    print(f"Lean Server: Verifying code {code_preview}...", flush=True)

    command = dict(cmd=code, allTactics=allTactics, ast=ast, tactics=tactics, premises=premises)
    if verbose:
        print(f"content being verified: {command}\n\n", flush=True)
    if last_env is not None:
        command.update(env=last_env)
    message_str = json.dumps(command, ensure_ascii=False)
    if verbose:
        print(f"message_str: {message_str}\n\n", flush=True)
    start_time = time.time()
    system_messages = ''
    try:
        with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as temp_file:
            temp_file.write(message_str + "\r\n\r\n")
            temp_file.seek(0)
            outputs = subprocess.run([lake_path, "exe", 'repl'], stdin=temp_file, capture_output=True, text=True, cwd=lean_workspace, timeout=timeout)
        #print(f"outputs: {outputs.stdout}", flush=True)
        result = json.loads(outputs.stdout)
        #print(f"result: {result}", flush=True)
        #ast_results = lean4_parser(code, result['ast']) if 'ast' in result and result['ast'] else {}
        result = {
            "sorries" : result.get('sorries', []), 
            "tactics" : result.get('tactics', []),
            "errors" : [m for m in result.get('messages', []) if m['severity'] == 'error'],
            "warnings" : [m for m in result.get('messages', []) if m['severity'] == 'warning'],
            "infos" : [m for m in result.get('messages', []) if m['severity'] == 'info'],
            "system_messages" : system_messages,
            "system_errors" : None,
            #"ast" : ast_results,
            "verified_code" : code,
        }
        result['pass'] = not result['errors']
        result['complete'] = result['pass'] and not result['sorries'] and not any("declaration uses 'sorry'" in warning['data'] or 'failed' in warning['data'] for warning in result['warnings'])
        # for k, v in result.items():
        #     print(f'{k}: {v}')
        #     print("=" * 20)
    except:
        tb = traceback.format_exc()
        print(f"System error detected: {tb[:100]}... code: {code[:50]}...", flush=True)
        result = {
            "pass": False,
            "complete": False,
            "system_errors": tb,
            "system_messages": system_messages
        }
    result['verify_time'] = time.time() - start_time
    return result


class Lean4ServerProcess(mp.Process):
    def __init__(self, idx, task_queue, request_statuses, lock, extra_args=AttrDict()):
        super().__init__()
        self.idx = idx
        self.task_queue = task_queue
        self.request_statuses = request_statuses
        self.lock = lock
        self.extra_args = extra_args

        self.timeout = extra_args.get('timeout', 300)
        self.memory_limit = extra_args.get('memory_limit', -1)
        self.lean_workspace = extra_args.get('lean_workspace')
        self.last_output_time = mp.Value(ctypes.c_double, time.time())
        self.complete_count = mp.Value(ctypes.c_int, 0)
    
    def run(self):
        # if self.memory_limit > 0:
        #     resource.setrlimit(
        #         resource.RLIMIT_AS,
        #         (self.memory_limit * (1000 ** 3), self.memory_limit * (1000 ** 3))
        #     )
        while True:
            inputs = self.task_queue.get()
            if inputs is None: # Terminate when receiving None
                break
            for _, request_id, task in inputs:
                if isinstance(task, str):
                    task = dict(code=task)
                if 'timeout' not in task:
                    task['timeout'] = self.timeout
                task['lean_workspace'] = self.lean_workspace
                result = verify_lean4_file(**task)
                if len(result['system_messages']) > 0:
                    retry_start_time = time.time()
                    while ('lean::exception: failed to create thread' in result['system_messages'] or
                           'std::bad_alloc: std::bad_alloc' in result['system_messages'] or
                           'Cannot allocate memory' in result['system_messages']) \
                          and time.time() - retry_start_time < self.timeout:
                        time.sleep(0.1)
                        result = verify_lean4_file(**task)
                with self.lock:
                    self.request_statuses[request_id] = result
                    self.last_output_time.value = time.time()
                    self.complete_count.value += 1


class Lean4ServerScheduler(ProcessScheduler):
    def __init__(self, lean_workspace, max_concurrent_requests=64, timeout=300, memory_limit=-1, name='verifier'):
        super().__init__(batch_size=1, name=name)

        self.processes = [
                Lean4ServerProcess(
                    idx=idx,
                    task_queue=self.task_queue,
                    request_statuses=self.request_statuses,
                    lock=self.lock,
                    extra_args=AttrDict(
                        timeout=timeout,
                        memory_limit=memory_limit,
                        lean_workspace=lean_workspace,
                    )
                )
                for idx in range(max_concurrent_requests)
            ]
        for p in self.processes:
            p.start()
        print(f'Complete launching {len(self.processes)} LeanServerProcesses')

        self.timeout = timeout
        self._running_monitor = mp.Value(ctypes.c_bool, True)
        self._last_complete_count = mp.Value(ctypes.c_int, 0)
        self._monitor_process = mp.Process(target=self._monitor)
        self._monitor_process.start()
    
    def _monitor(self):
        while self._running_monitor.value:
            time.sleep(1.0)
            subprocess.run(['killall', 'repl', f'--older-than={int(self.timeout) + 10}s'], capture_output=True)
    
    def close(self):
        super().close()
        for p in self.processes:
            p.join()
        self._running_monitor.value = False
        self._monitor_process.join()
        print(f'All {len(self.processes)} LeanServerProcesses stopped')


if __name__ == '__main__':
    time_start = time.time()
    
    code = """

-- !benchmark @start import type=solution

-- !benchmark @end import
-- additional imports (or leave empty)

-- !benchmark @start solution_aux

-- !benchmark @end solution_aux

-- !benchmark @start precond_aux

-- !benchmark @end precond_aux
@[reducible, simp]
def ComputeAvg_precond (a : Int) (b : Int) : Prop :=
  -- !benchmark @start precond
  True
  -- !benchmark @end precond


-- !benchmark @start code_aux

-- !benchmark @end code_aux


def ComputeAvg (a : Int) (b : Int) (h_precond : ComputeAvg_precond (a) (b)) : Int :=
  -- !benchmark @start code
  (a + b) / 2
  -- !benchmark @end code


-- !benchmark @start postcond_aux

-- !benchmark @end postcond_aux


@[reducible, simp]
def ComputeAvg_postcond (a : Int) (b : Int) (result: Int) (h_precond : ComputeAvg_precond (a) (b)) :=
  -- !benchmark @start postcond
  2 * result = a + b - ((a + b) % 2)
  -- !benchmark @end postcond


-- !benchmark @start proof_aux
-- auxiliary lemmas (or leave empty)

-- !benchmark @end proof_aux


theorem ComputeAvg_spec_satisfied (a: Int) (b: Int) (h_precond : ComputeAvg_precond (a) (b)) :
    ComputeAvg_postcond (a) (b) (ComputeAvg (a) (b) h_precond) h_precond := by
  -- !benchmark @start proof
  simp only [ComputeAvg, ComputeAvg_postcond]
  have h := Int.ediv_add_emod (a + b) 2
  omega

  -- !benchmark @end proof


"""
    lean4_scheduler = Lean4ServerScheduler(lean_workspace='lean_refactor/mathlib4', max_concurrent_requests=1, timeout=300, memory_limit=10, name='verifier')
    request_id_list = lean4_scheduler.submit_all_request([dict(code=code, ast=True, tactics=True)])
    outputs_list = lean4_scheduler.get_all_request_outputs(request_id_list)
    lean4_scheduler.close()
    pprint(outputs_list)
    for output in outputs_list:
        print(get_error_str_goedel_style(output['verified_code'], output['errors']))
        print("=" * 20)
    time_end = time.time()
    print(f"Time taken: {time_end - time_start} seconds")
    # rid = lean4_scheduler.submit_request({'code': code, 'ast': True, 'tactics': True})
    # print(lean4_scheduler.get_request_outputs(rid))
    # lean4_scheduler.close()
