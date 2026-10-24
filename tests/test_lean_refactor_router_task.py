"""Meaningful offline bridge tests; no model, service or repository mutation."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('jevops_router_test_subject', ROOT / 'tools/run_lean_refactor_router_task.py')
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)
SOURCE = Path('/home/barberb/lift_coding/external/ipfs_accelerate')
import sys
sys.path.insert(0, str(SOURCE))
from ipfs_accelerate_py.agent_supervisor.task_sources.todo_vector_index import parse_todo_blocks


class RouterTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='jevops-router-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'config').mkdir()
        self.cfg = json.loads((ROOT / worker.CONFIG).read_text())
        (self.root / worker.CONFIG).write_text(json.dumps(self.cfg))
        (self.root / 'implementation_plan').mkdir()
        (self.root / self.cfg['taskboard']).write_text('''# Test campaign
## JLR-001 Actual inventory
- Status: completed
- Depends on:
## JLR-002 Strict model proposal
- Status: pending
- Provider role: grok-only
- Model: grok-4.7
- Depends on: JLR-001
- Predicted files: implementation_plan/proposals/JLR-002.review.json
- Outputs: implementation_plan/proposals/JLR-002.review.json
- Validation: python3 tools/check_lean_refactor_plan.py --check-task JLR-002
- Acceptance: Unverified engineering review only.
''')
        self.dag = {'schema': 'jevops.lean-refactor.campaign.v1', 'tasks': [
            {'id': 'JLR-002', 'mode': 'router', 'depends_on': ['JLR-001'],
             'predicted_files': ['implementation_plan/proposals/JLR-002.review.json']}]}
        (self.root / self.cfg['goals']).write_text(json.dumps(self.dag))
        self.output = self.root / 'implementation_plan/proposals/JLR-002.review.json'

    def packet(self):
        return worker.task_packet(self.root, self.cfg, 'JLR-002', parse_todo_blocks)

    def proposal(self, packet=None, **change):
        packet = self.packet()[0] if packet is None else packet
        path = next(iter(packet['targets']))
        row = {'schema': worker.SCHEMA, 'task_id': 'JLR-002', 'summary': 'Unverified review',
               'files': [{'path': path, 'base_sha256': packet['targets'][path]['base_sha256'],
                          'content': '{"review":"unverified"}\n'}]}
        row.update(change)
        return json.dumps(row)

    def fake_call(self, prompt, cfg, directory):
        return self.proposal(), {'child': {'effective_provider': 'grok_cli'}, **worker.AUTH}

    def complete_fake_call(self, prompt, cfg, directory):
        trace = {'provider': 'grok_cli', 'model': 'grok-4.7',
                 'cmd': [cfg['grok_executable'], '--model', 'grok-4.7', '--tools', '']}
        (directory / 'grok_cli_trace.jsonl').write_text(json.dumps(trace) + '\n')
        return self.proposal(), {'child': {'effective_provider': 'grok_cli', 'status': 'ok', 'exit_code': 0},
                                 'requested_model': 'grok-4.7', 'actual_trace': trace, **worker.AUTH}

    def test_native_parser_reads_exact_id_dependencies_and_predicted_paths(self):
        packet, _, _ = self.packet()
        self.assertEqual(packet['fields']['provider_role'], 'grok-only')
        self.assertEqual(packet['goal_task']['depends_on'], ['JLR-001'])

    def test_preflight_performs_no_provider_call_or_runtime_write(self):
        def forbidden(*args): raise AssertionError('no call')
        result = worker.run(self.root, 'JLR-002', preflight=True, parser=parse_todo_blocks, caller=forbidden)
        self.assertEqual(result['provider_calls'], 0)
        self.assertFalse((self.root / self.cfg['runtime_root']).exists())
        self.assertFalse(self.output.exists())

    def test_valid_proposal_has_real_budget_reservation_and_no_completion_claim(self):
        result = worker.run(self.root, 'JLR-002', parser=parse_todo_blocks, caller=self.fake_call)
        self.assertEqual(json.loads(self.output.read_text()), {'review': 'unverified'})
        self.assertIs(result['completion_authority'], False)
        self.assertIn('pending', result['validation'])
        budget = json.loads((self.root / self.cfg['runtime_root'] / 'router-budget.json').read_text())
        self.assertEqual(budget['calls'], 1)

    def test_wrong_model_or_fallback_config_rejected_before_request(self):
        for key, value in [('model', 'grok-4.6'), ('allow_cross_provider_fallback', True), ('max_calls', 25)]:
            cfg = {**self.cfg, key: value}
            (self.root / worker.CONFIG).write_text(json.dumps(cfg))
            with self.subTest(key=key), self.assertRaises(ValueError): worker.config(self.root)

    def test_model_cannot_write_fake_benchmark_or_control_evidence(self):
        for path in ('data/benchmark/result.json', 'config/owned.json', '../escape', '.env',
                     'implementation_plan/lean_refactor_arena_20261024.todo.md'):
            with self.subTest(path=path):
                board = (self.root / self.cfg['taskboard']).read_text()
                original = 'implementation_plan/proposals/JLR-002.review.json'
                (self.root / self.cfg['taskboard']).write_text(board.replace(original, path))
                self.dag['tasks'][0]['predicted_files'] = [path]
                (self.root / self.cfg['goals']).write_text(json.dumps(self.dag))
                with self.assertRaises(ValueError): self.packet()
                (self.root / self.cfg['taskboard']).write_text(board)

    def test_unknown_fields_duplicate_keys_and_wrong_identity_rejected(self):
        packet, _, _ = self.packet()
        for raw in (self.proposal(extra=True), self.proposal(task_id='JLR-999'),
                    '{"schema":"x","schema":"y"}'):
            with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                worker.validate_proposal(raw, 'JLR-002', packet, self.cfg)

    def test_partial_or_forged_baseline_and_duplicate_target_rejected(self):
        packet, _, _ = self.packet()
        row = json.loads(self.proposal())
        for files in ([], [dict(row['files'][0], base_sha256='0' * 64)], row['files'] * 2):
            with self.subTest(files=files), self.assertRaises(ValueError):
                worker.validate_proposal(json.dumps({**row, 'files': files}), 'JLR-002', packet, self.cfg)

    def test_changed_target_while_model_runs_refuses_without_overwrite(self):
        def concurrent(*args):
            raw = self.proposal()
            self.output.parent.mkdir()
            self.output.write_text('real concurrent edit')
            return raw, {}
        with self.assertRaises(ValueError):
            worker.run(self.root, 'JLR-002', parser=parse_todo_blocks, caller=concurrent)
        self.assertEqual(self.output.read_text(), 'real concurrent edit')

    def test_symlink_or_hardlink_target_refused(self):
        self.output.parent.mkdir()
        outside = self.root / 'real.txt'; outside.write_text('untouched')
        self.output.symlink_to(outside)
        with self.assertRaises(ValueError): self.packet()
        self.output.unlink()
        __import__('os').link(outside, self.output)
        with self.assertRaises(ValueError): self.packet()
        self.assertEqual(outside.read_text(), 'untouched')

    def test_provider_failure_consumes_reserved_budget_and_does_not_write_output(self):
        def failure(*args): raise RuntimeError('real provider failure')
        for _ in range(3):
            with self.assertRaises(RuntimeError):
                worker.run(self.root, 'JLR-002', parser=parse_todo_blocks, caller=failure)
        with self.assertRaisesRegex(ValueError, 'budget exhausted'):
            worker.run(self.root, 'JLR-002', parser=parse_todo_blocks, caller=failure)
        self.assertFalse(self.output.exists())
        budget = json.loads((self.root / self.cfg['runtime_root'] / 'router-budget.json').read_text())
        self.assertEqual(budget['calls'], 3)

    def test_native_dependency_and_goal_dag_mismatch_refuse_before_call(self):
        path = self.root / self.cfg['taskboard']
        path.write_text(path.read_text().replace('Status: completed', 'Status: pending'))
        with self.assertRaisesRegex(ValueError, 'Dependency'): self.packet()
        path.write_text(path.read_text().replace('Status: pending', 'Status: completed', 1))
        self.dag['tasks'][0]['depends_on'] = []
        (self.root / self.cfg['goals']).write_text(json.dumps(self.dag))
        with self.assertRaisesRegex(ValueError, 'DAG dependencies'): self.packet()

    def test_existing_llm_adapter_gets_exact_route_and_actual_trace_is_required(self):
        from ipfs_accelerate_py.agent_supervisor.todo_daemon import llm
        directory = self.root / 'call'; directory.mkdir()
        seen = []
        def adapter(prompt, invocation):
            seen.append(invocation)
            self.assertEqual(__import__('os').environ.get('ipfs_accelerate_py_ROUTER_RESPONSE_CACHE'), '0')
            (directory / 'grok_cli_trace.jsonl').write_text(json.dumps({'provider': 'grok_cli', 'model': 'grok-4.7',
                'cmd': [self.cfg['grok_executable'], '--model', 'grok-4.7', '--tools', '']}) + '\n')
            return '{}', SimpleNamespace(status='ok', exit_code=0, effective_provider='grok_cli', to_dict=lambda: {'effective_provider': 'grok_cli'})
        with patch.object(llm, 'call_llm_router_with_receipt', adapter):
            worker.invoke('actual bounded prompt', self.cfg, directory)
        invocation = seen[0]
        self.assertEqual(invocation.provider, 'grok_cli')
        self.assertEqual(invocation.model_name, 'grok-4.7')
        self.assertEqual(invocation.required_effective_providers, ('grok_cli',))
        self.assertFalse(invocation.allow_cross_provider_fallback)
        self.assertFalse(invocation.allow_local_fallback)
        self.assertEqual(invocation.python_executable, self.cfg['python_executable'])

    def test_actual_trace_wrong_model_fails(self):
        from ipfs_accelerate_py.agent_supervisor.todo_daemon import llm
        directory = self.root / 'call'; directory.mkdir()
        def adapter(*args):
            (directory / 'grok_cli_trace.jsonl').write_text(json.dumps({'provider': 'grok_cli', 'model': 'grok-4.6'}) + '\n')
            return '{}', SimpleNamespace(status='ok', exit_code=0, effective_provider='grok_cli')
        with patch.object(llm, 'call_llm_router_with_receipt', adapter), self.assertRaises(ValueError):
            worker.invoke('actual prompt', self.cfg, directory)

    def test_natural_completion_preserves_receipt_but_source_change_invalidates(self):
        worker.run(self.root, 'JLR-002', parser=parse_todo_blocks, caller=self.complete_fake_call)
        self.assertTrue(worker.verify_task_receipt(self.root, 'JLR-002')['valid'])
        board = self.root / self.cfg['taskboard']
        original = board.read_text()
        from ipfs_accelerate_py.agent_supervisor.rescue.lane_resume import mark_task_completed
        board.write_text(mark_task_completed(original, 'JLR-002', task_header_prefix='## JLR-',
                                              note='lane_resume deterministic command exit 0 at actual test clock'))
        self.assertTrue(worker.verify_task_receipt(self.root, 'JLR-002')['valid'])
        board.write_text(board.read_text().replace('Unverified engineering review only.', 'Different task scope.'))
        with self.assertRaises(ValueError): worker.verify_task_receipt(self.root, 'JLR-002')

    def test_newer_failed_attempt_blocks_prior_success(self):
        worker.run(self.root, 'JLR-002', parser=parse_todo_blocks, caller=self.complete_fake_call)
        def failed(*args): raise RuntimeError('actual later attempt failed')
        with self.assertRaises(RuntimeError): worker.run(self.root, 'JLR-002', parser=parse_todo_blocks, caller=failed)
        with self.assertRaises(FileNotFoundError): worker.verify_task_receipt(self.root, 'JLR-002')

    def test_changed_raw_trace_or_output_refuses_readonly_verification(self):
        worker.run(self.root, 'JLR-002', parser=parse_todo_blocks, caller=self.complete_fake_call)
        info = worker.verify_task_receipt(self.root, 'JLR-002')
        trace = Path(info['result_path']).parent / 'grok_cli_trace.jsonl'
        original = trace.read_bytes(); trace.write_bytes(original + b' ')
        with self.assertRaises(ValueError): worker.verify_task_receipt(self.root, 'JLR-002')
        trace.write_bytes(original)
        self.output.write_text('different output')
        with self.assertRaises(ValueError): worker.verify_task_receipt(self.root, 'JLR-002')

    def test_input_read_bound_refuses_large_file_before_loading_body(self):
        path = self.root / 'oversized.txt'
        with path.open('wb') as stream: stream.truncate(1000000)
        with self.assertRaisesRegex(ValueError, 'bounded read'):
            worker.regular(path, maximum=32)

    def starter_fixture(self, *, validator_exit=0):
        spec = importlib.util.spec_from_file_location('jevops_starter_test_subject', ROOT / 'tools/start_lean_refactor_supervisor.py')
        starter = importlib.util.module_from_spec(spec); spec.loader.exec_module(starter)
        (self.root / starter.MANIFEST).write_text((ROOT / starter.MANIFEST).read_text())
        (self.root / 'tools').mkdir()
        (self.root / 'tools/check_lean_refactor_plan.py').write_text('raise SystemExit(' + str(validator_exit) + ')\n')
        board = self.root / self.cfg['taskboard']
        board.write_text(board.read_text().replace('- Depends on:\n', '- Depends on:\n- Deterministic command: python3 tools/inventory.py\n- Validation: python3 tools/check_lean_refactor_plan.py --check-task JLR-001\n')
                         .replace('- Provider role:', '- Deterministic command: python3 tools/run_lean_refactor_router_task.py --task-id JLR-002\n- Provider role:'))
        return starter

    def test_starter_runs_real_bounded_validator_without_launching(self):
        starter = self.starter_fixture()
        result = starter.preflight(self.root)[2]
        self.assertEqual(result['plan_validator_exit_code'], 0)
        self.assertEqual(result['provider_calls'], 0)
        self.assertFalse((self.root / self.cfg['runtime_root']).exists())

    def test_starter_refuses_real_validator_failure_before_launch(self):
        starter = self.starter_fixture(validator_exit=1)
        with self.assertRaisesRegex(ValueError, 'validator refused'):
            starter.preflight(self.root)
        self.assertFalse((self.root / self.cfg['runtime_root']).exists())

    def test_starter_refuses_command_alias_that_native_resume_would_never_execute(self):
        starter = self.starter_fixture()
        path = self.root / self.cfg['taskboard']
        path.write_text(path.read_text().replace('Deterministic command:', 'Command:'))
        with self.assertRaisesRegex(ValueError, 'genuine supervised command'):
            starter.preflight(self.root)

    def test_target_edit_during_temporary_fsync_is_not_overwritten(self):
        self.output.parent.mkdir()
        self.output.write_text('original user source')
        actual_fsync = worker.os.fsync
        injected = []
        def fsync(descriptor):
            path = str(Path('/proc/self/fd/' + str(descriptor)).resolve())
            if '/.JLR-002.review.json.' in path and not injected:
                injected.append(True)
                self.output.write_text('concurrent user source')
            return actual_fsync(descriptor)
        with patch.object(worker.os, 'fsync', fsync), self.assertRaisesRegex(ValueError, 'CAS changed'):
            worker.run(self.root, 'JLR-002', parser=parse_todo_blocks, caller=self.fake_call)
        self.assertTrue(injected)
        self.assertEqual(self.output.read_text(), 'concurrent user source')


if __name__ == '__main__':
    unittest.main()
