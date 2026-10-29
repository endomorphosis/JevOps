"""Offline lifecycle and real systemd-parser checks; never start a service."""
from contextlib import ExitStack
import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'jevops_persistent_watchdog_test_subject', ROOT / 'tools/manage_supervisor_watchdog.py')
watcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watcher)


class PersistentWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='jevops-watchdog-unit-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'campaign space % literal$ROOT'
        (self.root / 'config').mkdir(parents=True)
        self.cfg = json.loads((ROOT / watcher.CONFIG).read_text())
        self.supervisor = json.loads((ROOT / self.cfg['supervisor_profile']).read_text())
        self.lanes = json.loads((ROOT / self.cfg['lane_manifest']).read_text())
        self.write_profiles()
        (self.root / self.cfg['provider_budget_policy']).write_text(json.dumps({'new_calls_allowed': False}))
        (self.root / self.cfg['repair_prompt']).write_text(
            (ROOT / self.cfg['repair_prompt']).read_text())
        (self.root / 'tools').mkdir()
        (self.root / 'tools/reload_supervisor_when_idle.py').write_text('# Private nonexecuting path fixture\n')
        self.manifest = self.root / self.cfg['runtime_manifest']
        self.manifest.parent.mkdir(parents=True)
        self.proc = self.base / 'private-proc'
        self.proc.mkdir()
        self.home = self.base / 'private-home'
        self.home.mkdir()

    def write_profiles(self):
        for relative, value in [(watcher.CONFIG, self.cfg),
                                (self.cfg['supervisor_profile'], self.supervisor),
                                (self.cfg['lane_manifest'], self.lanes)]:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))

    def guardian(self, pid=41, *, start='123456', extra=(), root=None, manifest=None):
        directory = self.proc / str(pid)
        directory.mkdir(exist_ok=True)
        argv = [self.supervisor['python_executable'], '-m', watcher.GUARDIAN,
                '--manifest-path', str(self.manifest if manifest is None else manifest),
                '--repo-root', str(self.root if root is None else root), '--apply', *extra]
        (directory / 'cmdline').write_bytes(b'\0'.join(x.encode() for x in argv) + b'\0')
        (directory / 'stat').write_text(
            f'{pid} (private guardian) ' + ' '.join(['S'] + ['0'] * 18 + [start] + ['0'] * 5))
        for name, target in [('exe', Path(self.supervisor['python_executable']).resolve()),
                             ('cwd', self.root)]:
            (directory / name).unlink(missing_ok=True)
            (directory / name).symlink_to(target)
        return directory

    def identity(self, pid=41):
        return watcher.guardian_identity(pid, self.root, self.manifest,
                                         self.supervisor['python_executable'], proc_root=self.proc)

    def migration_context(self):
        stack = ExitStack()
        actual_path = Path
        actual_identity = watcher.guardian_identity
        stack.enter_context(patch.object(watcher, 'Path', side_effect=lambda value:
            self.proc if str(value) == '/proc' else actual_path(value)))
        stack.enter_context(patch.object(watcher, 'guardian_identity', side_effect=lambda pid, *a, **kw:
            actual_identity(pid, *a, proc_root=self.proc)))
        return stack

    def test_render_uses_real_systemd_parser_without_starting_anything(self):
        _, _, units = watcher.render(self.root)
        rendered = self.base / 'parser-input'
        rendered.mkdir()
        paths = []
        for name, content in units.items():
            path = rendered / name
            path.write_text(content)
            paths.append(str(path))
        result = subprocess.run(['systemd-analyze', '--user', 'verify', *paths],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / self.cfg['state_root']).exists())

    def test_render_is_deterministic_and_preserves_all_runtime_inputs(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(watcher.render(self.root), watcher.render(self.root))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_units_persist_but_preserve_native_child_lifecycle_and_limits(self):
        _, _, units = watcher.render(self.root)
        for name in (self.cfg['guardian_unit'], self.cfg['repair_unit']):
            content = units[name]
            for literal in ('Restart=always\n', 'StartLimitIntervalSec=0\n', 'KillMode=process\n',
                            'WantedBy=default.target\n', 'StandardOutput=journal\n',
                            'CPUAccounting=yes\n', 'MemoryAccounting=yes\n',
                            'Environment=PYTHONDONTWRITEBYTECODE=1\n'):
                self.assertIn(literal, content)
            self.assertNotIn('CPUQuota=', content)
            self.assertNotIn('MemoryMax=', content)
            self.assertNotIn('ConditionPathExists=', content)
            if name == self.cfg['repair_unit']:
                self.assertIn('WatchdogSec=120s\n', content)
                self.assertIn('NotifyAccess=main\n', content)
                self.assertIn('WatchdogSignal=SIGKILL\n', content)
            else:
                self.assertNotIn('WatchdogSec=', content)
        repair = units[self.cfg['repair_unit']]
        self.assertIn(watcher.DISPATCHER, repair)
        for argument, value in [('worker-timeout', self.cfg['worker_timeout_seconds']), ('max-attempts', 3),
                                ('heartbeat-seconds', 120), ('report-seconds', 600)]:
            self.assertIn(f'"--{argument}" "{value}"', repair)
        self.assertIn('"--hold-path"', repair)
        self.assertIn('"--worker-argv-json"', repair)
        self.assertIn('"--python"', units[self.cfg['guardian_unit']])
        self.assertEqual(self.lanes['lanes'][0]['max_resume_seconds'], 14400)

    def test_service_watchdog_requires_one_explicit_native_capability_without_executing_code(self):
        source = self.base / 'private-framework'
        path = source / 'ipfs_accelerate_py/agent_supervisor/rescue/repair_dispatcher.py'
        path.parent.mkdir(parents=True)
        sentinel = self.base / 'must-not-execute'
        path.write_text('SERVICE_WATCHDOG_VERSION = 1\n'
                        + 'from pathlib import Path\nPath(' + repr(str(sentinel)) + ').touch()\n')
        watcher.require_native_service_watchdog(source)
        self.assertFalse(sentinel.exists())
        for value in ('', 'SERVICE_WATCHDOG_VERSION = True\n',
                      'SERVICE_WATCHDOG_VERSION = 0\n', 'SERVICE_WATCHDOG_VERSION = "1"\n',
                      'SERVICE_WATCHDOG_VERSION = 1\nSERVICE_WATCHDOG_VERSION = 2\n'):
            with self.subTest(value=value):
                path.write_text(value)
                with self.assertRaises(ValueError):
                    watcher.require_native_service_watchdog(source)

    def test_install_refuses_missing_native_notification_before_any_control_or_unit_write(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(watcher, 'require_native_service_watchdog',
                          side_effect=ValueError('notification support missing')) as guard, \
             patch.object(watcher, 'command') as command:
            with self.assertRaisesRegex(ValueError, 'notification support'):
                watcher._install_locked(self.root)
        guard.assert_called_once_with(self.supervisor['accelerator_source'])
        command.assert_not_called()
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_provider_freeze_requires_actual_adapter_capability_without_executing_code(self):
        source = self.base / 'private-framework'
        path = source / 'ipfs_accelerate_py/agent_supervisor/todo_daemon/llm.py'
        path.parent.mkdir(parents=True)
        sentinel = self.base / 'must-not-execute-budget-adapter'
        path.write_text('PROVIDER_BUDGET_POLICY_VERSION = 1\n'
                        + 'from pathlib import Path\nPath(' + repr(str(sentinel)) + ').touch()\n')
        watcher.require_native_provider_budget_policy(source)
        self.assertFalse(sentinel.exists())
        for value in ('', 'PROVIDER_BUDGET_POLICY_VERSION = True\n',
                      'PROVIDER_BUDGET_POLICY_VERSION = 0\n',
                      'PROVIDER_BUDGET_POLICY_VERSION = "1"\n',
                      'PROVIDER_BUDGET_POLICY_VERSION = 1\nPROVIDER_BUDGET_POLICY_VERSION = 2\n'):
            with self.subTest(value=value):
                path.write_text(value)
                with self.assertRaises(ValueError):
                    watcher.require_native_provider_budget_policy(source)

    def test_install_refuses_unenforceable_provider_freeze_before_any_unit_write(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(watcher, 'require_native_service_watchdog'), \
             patch.object(watcher, 'require_native_provider_budget_policy',
                          side_effect=ValueError('provider-budget freeze support missing')) as guard, \
             patch.object(watcher, 'command') as command:
            with self.assertRaisesRegex(ValueError, 'provider-budget freeze support'):
                watcher._install_locked(self.root)
        guard.assert_called_once_with(self.supervisor['accelerator_source'])
        command.assert_not_called()
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_render_scopes_provider_freeze_to_managed_daemons(self):
        units = watcher.render(self.root)[2]
        expected = 'JEVOPS_REFACTOR_LLM_BUDGET_POLICY=' + str(self.root / self.cfg['provider_budget_policy'])
        for name in (self.cfg['guardian_unit'], self.cfg['repair_unit']):
            self.assertIn('Environment=' + watcher.systemd_arg(expected) + '\n', units[name])
        self.assertNotIn('JEVOPS_REFACTOR_LLM_BUDGET_POLICY', units[watcher.RELOAD_UNIT])

    def test_render_requires_observed_lane_policy_on_the_repair_service(self):
        units = watcher.render(self.root)[2]
        expected = watcher.systemd_arg('--required-lane-env',exec_start=True)+' '+watcher.systemd_arg('JEVOPS_REFACTOR_LLM_BUDGET_POLICY',exec_start=True)
        self.assertIn(expected,units[self.cfg['repair_unit']])
        self.assertNotIn('--required-lane-env',units[self.cfg['guardian_unit']])
        self.assertNotIn('--required-lane-env',units[watcher.RELOAD_UNIT])

    def test_maintenance_storage_reserve_is_validated_before_rendering(self):
        for value in (None, True, 0, -1, '2147483648', 64 * 1024 * 1024 - 1, 8 * 1024 ** 3 + 1):
            with self.subTest(value=value):
                self.cfg['worker_minimum_free_bytes'] = value
                self.write_profiles()
                with self.assertRaisesRegex(ValueError, 'storage reserve'):
                    watcher.render(self.root)
        for value in (64 * 1024 * 1024, 2 * 1024 ** 3, 8 * 1024 ** 3):
            with self.subTest(value=value):
                self.cfg['worker_minimum_free_bytes'] = value
                self.write_profiles()
                units = watcher.render(self.root)[2]
                expected = watcher.systemd_arg('--worker-min-free-bytes', exec_start=True) + ' ' + watcher.systemd_arg(value, exec_start=True)
                self.assertIn(expected, units[self.cfg['repair_unit']])
                self.assertNotIn('--worker-min-free-bytes', units[self.cfg['guardian_unit']])
                self.assertNotIn('--worker-min-free-bytes', units[watcher.RELOAD_UNIT])

    def test_worker_storage_admission_capability_is_static_and_exact(self):
        source = self.base / 'private-worker-storage-framework'
        path = source / 'ipfs_accelerate_py/agent_supervisor/rescue/repair_dispatcher.py'
        path.parent.mkdir(parents=True)
        sentinel = self.base / 'must-not-execute-storage-adapter'
        path.write_text('WORKER_STORAGE_ADMISSION_VERSION = 1\n'
                        + 'from pathlib import Path\nPath(' + repr(str(sentinel)) + ').touch()\n')
        watcher.require_native_worker_storage_admission(source)
        self.assertFalse(sentinel.exists())
        for value in ('', 'WORKER_STORAGE_ADMISSION_VERSION = True\n',
                      'WORKER_STORAGE_ADMISSION_VERSION = 0\n',
                      'WORKER_STORAGE_ADMISSION_VERSION = "1"\n',
                      'WORKER_STORAGE_ADMISSION_VERSION = 1\nWORKER_STORAGE_ADMISSION_VERSION = 2\n'):
            with self.subTest(value=value):
                path.write_text(value)
                with self.assertRaises(ValueError):
                    watcher.require_native_worker_storage_admission(source)

    def test_install_refuses_missing_worker_storage_admission_before_unit_writes(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(watcher, 'require_native_service_watchdog'), \
             patch.object(watcher, 'require_native_provider_budget_policy'), \
             patch.object(watcher, 'require_native_lane_environment_guard'), \
             patch.object(watcher, 'require_native_worker_storage_admission', side_effect=ValueError('worker-storage support missing')) as guard, \
             patch.object(watcher, 'command') as command:
            with self.assertRaisesRegex(ValueError, 'worker-storage support'):
                watcher._install_locked(self.root)
        guard.assert_called_once_with(self.supervisor['accelerator_source'])
        command.assert_not_called()
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_lane_environment_capability_is_static_and_exact(self):
        source = self.base / 'private-lane-environment-framework'
        path = source / 'ipfs_accelerate_py/agent_supervisor/rescue/repair_dispatcher.py'
        path.parent.mkdir(parents=True)
        sentinel = self.base / 'must-not-execute-lane-environment-adapter'
        path.write_text('LANE_ENVIRONMENT_GUARD_VERSION = 1\n'
                        + 'from pathlib import Path\nPath(' + repr(str(sentinel)) + ').touch()\n')
        watcher.require_native_lane_environment_guard(source)
        self.assertFalse(sentinel.exists())
        for value in ('', 'LANE_ENVIRONMENT_GUARD_VERSION = True\n',
                      'LANE_ENVIRONMENT_GUARD_VERSION = 0\n',
                      'LANE_ENVIRONMENT_GUARD_VERSION = "1"\n',
                      'LANE_ENVIRONMENT_GUARD_VERSION = 1\nLANE_ENVIRONMENT_GUARD_VERSION = 2\n'):
            with self.subTest(value=value):
                path.write_text(value)
                with self.assertRaises(ValueError):
                    watcher.require_native_lane_environment_guard(source)

    def test_install_refuses_unobserved_lane_environment_before_any_unit_write(self):
        before = {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(watcher,'require_native_service_watchdog'), \
             patch.object(watcher,'require_native_provider_budget_policy'), \
             patch.object(watcher,'require_native_lane_environment_guard',side_effect=ValueError('lane-environment support missing')) as guard, \
             patch.object(watcher,'command') as command:
            with self.assertRaisesRegex(ValueError,'lane-environment support'):
                watcher._install_locked(self.root)
        guard.assert_called_once_with(self.supervisor['accelerator_source'])
        command.assert_not_called()
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_invalid_provider_freeze_cannot_be_rendered(self):
        policy = self.root / self.cfg['provider_budget_policy']
        for value in ({}, {'new_calls_allowed': True}, {'new_calls_allowed': 0}):
            with self.subTest(value=value):
                policy.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError, 'provider freeze'):
                    watcher.render(self.root)

    def test_third_reload_unit_is_bounded_manual_oneshot_without_install_target(self):
        units = watcher.render(self.root)[2]
        self.assertEqual(set(units), {self.cfg['guardian_unit'], self.cfg['repair_unit'], watcher.RELOAD_UNIT})
        text = units[watcher.RELOAD_UNIT]
        for literal in ('Type=oneshot\n', 'Restart=no\n', 'SuccessExitStatus=75\n',
                        'TimeoutStartSec=1810s\n', 'KillMode=control-group\n', 'MemoryMax=512M\n',
                        'TasksMax=32\n', '"--timeout" "1800"', 'reload_supervisor_when_idle.py'):
            self.assertIn(literal, text)
        self.assertNotIn('[Install]', text)
        self.assertNotIn('WantedBy=', text)
        self.assertNotIn('Requires=', text)

    def test_systemd_dollars_are_escaped_only_in_execstart(self):
        value = 'space % literal$ROOT "quote" \\ path'
        plain = watcher.systemd_arg(value)
        executable = watcher.systemd_arg(value, exec_start=True)
        self.assertEqual(json.loads(plain), value.replace('%', '%%'))
        self.assertEqual(json.loads(executable), value.replace('%', '%%').replace('$', '$$'))
        for content in watcher.render(self.root)[2].values():
            self.assertIn('literal$$ROOT', next(line for line in content.splitlines() if line.startswith('ExecStart=')))
            self.assertIn('literal$ROOT', next(line for line in content.splitlines() if line.startswith('WorkingDirectory=')))
        with self.assertRaises(ValueError):
            watcher.systemd_arg('unsafe\nargument')
        self.assertEqual(watcher.systemd_path('/tmp/a space % $literal'), '/tmp/a space %% $literal')
        for value in ('relative/path', '/tmp/path\\continuation', '/tmp/path\nnext', '/tmp/trailing '):
            with self.subTest(value=value), self.assertRaises(ValueError):
                watcher.systemd_path(value)

    def test_profile_rejects_zero_overbound_and_boolean_budgets(self):
        limits = {'poll_seconds': 60, 'heartbeat_seconds': 600, 'report_seconds': 1800,
                  'quiet_seconds': 3600, 'startup_grace_seconds': 600,
                  'worker_timeout_seconds': 1800, 'cooldown_seconds': 3600,
                  'max_cooldown_seconds': 14400, 'max_repair_attempts': 3}
        original = copy.deepcopy(self.cfg)
        for key, limit in limits.items():
            for value in (0, limit + 1, True):
                with self.subTest(key=key, value=value):
                    self.cfg = {**original, key: value}
                    self.write_profiles()
                    with self.assertRaises(ValueError): watcher.profile(self.root)

    def test_profile_rejects_activation_budget_reset_route_and_path_escape(self):
        original = copy.deepcopy(self.cfg)
        for key in ('activate_planned_work', 'reset_campaign_budgets'):
            self.cfg = {**original, key: True}; self.write_profiles()
            with self.assertRaises(ValueError): watcher.profile(self.root)
        self.cfg = original
        for key, value in [('provider', 'other'), ('model', 'grok-4.6'), ('allow_local_fallback', True)]:
            self.supervisor = {**json.loads((ROOT / self.cfg['supervisor_profile']).read_text()), key: value}
            self.write_profiles()
            with self.assertRaises(ValueError): watcher.profile(self.root)
        self.supervisor = json.loads((ROOT / self.cfg['supervisor_profile']).read_text())
        self.cfg = {**original, 'state_root': '../another-repository'}; self.write_profiles()
        with self.assertRaises(ValueError): watcher.profile(self.root)
        self.cfg = {**original, 'state_root': 'escaped-state'}
        (self.root / 'escaped-state').symlink_to(self.base)
        self.write_profiles()
        with self.assertRaises(ValueError): watcher.profile(self.root)

    def test_exact_guardian_identity_includes_kernel_start(self):
        self.guardian()
        identity = self.identity()
        self.assertEqual(identity['pid'], 41)
        self.assertEqual(identity['start_ticks'], '123456')
        self.assertEqual(identity['uid'], os.getuid())

    def test_guardian_identity_refuses_relative_or_wrong_scope_duplicate_flags_and_zombies(self):
        cases = [dict(root='.'), dict(manifest='relative.json'), dict(root=self.base),
                 dict(extra=('--repo-root', str(self.root))), dict(extra=('--apply',)),
                 dict(extra=('--unknown', 'value'))]
        for fields in cases:
            with self.subTest(fields=fields):
                self.guardian(**fields)
                self.assertIsNone(self.identity())
        directory = self.guardian()
        (directory / 'cwd').unlink(); (directory / 'cwd').symlink_to(self.base)
        self.assertIsNone(self.identity())
        directory = self.guardian()
        stat_text = (directory / 'stat').read_text().replace(') S ', ') Z ')
        (directory / 'stat').write_text(stat_text)
        self.assertIsNone(self.identity())

    def test_guardian_identity_refuses_another_uid_executable_or_module(self):
        self.guardian()
        with patch.object(watcher.os, 'getuid', return_value=os.getuid() + 1):
            self.assertIsNone(self.identity())
        directory = self.guardian()
        (directory / 'exe').unlink(); (directory / 'exe').symlink_to('/usr/bin/true')
        self.assertIsNone(self.identity())
        directory = self.guardian()
        raw = (directory / 'cmdline').read_bytes().replace(watcher.GUARDIAN.encode(), b'unrelated.module')
        (directory / 'cmdline').write_bytes(raw)
        self.assertIsNone(self.identity())

    def test_duplicate_guardians_are_refused_before_opening_any_pidfd(self):
        self.guardian(41); self.guardian(42)
        with self.migration_context(), patch.object(watcher.os, 'pidfd_open') as opened:
            with self.assertRaisesRegex(ValueError, 'Duplicate guardians'):
                watcher.migrate_guardian(self.root, self.cfg, self.supervisor)
        opened.assert_not_called()

    def test_pid_reuse_between_scan_and_signal_is_refused(self):
        self.guardian()
        fd = os.open(self.base / 'private-pidfd', os.O_CREAT | os.O_RDONLY, 0o600)
        def reused(pid):
            self.guardian(start='999999')
            return fd
        with self.migration_context(), patch.object(watcher.os, 'pidfd_open', side_effect=reused), \
                patch.object(watcher.signal, 'pidfd_send_signal') as sent:
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                watcher.migrate_guardian(self.root, self.cfg, self.supervisor)
        sent.assert_not_called()
        with self.assertRaises(OSError): os.fstat(fd)

    def test_migration_signals_only_the_exact_guardian_and_retains_watchdog(self):
        directory = self.guardian()
        watchdog = self.proc / '73'; watchdog.mkdir(); (watchdog / 'untouched').write_bytes(b'healthy watchdog')
        fd = os.open(self.base / 'private-pidfd', os.O_CREAT | os.O_RDONLY, 0o600)
        def exit_guardian(actual_fd, actual_signal):
            self.assertEqual(actual_fd, fd)
            self.assertEqual(actual_signal, watcher.signal.SIGTERM)
            shutil.rmtree(directory)
        with self.migration_context(), patch.object(watcher.os, 'pidfd_open', return_value=fd) as opened, \
                patch.object(watcher.signal, 'pidfd_send_signal', side_effect=exit_guardian) as sent:
            report = watcher.migrate_guardian(self.root, self.cfg, self.supervisor)
        opened.assert_called_once_with(41); sent.assert_called_once()
        self.assertEqual(report['migrated_pid'], 41)
        self.assertIs(report['watchdog_signaled'], False)
        self.assertEqual((watchdog / 'untouched').read_bytes(), b'healthy watchdog')

    def test_migration_waits_for_kernel_lock_after_guardian_identity_disappears(self):
        directory = self.guardian()
        lock = (self.manifest.parent / 'watchdog-guardian.lock').open('a+')
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = os.open(self.base / 'private-pidfd', os.O_CREAT | os.O_RDONLY, 0o600)
        blocked = threading.Event()
        released = threading.Event()
        real_flock = fcntl.flock
        attempts = []

        def actual_lock_attempt(descriptor, operation):
            try:
                return real_flock(descriptor, operation)
            except BlockingIOError:
                attempts.append('kernel-lock-still-owned')
                blocked.set()
                raise

        def kernel_finishes_exit():
            # Keep the real flock until migration actually observes contention,
            # rather than depending on a sleep or a mocked successful flock.
            if blocked.wait(2):
                lock.close()
                released.set()

        release_thread = threading.Thread(target=kernel_finishes_exit)
        release_thread.start()
        try:
            def identity_disappears(actual_fd, actual_signal):
                self.assertEqual(actual_fd, fd)
                self.assertEqual(actual_signal, watcher.signal.SIGTERM)
                shutil.rmtree(directory)
                self.assertFalse(lock.closed)

            with self.migration_context(), patch.object(watcher.os, 'pidfd_open', return_value=fd), \
                    patch.object(watcher.signal, 'pidfd_send_signal', side_effect=identity_disappears) as sent, \
                    patch.object(watcher.fcntl, 'flock', side_effect=actual_lock_attempt):
                result = watcher.migrate_guardian(self.root, self.cfg, self.supervisor)
        finally:
            release_thread.join(timeout=3)
        self.assertFalse(release_thread.is_alive())
        self.assertTrue(released.is_set())
        self.assertGreaterEqual(len(attempts), 1)
        sent.assert_called_once()
        self.assertEqual(result['migrated_pid'], 41)
        self.assertIs(result['watchdog_signaled'], False)

    def test_repeat_install_keeps_same_unit_bytes_and_does_not_migrate_managed_guardian(self):
        calls = []
        def fake_command(argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch.object(watcher.Path, 'home', return_value=self.home), \
                patch.object(watcher, 'command', side_effect=fake_command), \
                patch.object(watcher, 'migrate_guardian') as migrate:
            first = watcher.install(self.root)
            unit_dir = self.home / '.config/systemd/user'
            before = {p.name: p.read_bytes() for p in unit_dir.iterdir()}
            second = watcher.install(self.root)
            self.assertEqual(before, {p.name: p.read_bytes() for p in unit_dir.iterdir()})
        migrate.assert_not_called()
        self.assertIs(first['planned_work_activated'], False)
        self.assertEqual(second['provider_calls'], 0)
        self.assertTrue(any(a[:3] == ['systemctl', '--user', 'enable'] for a in calls))
        for argv in calls:
            if argv[:3] in (['systemctl', '--user', 'enable'], ['systemctl', '--user', 'start']):
                self.assertEqual(argv[3:], [self.cfg['guardian_unit'], self.cfg['repair_unit']])
            if argv[:3] == ['systemd-analyze', '--user', 'verify']:
                self.assertEqual({Path(p).name for p in argv[3:]}, set(before))
        self.assertEqual(first['manual_units_not_enabled_or_started'], [watcher.RELOAD_UNIT])
        self.assertFalse((self.root / self.cfg['state_root'] / 'unit-backups').exists())

    def test_reviewed_static_reload_adoption_is_exact_scoped_backed_up_and_manual(self):
        legacy = '# Explicit previously reviewed operator reload unit\n[Service]\nType=oneshot\n'
        digest = __import__('hashlib').sha256(legacy.encode()).hexdigest()
        target = self.home / '.config/systemd/user' / watcher.RELOAD_UNIT
        target.parent.mkdir(parents=True); target.write_text(legacy)
        calls = []
        def fake_command(argv, **kwargs):
            calls.append(argv); return SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch.object(watcher.Path, 'home', return_value=self.home), \
                patch.object(watcher, 'LEGACY_RELOAD_UNIT_SHA256', digest), \
                patch.object(watcher, 'command', side_effect=fake_command):
            report = watcher.install(self.root)
        self.assertTrue(target.read_text().startswith('# Managed by JevOps tools/manage_supervisor_watchdog.py'))
        backup = self.root / self.cfg['state_root'] / 'unit-backups' / (watcher.RELOAD_UNIT + '.' + digest)
        self.assertEqual(backup.read_text(), legacy)
        self.assertEqual(report['manual_units_not_enabled_or_started'], [watcher.RELOAD_UNIT])
        for argv in calls:
            if argv[:3] in (['systemctl', '--user', 'enable'], ['systemctl', '--user', 'start']):
                self.assertNotIn(watcher.RELOAD_UNIT, argv)

    def test_other_operator_reload_bytes_are_not_adopted(self):
        target = self.home / '.config/systemd/user' / watcher.RELOAD_UNIT
        target.parent.mkdir(parents=True); target.write_text('# Unreviewed operator unit\n')
        with patch.object(watcher.Path, 'home', return_value=self.home), \
                patch.object(watcher, 'command', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')) as call:
            with self.assertRaisesRegex(ValueError, 'unmanaged'):
                watcher.install(self.root)
        self.assertFalse(any(c.args[0][:3] == ['systemctl', '--user', 'start'] for c in call.call_args_list))
        self.assertEqual(target.read_text(), '# Unreviewed operator unit\n')

    def test_static_reload_adoption_pins_raw_bytes_without_newline_normalization(self):
        legacy = '# Reviewed operator reload\n[Service]\nType=oneshot\n'
        digest = __import__('hashlib').sha256(legacy.encode()).hexdigest()
        target = self.home / '.config/systemd/user' / watcher.RELOAD_UNIT
        target.parent.mkdir(parents=True); target.write_bytes(legacy.replace('\n', '\r\n').encode())
        original = target.read_bytes()
        with patch.object(watcher.Path, 'home', return_value=self.home), \
                patch.object(watcher, 'LEGACY_RELOAD_UNIT_SHA256', digest), \
                patch.object(watcher, 'command', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')):
            with self.assertRaisesRegex(ValueError, 'unmanaged'):
                watcher.install(self.root)
        self.assertEqual(target.read_bytes(), original)

    def test_execution_v2_profile_preflight_is_preserved_and_unknown_profile_refused(self):
        self.lanes['execution_profile'] = 'config/lean_refactor_arena_20261024_execution_v2.json'
        self.write_profiles()
        with patch.object(watcher.Path, 'home', return_value=self.home), \
                patch.object(watcher, 'command', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')) as call:
            watcher.install(self.root)
        matches = [c for c in call.call_args_list if str(self.root / 'tools/lean_refactor_execution_v2.py') in c.args[0]]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].kwargs['timeout'], 1200)
        self.lanes['execution_profile'] = 'config/unreviewed_execution.json'; self.write_profiles()
        with patch.object(watcher, 'command', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')) as call:
            with self.assertRaisesRegex(ValueError, 'Unknown research execution profile'):
                watcher.install(self.root)
        self.assertFalse(any(c.args[0][:2] == ['systemctl', '--user'] for c in call.call_args_list))

    def test_install_refuses_unmanaged_unit_without_starting_or_signaling(self):
        destination = self.home / '.config/systemd/user' / self.cfg['guardian_unit']
        destination.parent.mkdir(parents=True)
        destination.write_text('[Service]\nExecStart=/bin/sleep infinity\n')
        before = destination.read_bytes()
        with patch.object(watcher.Path, 'home', return_value=self.home), \
                patch.object(watcher, 'command', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')) as command, \
                patch.object(watcher, 'migrate_guardian') as migrate:
            with self.assertRaisesRegex(ValueError, 'unmanaged'):
                watcher.install(self.root)
        migrate.assert_not_called()
        self.assertFalse(any(a.args[0][:3] == ['systemctl', '--user', 'start'] for a in command.call_args_list))
        self.assertEqual(destination.read_bytes(), before)

    def test_install_refuses_concurrent_installer_under_real_private_flock(self):
        state = self.root / self.cfg['state_root']
        state.mkdir(parents=True)
        # The installer exposes its exact lock name through its source, and
        # this test holds the actual inode rather than mocking flock success.
        candidates = ('installation.lock', 'install.lock')
        source = Path(watcher.__file__).read_text()
        selected = next((name for name in candidates if repr(name) in source or '"' + name + '"' in source), None)
        self.assertIsNotNone(selected, 'Expected explicit installer lock filename')
        with (state / selected).open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(watcher, 'command') as command:
                with self.assertRaises((OSError, ValueError)):
                    watcher.install(self.root)
            command.assert_not_called()

    def test_native_dispatcher_never_calls_repair_provider_for_planned_only_backlog(self):
        source = self.supervisor['accelerator_source']
        sys.path.insert(0, source)
        from ipfs_accelerate_py.agent_supervisor.rescue import repair_dispatcher as dispatcher
        board = self.root / 'private.todo.md'
        board.write_text('''# Private planned campaign
## JLR-001 Bootstrap complete
- Status: completed
## JLR-016 Unactivated experiment
- Status: planned
- Depends on: JLR-001
''')
        manifest = copy.deepcopy(self.lanes)
        manifest['todo_path'] = board.name
        self.manifest.write_text(json.dumps(manifest))
        state_dir = self.root / self.cfg['state_root'] / 'private-native-dispatch'
        cfg = dispatcher.Config(manifest_path=self.manifest, repo_root=self.root, state_dir=state_dir,
                                evidence_paths=(ROOT / 'tools/manage_supervisor_watchdog.py',))
        dead = {'pid': 0, 'alive': False, 'argv': []}
        worker_calls = []
        def forbidden_worker(*args, **kwargs):
            worker_calls.append(1)
            raise AssertionError('Planned backlog must not call a repair provider')
        with patch.object(dispatcher, '_find_owner', return_value=(dead, [], [])), \
                patch.object(dispatcher, 'lane_storage_emergency', return_value=None):
            result = dispatcher.tick(cfg, {}, apply=True, probe=lambda pid: {**dead, 'pid': pid},
                                     worker=forbidden_worker)
        self.assertEqual(result['action'], 'healthy')
        self.assertEqual(result['incidents'], [])
        self.assertEqual(worker_calls, [])
        self.assertEqual(board.read_text().count('Status: planned'), 1)


if __name__ == '__main__':
    unittest.main()
