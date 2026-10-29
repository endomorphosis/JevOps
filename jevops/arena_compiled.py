"""Explicit fresh native checker; the historical interpreted adapter is intact.

This compiles the unchanged trusted driver at an exact project pin. It neither
reuses a proof cache nor substitutes an installed compiler for a missing pin.
Build and execution identities participate in the new verifier context.
"""
from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import tempfile
import time
import uuid

from . import arena_lean as native
from .arena import Outcome, VerificationRequest, VersionReceipt, content_hash, intake_error, source_hash, _units
from .arena_isolation import IsolationUnavailable
from .proof_ca import canonical_json

DRIVER, METHOD = Path(__file__).parent / 'lean/ArenaAuditCheck.lean', native.METHOD
POLICY = 'jevops-arena-fresh-mixed-native/selective-audit-v3'
MAX_BYTES, MAX_MEMORY = 128 * 1024**2, 4 * 1024**3
LIBRARIES = ('libleanshared.so', 'libLean.a', 'libStd.a', 'libInit.a', 'libleanrt.a', 'libleancpp.a')


def sha(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError('ordinary native input required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def actor(pid):
    proc = Path('/proc') / str(pid)
    fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
    if fields[0] == 'Z':
        raise ProcessLookupError('exited owned native actor')
    return {'uid': proc.stat().st_uid, 'start': fields[19], 'session': int(fields[3]),
            'exe': str((proc / 'exe').resolve()), 'cwd': str((proc / 'cwd').resolve())}


def session_actors(session, born, cwd):
    result = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[3]) != session:
                continue
            identity = actor(int(proc.name))
            if identity['uid'] != os.getuid() or int(identity['start']) < int(born) or identity['cwd'] != str(cwd.resolve()):
                raise ValueError('owned native session identity differs')
            result.append((int(proc.name), identity))
        except (FileNotFoundError, ProcessLookupError):
            pass
    return result


def cleanup(session, born, cwd):
    observations = []
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid, identity in reversed(session_actors(session, born, cwd)):
            try:
                fd = os.pidfd_open(pid)
                try:
                    if actor(pid) != identity:
                        raise ValueError('native actor changed before pidfd cleanup')
                    signal.pidfd_send_signal(fd, sig)
                    observations.append({'start_ticks': identity['start'], 'signal': int(sig)})
                finally:
                    os.close(fd)
            except (FileNotFoundError, ProcessLookupError):
                pass
        if sig == signal.SIGTERM:
            until = time.monotonic() + .2
            while time.monotonic() < until and session_actors(session, born, cwd):
                time.sleep(.01)
    return observations


def limits():
    resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY, MAX_MEMORY))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))


def capture(argv, directory, env, payload, timeout):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError('unchanged bounded native timeout required')
    directory.mkdir()
    raw = canonical_json(payload).encode()
    (directory / 'input.json').write_bytes(raw)
    started = time.monotonic()
    timed_out = False
    signaled = []
    with (directory / 'input.json').open('rb') as inp, (directory / 'stdout').open('xb') as out, (directory / 'stderr').open('xb') as err:
        child = subprocess.Popen(argv, cwd=directory, env=env, stdin=inp, stdout=out, stderr=err,
                                 start_new_session=True, preexec_fn=limits)
        born = int(float(Path('/proc/uptime').read_text().split()[0]) * os.sysconf('SC_CLK_TCK')) - 2
        fd = os.pidfd_open(child.pid)
        try:
            identity = None
            try:
                identity = actor(child.pid)
            except (FileNotFoundError, ProcessLookupError):
                if child.poll() is None:
                    raise ValueError('native child vanished before ownership read')
            if identity is not None and (identity['uid'] != os.getuid() or identity['session'] != child.pid
                                        or identity['cwd'] != str(directory.resolve())):
                raise ValueError('native child ownership differs')
            try:
                code = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out, code = True, 124
        finally:
            previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
            try:
                signaled = cleanup(child.pid, identity['start'] if identity else born, directory)
                child.wait(timeout=3)
            finally:
                os.close(fd)
                signal.pthread_sigmask(signal.SIG_SETMASK, previous)
    if any((directory / name).stat().st_size > native.MAX_OUTPUT for name in ('stdout', 'stderr')):
        raise ValueError('native output byte budget')
    output, errors = (directory / 'stdout').read_bytes(), (directory / 'stderr').read_bytes()
    observation = {'argv': list(map(str, argv)), 'exit_code': code, 'timed_out': timed_out,
                   'timeout_seconds': timeout, 'wall_seconds': time.monotonic() - started,
                   'process_reaped': child.poll() is not None, 'pidfd_cleanup': True, 'cleanup': signaled,
                   'max_process_address_space_bytes': MAX_MEMORY, 'max_artifact_bytes': MAX_BYTES,
                   'input_sha256': hashlib.sha256(raw).hexdigest(),
                   'stdout_sha256': hashlib.sha256(output).hexdigest(), 'stderr_sha256': hashlib.sha256(errors).hexdigest()}
    return output, errors, code, observation


def link_command(lean, exe, cfile):
    return [str(lean.with_name('leanc')), '-leanshared', '-O1', '-Wl,--strip-all',
            '-Wl,-rpath,' + str(lean.parent.parent / 'lib/lean'), '-o', str(exe), str(cfile),
            '-Wl,--no-as-needed', '-lleanshared', '-Wl,--as-needed', '-Wl,--start-group',
            '-lLean', '-lStd', '-lInit', '-lleanrt', '-lleancpp', '-Wl,--end-group']


def environment(binding, directory):
    return {'PATH': str(binding.lean.parent) + ':/usr/bin:/bin', 'HOME': str(directory), 'TMPDIR': str(directory),
            'LEAN_PATH': os.pathsep.join(map(str, binding.search_paths)),
            'LEAN_SYSROOT': str(binding.lean.parent.parent), 'LEAN_NUM_THREADS': '1'}


@dataclass(frozen=True)
class CompiledChecker:
    executable: Path
    manifest: dict

    def validate(self, binding):
        paths = {str(DRIVER): sha(DRIVER), str(binding.lean): sha(binding.lean),
                 str(binding.lean.with_name('leanc')): sha(binding.lean.with_name('leanc')),
                 str(Path(__file__)): sha(Path(__file__))}
        paths.update({str(binding.lean.parent.parent / 'lib/lean' / name):
                      sha(binding.lean.parent.parent / 'lib/lean' / name) for name in LIBRARIES})
        if (paths != self.manifest['source_sha256'] or binding.pin.to_dict() != self.manifest['pin']
                or sha(self.executable) != self.manifest['executable_sha256']
                or self.executable.stat().st_size > MAX_BYTES
                or self.manifest['policy'] != POLICY):
            raise ValueError('compiled checker source/custody changed')


@contextmanager
def prepare_checkers(bindings):
    """Fresh compilation for this acceptance only; temporary artifacts expire."""
    with tempfile.TemporaryDirectory(prefix='jevops-compiled-checker-') as scratch:
        checkers = {}
        for pin, binding in bindings.items():
            directory = Path(scratch) / uuid.uuid4().hex
            directory.mkdir()
            source, cfile, exe = (directory / n for n in ('ArenaCheck.lean', 'ArenaCheck.c', 'ArenaCheck'))
            source.write_bytes(DRIVER.read_bytes())
            inputs = {str(p): sha(p) for p in (DRIVER, binding.lean, binding.lean.with_name('leanc'), Path(__file__),
                       *(binding.lean.parent.parent / 'lib/lean' / name for name in LIBRARIES))}
            started = time.time()
            env = environment(binding, directory)
            steps = []
            for label, argv in [('compile', [str(binding.lean), '-j1', '-M4096', '-R', str(directory), '-c', str(cfile), str(source)]),
                                ('link', link_command(binding.lean, exe, cfile))]:
                output, errors, code, observation = capture(argv, directory / label, env, {}, 60)
                steps.append({**observation, 'step': label, 'stdout': output.decode(errors='replace'), 'stderr': errors.decode(errors='replace')})
                if code or observation['timed_out']:
                    raise ValueError('fresh compiled checker ' + label + ' failed: ' + json.dumps(steps))
            manifest = {'policy': POLICY, 'build_id': uuid.uuid4().hex, 'pin': pin.to_dict(),
                        'started_at': started, 'finished_at': time.time(), 'source_sha256': inputs,
                        'generated_c_sha256': sha(cfile), 'executable_sha256': sha(exe),
                        'executable_bytes': exe.stat().st_size, 'steps': steps, 'proof_cache': False}
            checker = CompiledChecker(exe, manifest)
            checker.validate(binding)
            checkers[pin] = checker
        yield checkers


def run_compiled(binding, payload, *, timeout, checker):
    if (len(payload.get('prefix', '').encode()) > native.MAX_PREFIX
            or any(len(payload.get(k, '').encode()) > 262144 for k in ('reference', 'candidate'))):
        raise ValueError('native source byte budget')
    checker.validate(binding)
    with tempfile.TemporaryDirectory(prefix='jevops-compiled-run-') as scratch:
        directory = Path(scratch)
        output, errors, code, observation = capture([str(checker.executable)], directory / 'run',
                                                   environment(binding, directory), payload, timeout)
    checker.validate(binding)
    if observation['timed_out']:
        raise TimeoutError('native verifier wall-time budget')
    if code:
        raise ValueError(f'native driver exit {code}: {errors.decode(errors="replace")[:500]} {output.decode(errors="replace")[:500]}')
    rows = [line.removeprefix('JEVOPS_ARENA:') for line in output.decode().splitlines() if line.startswith('JEVOPS_ARENA:')]
    if len(rows) != 1:
        raise ValueError('exactly one bound native report required')
    return json.loads(rows[0]), code, observation


class CompiledNativeLeanVerifier(native.NativeLeanVerifier):
    """Separate verifier identity; the old class and all old contexts are intact."""
    def __init__(self, bindings, *, checkers, **kwargs):
        if kwargs.get('isolation') is not None:
            raise ValueError('compiled backend requires its explicit trusted-local policy')
        if kwargs.get('timeout', 60) > 60:
            raise ValueError('compiled backend preserves the sixty-second execution cap')
        self.checkers = dict(checkers)
        if set(self.checkers) != set(bindings):
            raise ValueError('every exact pin needs a freshly bound compiled checker')
        for pin, checker in self.checkers.items():
            checker.validate(bindings[pin])
        self.backend_identity = content_hash({str(pin): checker.manifest for pin, checker in self.checkers.items()})
        super().__init__(bindings, **kwargs)
        self.version = content_hash({'interpreted_verifier': self.version, 'policy': POLICY,
                                     'compiled_source': sha(Path(__file__)), 'builds': self.backend_identity})

    @property
    def options_json(self):
        return canonical_json({**json.loads(super().options_json), 'compiled_policy': POLICY,
                               'fresh_build_identity': self.backend_identity, 'proof_cache': False})

    def validate_request(self, request):
        super().validate_request(request)
        if self.backend_identity != content_hash({str(pin): checker.manifest for pin, checker in self.checkers.items()}):
            raise ValueError('compiled build identity changed during context')
        self.checkers[request.version].validate(self.bindings[request.version])

    def __call__(self, request: VerificationRequest) -> VersionReceipt:
        empty = VersionReceipt(request.request_id, source_hash(request.source), request.context.problem, Outcome.ERROR)
        try:
            self.validate_request(request)
            error = intake_error(request.source, request.context.statement)
            if error:
                return replace(empty, outcome=Outcome.REJECTED, reason=error)
            if self.processes >= self.max_processes:
                return replace(empty, outcome=Outcome.BUDGET_EXHAUSTED, reason="native_process_budget")
            self.processes += 1
            start = time.monotonic()
            data, code, execution = run_compiled(self.bindings[request.version], {
                "request_id": request.request_id, "target": request.context.problem,
                "prefix": self.bindings[request.version].prefix, "reference": request.context.reference_source,
                "candidate": request.source, "max_heartbeats": self.max_heartbeats,
                "candidate_first": self.branch_order == "candidate-first",
            }, timeout=self.timeout, checker=self.checkers[request.version])
            self.validate_request(request)  # Changes during execution invalidate the observation.
            if (data.get("schema") != "jevops-native-arena/v1" or data.get("request_id") != request.request_id
                    or data.get("target") != request.context.problem or data.get("measurement") != METHOD
                    or data.get("branch_order") != self.branch_order
                    or data.get("lean_version") != request.version.lean_tag.removeprefix("v")
                    or not re.fullmatch(r"[0-9a-f]{40}", data.get("lean_githash", ""))):
                raise ValueError("native report identity mismatch")
            report = data["report"]
            outcome = Outcome(report["outcome"])
            # Resource-limit diagnostics are not semantic counterexamples.
            if outcome == Outcome.REJECTED and any("maximum number of heartbeats" in d.get("message", "")
                                                   for d in report.get("diagnostics", [])):
                outcome = Outcome.TIMEOUT
            observed = {"compiled_backend": self.checkers[request.version].manifest,
                        "compiled_execution": execution, "measurement": METHOD, "lean_version": data["lean_version"],
                        "branch_order": self.branch_order,
                        "lean_githash": data["lean_githash"], "wall_ms": round((time.monotonic() - start) * 1000, 3),
                        "dependency_digest": request.context.dependency_digests[request.context.versions.index(request.version)],
                        "driver_sha256": source_hash(DRIVER.read_text()), "report": report}
            if self.isolation is not None:
                observed["execution_policy"] = self.isolation.policy
                observed["execution_identity"] = self.isolation_identity
            if outcome != Outcome.VERIFIED:
                return replace(empty, outcome=outcome, exit_code=code, reason=report.get("reason", ""),
                               observations_json=canonical_json(observed))
            for key in ("heartbeats", "raw_heartbeats", "reference_heartbeats", "reference_raw_heartbeats"):
                _units(report[key], key)
            if (report.get("type_preserved") is not True or report.get("target_absent_before") is not True
                    or report["heartbeats"] != report["raw_heartbeats"] // 1000
                    or report["reference_heartbeats"] != report["reference_raw_heartbeats"] // 1000):
                raise ValueError("native evidence mismatch")
            for key in ("axioms", "reference_axioms"):
                if not isinstance(report[key], list) or any(not isinstance(x, str) for x in report[key]):
                    raise ValueError("malformed native axiom report")
                if set(report[key]) - set(request.context.allowed_axioms) or "sorryAx" in report[key]:
                    return replace(empty, outcome=Outcome.ERROR if key == "reference_axioms" else Outcome.REJECTED,
                                   exit_code=code, reason=key + "_policy", observations_json=canonical_json(observed))
            if (request.version == request.context.versions[0] and request.context.reference_heartbeats is not None
                    and report["reference_heartbeats"] != request.context.reference_heartbeats):
                return replace(empty, reason="reference_heartbeat_calibration_drift",
                               observations_json=canonical_json(observed))
            axiom_text = f"'{request.context.problem}' depends on axioms: [{', '.join(report['axioms'])}]"
            return replace(empty, outcome=Outcome.VERIFIED, type_preserved=True, exit_code=code,
                           axiom_output=axiom_text, heartbeats=report["heartbeats"],
                           observations_json=canonical_json(observed))
        except (TimeoutError, subprocess.TimeoutExpired):
            return replace(empty, outcome=Outcome.TIMEOUT, reason="native_wall_timeout")
        except IsolationUnavailable as exc:
            return replace(empty, outcome=Outcome.UNAVAILABLE, reason=str(exc)[:500])
        except Exception as exc:
            return replace(empty, reason=f"{type(exc).__name__}: {str(exc)[:500]}")

