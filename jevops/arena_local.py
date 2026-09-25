"""Project-bound InfoTree capture/replay using the existing Arena prefix parser.

Single-process ownership, explicit verifier dependency, no ambient model clients,
downloads or builds. Captures and local successes are never whole-proof admission.
Trusted-local execution unless the guard supplies its existing Docker isolation.
"""
from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from . import proof_replay as replay, proof_state as ps
from .arena import VerificationRequest, content_hash, intake_error, reference_tokens, source_hash
from .arena_isolation import capture_process
from .arena_lean import DRIVER, MAX_PREFIX, NativeLeanVerifier
from .arena_providers import strict_json, _fields
from .premise_search import bounded_int, premise_name, subgoal_pool as _subgoal_pool, subgoal_selection

DRIVER_TAIL = Path(__file__).with_name("lean") / "ArenaLocal.lean"
SCHEMA = "jevops-arena-local/v1"
STAGE_SCHEMA = "jevops-arena-local-stage/v1"
PROJECTION = "closing-source-spans/v1"
MARKER = b"JEVOPS_ARENA_LOCAL:"
PROFILE_METHOD = "lean-trace-profiler-raw-heartbeats/v1"


def _profile_summary(report, environment, threshold, node_budget, event_budget):
    """Validate the instrumented interval forest; never turn it into a score.

    Exclusive means excluding recorded tactic children, not all inner Lean
    work. Below-threshold/non-tactic work and instrumentation stay in residuals.
    Hints are display-only, not source offsets or replay anchors.
    """
    _fields(report, "schema environment lean_version lean_githash instrumented measurement projection "
            "threshold_raw command_raw nodes_visited events proof_admitted score_eligible")
    if (report['schema'] != 'jevops-tactic-heartbeat-profile/v1' or report['environment'] != environment
            or report['instrumented'] is not True or report['measurement'] != PROFILE_METHOD
            or report['projection'] != 'builtin-tactic-traces/v1'
            or report['proof_admitted'] is not False or report['score_eligible'] is not False
            or type(report['lean_githash']) is not str or not re.fullmatch('[0-9a-f]{40}', report['lean_githash'])):
        raise ValueError('invalid diagnostic profile identity or authority')
    bounded_int(report['threshold_raw'], threshold, threshold)
    bounded_int(report['command_raw'], 0, 2**53 - 1)
    bounded_int(report['nodes_visited'], 1, node_budget)
    rows = report['events']
    if type(rows) is not list or not 1 <= len(rows) <= min(event_budget, report['nodes_visited']):
        raise ValueError('empty or unbounded tactic profile')
    children, roots, stack = {i: [] for i in range(len(rows))}, [], []
    for i, row in enumerate(rows):
        _fields(row, 'id parent syntax_kind hint hint_truncated start_raw stop_raw inclusive_raw')
        bounded_int(row['id'], i, i)
        for key in ('start_raw', 'stop_raw', 'inclusive_raw'):
            bounded_int(row[key], 0, 2**53 - 1)
        if (row['stop_raw'] < row['start_raw'] or row['inclusive_raw'] != row['stop_raw'] - row['start_raw']
                or row['inclusive_raw'] > report['command_raw']
                or type(row['syntax_kind']) is not str or len(row['syntax_kind']) > 256
                or not row['syntax_kind'].startswith('Lean.Parser.Tactic.')
                or type(row['hint']) is not str or len(row['hint']) > 512
                or type(row['hint_truncated']) is not bool):
            raise ValueError('invalid tactic interval or hint')
        parent = row['parent']
        if parent is None:
            roots.append(i)
            stack = []
        else:
            bounded_int(parent, 0, i - 1)
            if parent not in stack:
                raise ValueError('profile parent outside preorder ancestry')
            stack = stack[:stack.index(parent) + 1]
            p = rows[parent]
            if not p['start_raw'] <= row['start_raw'] <= row['stop_raw'] <= p['stop_raw']:
                raise ValueError('profile child escapes parent')
            children[parent].append(i)
        stack.append(i)
    for siblings in [roots, *children.values()]:
        if any(rows[a]['stop_raw'] > rows[b]['start_raw'] for a, b in zip(siblings, siblings[1:])):
            raise ValueError('overlapping or out-of-order profile siblings')
    covered = sum(rows[i]['inclusive_raw'] for i in roots)
    if covered > report['command_raw']:
        raise ValueError('profile roots exceed instrumented command cost')
    exclusive = [{**row, 'exclusive_recorded_raw': row['inclusive_raw'] - sum(
                    rows[c]['inclusive_raw'] for c in children[row['id']])} for row in rows]
    return {'schema': 'jevops-tactic-profile-summary/v1', 'instrumented': True,
            'score_eligible': False, 'proof_admitted': False, 'events': exclusive,
            'root_ids': roots, 'covered_raw': covered, 'unattributed_raw': report['command_raw'] - covered,
            'exclusive_total_raw': sum(row['exclusive_recorded_raw'] for row in exclusive),
            'interpretation': 'exclusive-of-recorded-tactic-children; hints-not-replay-anchors'}


def _cycle_checks(report, mode, ceiling, steps, depth, key="raw-v1"):
    """Validate bounded native observations, not proofs of goal equivalence.

    Equality is checked structurally inside Lean; the admission boundary still
    independently replays every successful script and extracted term.
    """
    if report["cycle_guard"] != mode:
        raise ValueError("foreign cycle guard")
    assigned = key == "assigned-v1"
    if assigned and report["cycle_key"] != key:
        raise ValueError("foreign cycle key")
    bounded_int(report["max_cycle_checks"], ceiling, ceiling)
    checks = report["cycle_checks"]
    if type(checks) is not list or len(checks) > ceiling:
        raise ValueError("cycle check budget")
    exhausted = report["cycle_checks_exhausted"]
    if type(exhausted) is not bool or (exhausted and len(checks) != ceiling):
        raise ValueError("invalid cycle exhaustion")
    prior = 0
    for number, check in enumerate(checks):
        _fields(check, "id at_step depth kind nodes declarations repeat_of decision" +
                (" expr_nodes level_nodes term_dereferences level_dereferences blocked_in" if assigned else ""))
        bounded_int(check["id"], number, number)
        bounded_int(check["at_step"], prior, steps)
        prior = check["at_step"]
        bounded_int(check["depth"], 0, depth - 1)
        bounded_int(check["nodes"], 0, 2048)
        bounded_int(check["declarations"], 0, 65)
        kind, ancestor = check["kind"], check["repeat_of"]
        kinds = ("eligible", "not_prop", "context_limit", "node_limit", "error") + (
            ("unresolved_term", "unresolved_level", "delayed_assignment", "depth_limit") if assigned else ("metavariables",))
        if kind not in kinds:
            raise ValueError("invalid cycle inspection kind")
        if assigned:
            for field in ("expr_nodes", "level_nodes"):
                bounded_int(check[field], 0, check["nodes"])
            if check["expr_nodes"] + check["level_nodes"] != check["nodes"]:
                raise ValueError("cycle node counter mismatch")
            bounded_int(check["term_dereferences"], 0, check["expr_nodes"])
            bounded_int(check["level_dereferences"], 0, check["level_nodes"])
            location = check["blocked_in"]
            if location not in (None, "goal", "local_type", "local_value", "instance", "prop_check"):
                raise ValueError("invalid cycle inspection location")
            if kind in ("eligible", "not_prop", "context_limit") and location is not None:
                raise ValueError("unexpected blocked key location")
            if kind in ("unresolved_term", "unresolved_level", "delayed_assignment", "node_limit", "depth_limit") and location not in (
                    "goal", "local_type", "local_value", "instance"):
                raise ValueError("missing blocked key location")
            if kind in ("unresolved_term", "delayed_assignment") and check["expr_nodes"] <= check["term_dereferences"]:
                raise ValueError("missing unresolved term visit")
            if kind == "unresolved_level" and check["level_nodes"] <= check["level_dereferences"]:
                raise ValueError("missing unresolved universe visit")
        if kind == "eligible" and (not check["nodes"] or check["declarations"] > 64):
            raise ValueError("incomplete cycle key")
        if kind == "node_limit" and check["nodes"] != 2048:
            raise ValueError("invalid cycle node exhaustion")
        if ancestor is not None:
            bounded_int(ancestor, 0, number - 1)
            old = checks[ancestor]
            if (kind != "eligible" or old["kind"] != "eligible" or old["depth"] >= check["depth"]
                    or old["at_step"] >= check["at_step"]):
                raise ValueError("invalid cycle ancestor")
        expected = "prune" if ancestor is not None and mode == "prune-v1" else "continue"
        if check["decision"] != expected:
            raise ValueError("cycle decision mismatch")
    return checks


def driver_source():
    """Compose reviewed libraries; do not compile/import candidate-owned oleans."""
    chunks = ["import Lean\n"]
    for path, namespace in ((DRIVER, "JevOpsArena"), (ps.EXPORTER, "JevOpsProofState")):
        source = path.read_text()
        boundary = f"\nend {namespace}\n"
        if not source.startswith("import Lean\n") or source.count(boundary) != 1:
            raise ValueError("unsupported project capture library layout")
        chunks.append(source[len("import Lean\n"):].split(boundary)[0] + boundary)
    tail = DRIVER_TAIL.read_text()
    if not tail.startswith("import Lean\n"):
        raise ValueError("unsupported project capture driver")
    return "\n".join([*chunks, tail[len("import Lean\n"):]])


def _identity():
    return content_hash({"driver": source_hash(driver_source()), "adapter": source_hash(Path(__file__).read_text()),
        "contracts": {p.name: source_hash(p.read_text()) for p in
                      (Path(ps.__file__), Path(replay.__file__), Path(__file__).with_name("premise_search.py"))}})


def parse_stage(output):
    if type(output) is not bytes or len(output) > ps.MAX_BYTES:
        raise ValueError("local capture output byte budget")
    rows = [row[len(MARKER):] for row in output.splitlines() if row.startswith(MARKER)]
    if len(rows) != 1:
        raise ValueError("one local capture envelope required")
    return strict_json(rows[0], limit=ps.MAX_BYTES)


class ArenaLocalRuntime:
    """Reserve integer invocations before work; no cache, implicit retry or refund.

    ``runner`` is only an offline fixture adapter, always labelled as such. The
    supplied guard enforces dependencies and execution restrictions before and
    after every operation. Capture/search leave its separate whole-proof process
    budget untouched; the opt-in discover_solver() explicitly consumes it.
    """
    def __init__(self, guard, record, *, max_processes=0, node_budget=4096,
                 event_budget=128, runner=None):
        if type(guard) is not NativeLeanVerifier:
            raise ValueError("explicit native verifier guard required")
        bounded_int(max_processes, 0, 256)
        bounded_int(node_budget, 1, ps.MAX_NODES)
        bounded_int(event_budget, 1, ps.MAX_EVENTS)
        if runner is not None and not callable(runner):
            raise ValueError("explicit fixture runner must be callable")
        if intake_error(record["src"], record["statement"]):
            raise ValueError("invalid frozen reference")
        self.guard, self.record = guard, json.loads(json.dumps(record, allow_nan=False))
        self.context = guard.context(self.record)
        if any(len(guard.bindings[p].prefix.encode()) > MAX_PREFIX for p in self.context.versions):
            raise ValueError("prefix byte budget")
        self.max_processes, self.node_budget, self.event_budget = max_processes, node_budget, event_budget
        self.runner, self.reserved, self.attempts = runner, 0, 0
        self.driver, self.identity = driver_source(), _identity()

    def _origin(self, pin):
        return {"kind": "arena-project/v1", "context_id": self.context.context_id,
            "record_sha256": content_hash(self.record), "target": self.context.problem,
            "pin": pin.to_dict(), "adapter_sha256": self.identity,
            "projection": PROJECTION,
            "evidence_mode": "fixture" if self.runner is not None else "local_lean"}

    def discover_solver(self, pin, *, source=None, mode="frontier-v1", limits=None,
                        draft_policy="shortest-v1"):
        """Full-source solver discovery using the guard's explicit process budget.

        Unlike capture/local search, this consumes guard.processes, not this
        object's separate local-stage allowance. Returns single-pin drafts only.
        """
        from .arena_solver import SolverLimits, discover_solver_frontier
        if self.runner is not None:
            raise ValueError("local-stage fixtures cannot stand in for whole-source solver verification")
        source = self.record["src"] if source is None else source
        self._check(pin, source)
        return discover_solver_frontier(self.context, source, pin, self.guard,
            context_validator=self.guard.validate_request, evidence_mode="local_lean", mode=mode,
            limits=SolverLimits() if limits is None else limits, draft_policy=draft_policy)

    def _check(self, pin, source):
        if pin not in self.context.versions or intake_error(source, self.context.statement):
            raise ValueError("foreign pin or source envelope")
        self.guard.validate_request(VerificationRequest(self.context, source, pin))
        if _identity() != self.identity:
            raise ValueError("local implementation changed; start a new capture epoch")

    def _run(self, binding, payload, deadline):
        self.attempts += 1
        if self.runner is not None:
            return self.runner(binding, payload)
        with ExitStack() as stack:
            scratch = stack.enter_context(tempfile.TemporaryDirectory(prefix="jevops-arena-local-"))
            driver = Path(scratch) / "ArenaLocal.lean"
            driver.write_text(self.driver)
            driver.chmod(0o444)
            stdin = stack.enter_context(tempfile.TemporaryFile())
            stdin.write(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()); stdin.seek(0)
            command = [str(binding.lean), "--run", str(driver)]
            env = {"PATH": f"{binding.lean.parent}:/usr/bin:/bin", "HOME": scratch, "TMPDIR": scratch,
                   "LEAN_PATH": os.pathsep.join(map(str, binding.search_paths)), "LEAN_NUM_THREADS": "1"}
            if self.guard.isolation is not None:
                command, env = stack.enter_context(self.guard.isolation.launch(binding.lean,
                    binding.search_paths, driver, scratch=scratch, deadline=deadline))
            out, err, code = capture_process(command, stdin=stdin, cwd=scratch, env=env,
                timeout=max(0.001, deadline - time.monotonic()), output_limit=ps.MAX_BYTES)
            if code:
                # Driver diagnostics only; no environment dumps or command echo.
                raise ValueError("local driver failed: " + (err + out).decode(errors="replace")[:1200])
            return parse_stage(out)

    def _invoke(self, pin, source, *, mode, environment, **extra):
        self._check(pin, source)
        result = {"schema": SCHEMA, "status": "BUDGET_EXHAUSTED", "mode": mode, "ok": False,
            "evidence_mode": self._origin(pin)["evidence_mode"], "proof_admitted": False,
            "whole_source_checked": False, "os_sandbox": self.guard.isolation is not None,
            "reserved_processes": 0, "attempted_processes": 0}
        if self.reserved >= self.max_processes:
            return result
        self.reserved += 1
        result["reserved_processes"] = 1
        payload = {"mode": mode, "environment": environment, "target": self.context.problem,
            "projection": PROJECTION,
            "prefix": self.guard.bindings[pin].prefix, "source": source,
            "node_budget": self.node_budget, "event_budget": self.event_budget,
            "max_heartbeats": self.guard.max_heartbeats, **extra}
        payload["request_sha256"] = content_hash(payload)
        result["request_sha256"] = payload["request_sha256"]
        deadline = time.monotonic() + self.guard.timeout
        before = self.attempts
        try:
            stage = self._run(self.guard.bindings[pin], payload, deadline)
            self._check(pin, source)
            if time.monotonic() > deadline:
                raise TimeoutError("local operation deadline")
            _fields(stage, "schema request_sha256 target lean_version lean_githash report")
            if (type(stage["report"]) is not dict
                    or stage["schema"] != STAGE_SCHEMA or stage["request_sha256"] != payload["request_sha256"]
                    or stage["target"] != self.context.problem or stage["lean_version"] != pin.lean_tag[1:]
                    or any(stage[k] != stage["report"].get(k) for k in ("lean_version", "lean_githash"))):
                raise ValueError("foreign local stage")
            result.update(ok=True, status="FIXTURE_ONLY" if self.runner is not None else "OBSERVED", stage=stage)
        except (ValueError, TypeError, KeyError, OSError, TimeoutError, subprocess.SubprocessError) as exc:
            result.update(status="ERROR", reason=f"{type(exc).__name__}: {str(exc)[:1400]}")
        result["attempted_processes"] = self.attempts - before
        return result

    def profile(self, pin, *, source=None, threshold_raw=100):
        """Instrument unchanged source, using the existing guard and budget.

        No candidate admission, cached observations, local score or proof-state
        replay follows from this measurement. Prefix work is outside the counter.
        """
        bounded_int(threshold_raw, 0, 1_000_000)
        source = self.context.reference_source if source is None else source
        binding = {'source_sha256': source_hash(source), 'context_id': self.context.context_id,
            'origin': {**self._origin(pin), 'projection': 'builtin-tactic-traces/v1'},
            'threshold_raw': threshold_raw, 'measurement': PROFILE_METHOD,
            'node_budget': self.node_budget, 'event_budget': self.event_budget}
        environment = content_hash(binding)
        result = self._invoke(pin, source, mode='profile', environment=environment, threshold_raw=threshold_raw)
        if result['ok']:
            try:
                summary = _profile_summary(result['stage']['report'], environment, threshold_raw,
                                           self.node_budget, self.event_budget)
                result.update(profile=summary, binding=binding, environment=environment)
            except (ValueError, TypeError, KeyError) as exc:
                result.update(ok=False, status='ERROR', reason=str(exc)[:400])
        return result

    def capture(self, pin, *, source=None):
        source = self.context.reference_source if source is None else source
        origin = self._origin(pin)
        binding = {"source_sha256": source_hash(source), "dependency_environment_sha256": self.context.context_id,
            "exporter_sha256": source_hash(ps.EXPORTER.read_text()), "node_budget": self.node_budget,
            "event_budget": self.event_budget, "origin_sha256": replay.digest(origin)}
        environment = replay.digest(binding)
        result = self._invoke(pin, source, mode="capture", environment=environment)
        if result["ok"]:
            capture = {**binding, "environment": environment, "origin": origin, "ok": True,
                "proof_admitted": False, "kernel_typechecked": False, "replayable": False,
                "dependency_closure_verified": False, "trace": result["stage"]["report"],
                "trace_sha256": replay.digest(result["stage"]["report"])}
            try:
                replay._check_capture(source, capture, self.context.context_id)
                spans = set()
                for event in capture["trace"]["events"]:
                    if event["declaration"] != [["s", p] for p in self.context.problem.split(".")]:
                        raise ValueError("non-target event in capture")
                    span = event["start"], event["end"]
                    if None in span or int(span[0]) >= int(span[1]) or span in spans:
                        raise ValueError("non-distinct closing source span")
                    spans.add(span)
                    if event["status"] == "captured" and (len(event["before"]["goals"]) != 1 or event["after"]["goals"]):
                        raise ValueError("non-closing event in project projection")
                result["capture"] = capture
            except (ValueError, TypeError, KeyError) as exc:
                result.update(ok=False, status="ERROR", reason=str(exc)[:400])
        return result

    def _replay_binding(self, pin, source, capture, event_id, candidate):
        self._check(pin, source)
        replay._check_capture(source, capture, self.context.context_id)
        if capture.get("origin") != self._origin(pin):
            raise ValueError("foreign capture origin")
        if capture["node_budget"] != self.node_budget or capture["event_budget"] != self.event_budget:
            raise ValueError("capture budget changed")
        if type(event_id) is not int or not 0 <= event_id < len(capture["trace"]["events"]):
            raise ValueError("unknown event")
        # Reuse exact span/envelope checks, not arbitrary generated commands.
        replay.replace_event(source, capture["trace"]["events"][event_id], candidate)
        return {"source_sha256": capture["source_sha256"], "trace_sha256": capture["trace_sha256"],
            "dependency_environment_sha256": self.context.context_id, "exporter_sha256": capture["exporter_sha256"],
            "event_id": event_id, "candidate_sha256": source_hash(candidate),
            "node_budget": self.node_budget, "event_budget": self.event_budget}

    def replay(self, pin, source, capture, event_id, candidate):
        binding = self._replay_binding(pin, source, capture, event_id, candidate)
        environment = replay.digest(binding)
        result = self._invoke(pin, source, mode="replay", environment=environment, event_id=event_id, candidate=candidate)
        result.update(binding=binding, environment=environment, closing_reproduced=False,
                      dependency_closure_verified=False)
        if result["ok"]:
            report = result["stage"]["report"]
            try:
                closing = replay.validate_replay(report, capture=capture, event_id=event_id,
                                                 candidate=candidate, environment=environment)
                result.update(native=report, native_sha256=replay.digest(report), closing_reproduced=closing)
            except (ValueError, TypeError, KeyError) as exc:
                result.update(ok=False, status="ERROR", reason=str(exc)[:400])
        return result

    def discover_application(self, pin, source, capture, event_id, premise):
        """Attempt one lemma with native unification and local premise discharge.

        One process reservation includes baseline replay, one guarded application,
        and (on success) independent extracted-term replay. No retries/cache or
        whole-proof admission. A failure is not a disproved proposition.
        """
        premise_name(premise)
        candidate = f"solve | apply _root_.{premise} <;> assumption"
        binding = self._replay_binding(pin, source, capture, event_id, candidate)
        binding.update(operation="application-materialization/v1", premise=premise)
        environment = replay.digest(binding)
        result = self._invoke(pin, source, mode="application", environment=environment,
                              event_id=event_id, candidate=candidate)
        result.update(binding=binding, environment=environment, closing_reproduced=False,
                      extracted_candidate=None, dependency_closure_verified=False,
                      application_attempts=result["attempted_processes"], roundtrip_attempts=0)
        if result["ok"]:
            self._accept_application(result, result["stage"]["report"], source, capture, event_id, candidate)
        return result

    def _accept_application(self, result, report, source, capture, event_id, candidate):
        """Common admission boundary for one-step and multi-step materialization."""
        environment = result["environment"]
        if result["ok"]:
            try:
                _fields(report, "schema lean_version lean_githash search extracted_candidate roundtrip")
                if report["schema"] != "jevops-local-application/v1":
                    raise ValueError("foreign application report")
                search_closed = replay.validate_replay(report["search"], capture=capture,
                    event_id=event_id, candidate=candidate, environment=environment)
                text = report["extracted_candidate"]
                if text is None:
                    if report["roundtrip"] is not None or search_closed:
                        raise ValueError("inconsistent materialization")
                else:
                    if not search_closed or type(text) is not str or not text.startswith("exact "):
                        raise ValueError("unchecked materialized term")
                    target = replay.replace_event(source, capture["trace"]["events"][event_id], text)
                    if intake_error(target, self.context.statement):
                        raise ValueError("unsupported materialized source")
                    result["roundtrip_attempts"] = 1
                    closed = replay.validate_replay(report["roundtrip"], capture=capture,
                        event_id=event_id, candidate=text, environment=environment)
                    if closed:
                        result.update(closing_reproduced=True, extracted_candidate=text)
                result.update(native=report, native_sha256=replay.digest(report))
            except (ValueError, TypeError, KeyError) as exc:
                result.update(ok=False, status="ERROR", reason=str(exc)[:400],
                              closing_reproduced=False, extracted_candidate=None)
        return result

    def discover_search(self, pin, source, capture, event_id, premises, *, max_steps=96, max_depth=4,
                        subgoal_pool=None, max_retrievals=32, retrieval_top_k=4, discharge_window=0,
                        discharge_filter="none", max_discharge_checks=256,
                        cycle_guard="none", max_cycle_checks=256, cycle_key="raw-v1"):
        """Bounded AND/OR backward search, then fresh script and term replay.

        Explicit nominees only; callers of this low-level adapter supply trusted
        scope. The batch API applies inventory/split/dependency exclusions first.
        Process reservations and primitive search units are separate. A timeout
        retains the full reservation and has unknown, not zero, observed steps.
        """
        bounded_int(max_steps, 0, 256)
        bounded_int(max_depth, 0, 8)
        bounded_int(max_retrievals, 0, 256)
        bounded_int(retrieval_top_k, 1, 8)
        bounded_int(discharge_window, 0, 16)
        bounded_int(max_discharge_checks, 0, 256)
        bounded_int(max_cycle_checks, 0, 256)
        if type(cycle_guard) is not str or cycle_guard not in {"none", "observe-v1", "prune-v1"}:
            raise ValueError("unknown cycle guard")
        cycling = cycle_guard != "none"
        if type(cycle_key) is not str or cycle_key not in {"raw-v1", "assigned-v1"}:
            raise ValueError("unknown cycle key")
        assigned = cycle_key == "assigned-v1"
        if assigned and not cycling:
            raise ValueError("assigned cycle key requires a cycle guard")
        if type(discharge_filter) is not str or discharge_filter not in {"none", "observe-all-v1", "propositions-v1"}:
            raise ValueError("unknown discharge filter")
        inspecting = discharge_filter != "none"
        if inspecting and not discharge_window:
            raise ValueError("discharge filter requires a positive window")
        if type(premises) not in (list, tuple) or not 1 <= len(premises) <= 8:
            raise ValueError("one to eight explicit premises required")
        premises = [premise_name(p) for p in premises]
        if len(set(premises)) != len(premises):
            raise ValueError("duplicate premises")
        dynamic = subgoal_pool is not None
        if discharge_window and not dynamic:
            raise ValueError("discharge ordering requires explicit subgoal pool")
        extra = {}
        if dynamic:
            pool = _subgoal_pool(subgoal_pool, premises)
            extra = dict(subgoal_pool=pool, max_retrievals=max_retrievals, retrieval_top_k=retrieval_top_k)
        if discharge_window:
            extra["discharge_window"] = discharge_window
        if inspecting:
            extra.update(discharge_filter=discharge_filter, max_discharge_checks=max_discharge_checks)
        if cycling:
            extra.update(cycle_guard=cycle_guard, max_cycle_checks=max_cycle_checks)
        if assigned:
            extra["cycle_key"] = cycle_key
        # This is an envelope/context check, not the candidate for the search.
        binding = self._replay_binding(pin, source, capture, event_id, "skip")
        binding.pop("candidate_sha256")
        binding.update(operation="bounded-backward-materialization/v1", premises=premises,
                       max_steps=max_steps, max_depth=max_depth)
        if dynamic:
            binding.update(operation="subgoal-backward-materialization/v1", **extra)
        if discharge_window:
            binding["operation"] = "discharge-backward-materialization/v1"
        if inspecting:
            binding["operation"] = "typed-discharge-materialization/v1"
        if cycling:
            binding.update(operation="cycle-guard-materialization/v1", **extra)
        if assigned:
            binding["operation"] = "assigned-cycle-materialization/v1"
        environment = replay.digest(binding)
        common = dict(binding=binding, environment=environment, closing_reproduced=False,
            extracted_candidate=None, dependency_closure_verified=False, application_attempts=0,
            roundtrip_attempts=0, search_steps_reserved=0, search_steps_observed=None)
        if dynamic:
            common.update(retrievals_reserved=0, retrievals_observed=None)
        if inspecting:
            common.update(discharge_checks_reserved=0, discharge_checks_observed=None, discharge_skips=None)
        if cycling:
            common.update(cycle_checks_reserved=0, cycle_checks_observed=None, cycle_prunes=None,
                          cycle_nodes_observed=None)
        if assigned:
            common.update({f"cycle_{f}_observed": None for f in
                ("expr_nodes", "level_nodes", "term_dereferences", "level_dereferences")})
        if (not max_steps or not max_depth or (dynamic and not max_retrievals)
                or (inspecting and not max_discharge_checks) or (cycling and not max_cycle_checks)):
            return dict(common, schema=SCHEMA, status="BUDGET_EXHAUSTED", ok=False, mode="search",
                reserved_processes=0, attempted_processes=0, proof_admitted=False,
                whole_source_checked=False, evidence_mode=self._origin(pin)["evidence_mode"])
        result = self._invoke(pin, source, mode="search", environment=environment, event_id=event_id,
                              premises=premises, max_steps=max_steps, max_depth=max_depth, **extra)
        result.update(common, search_steps_reserved=max_steps * result["reserved_processes"])
        if dynamic:
            result["retrievals_reserved"] = max_retrievals * result["reserved_processes"]
        if inspecting:
            result["discharge_checks_reserved"] = max_discharge_checks * result["reserved_processes"]
        if cycling:
            result["cycle_checks_reserved"] = max_cycle_checks * result["reserved_processes"]
        if not result["ok"]:
            return result
        try:
            report = result["stage"]["report"]
            _fields(report, "schema lean_version lean_githash premises max_steps max_depth attempted_steps "
                            "depth_cutoffs step_exhausted trace path script application" +
                            (" subgoal_pool max_retrievals retrieval_top_k retrievals retrieval_exhausted" if dynamic else "") +
                            (" discharge_window" if discharge_window else "") +
                            (" discharge_filter max_discharge_checks discharge_checks discharge_checks_exhausted" if inspecting else "") +
                            (" cycle_guard max_cycle_checks cycle_checks cycle_checks_exhausted" if cycling else "") +
                            (" cycle_key" if assigned else ""))
            schema = ("jevops-local-search/v6" if assigned else "jevops-local-search/v5" if cycling else "jevops-local-search/v4" if inspecting else "jevops-local-search/v3" if discharge_window
                      else "jevops-local-search/v2" if dynamic else "jevops-local-search/v1")
            if (report["schema"] != schema
                    or report["premises"] != premises
                    or type(report["max_steps"]) is not int or report["max_steps"] != max_steps
                    or type(report["max_depth"]) is not int or report["max_depth"] != max_depth):
                raise ValueError("foreign search report")
            if discharge_window:
                bounded_int(report["discharge_window"], discharge_window, discharge_window)
            bounded_int(report["attempted_steps"], 0, max_steps)
            used = report["attempted_steps"]
            bounded_int(report["depth_cutoffs"], 0, max_steps)
            if type(report["step_exhausted"]) is not bool or (report["step_exhausted"] and used != max_steps):
                raise ValueError("invalid search exhaustion")
            actions = {"assumption", "intro", "constructor", *("apply _root_." + p for p in premises)}
            initial_actions = actions
            if dynamic:
                if (report["subgoal_pool"] != pool or type(report["max_retrievals"]) is not int
                        or report["max_retrievals"] != max_retrievals or type(report["retrieval_top_k"]) is not int
                        or report["retrieval_top_k"] != retrieval_top_k):
                    raise ValueError("foreign retrieval configuration")
                queries = report["retrievals"]
                if type(queries) is not list or len(queries) > max_retrievals:
                    raise ValueError("retrieval query budget")
                if (type(report["retrieval_exhausted"]) is not bool or
                        (report["retrieval_exhausted"] and len(queries) != max_retrievals)):
                    raise ValueError("invalid retrieval exhaustion")
                for number, query in enumerate(queries):
                    _fields(query, "id depth head selected")
                    bounded_int(query["id"], number, number)
                    bounded_int(query["depth"], 1, max_depth - 1)
                    head = query["head"]
                    if head is not None and (type(head) is not str or not 0 < len(head.encode()) <= 1024):
                        raise ValueError("invalid queried head")
                    if query["selected"] != subgoal_selection(pool, premises, head, retrieval_top_k):
                        raise ValueError("retrieval selection mismatch")
                actions = {"assumption", "intro", "constructor", *("apply _root_." + p["name"] for p in pool)}
            trace, path, script = report["trace"], report["path"], report["script"]
            if type(trace) is not list or len(trace) != used:
                raise ValueError("search counter mismatch")
            if cycling:
                cycle_checks = _cycle_checks(report, cycle_guard, max_cycle_checks, used, max_depth, cycle_key)
            if inspecting:
                if report["discharge_filter"] != discharge_filter:
                    raise ValueError("foreign discharge filter")
                bounded_int(report["max_discharge_checks"], max_discharge_checks, max_discharge_checks)
                checks = report["discharge_checks"]
                if type(checks) is not list or len(checks) > max_discharge_checks:
                    raise ValueError("discharge inspection budget")
                if (type(report["discharge_checks_exhausted"]) is not bool or
                        (report["discharge_checks_exhausted"] and len(checks) != max_discharge_checks)):
                    raise ValueError("invalid inspection exhaustion")
                prior_step = 0
                for number, check in enumerate(checks):
                    _fields(check, "id at_step depth goal_index head kind decision")
                    bounded_int(check["id"], number, number)
                    bounded_int(check["at_step"], prior_step, used)
                    prior_step = check["at_step"]
                    bounded_int(check["depth"], 0, max_depth - 1)
                    bounded_int(check["goal_index"], 0, discharge_window - 1)
                    head = check["head"]
                    if head is not None and (type(head) is not str or not 0 < len(head.encode()) <= 1024):
                        raise ValueError("invalid discharge head")
                    if check["kind"] not in ("prop", "data", "unknown", "error"):
                        raise ValueError("invalid discharge kind")
                    decision = "attempt" if discharge_filter == "observe-all-v1" or check["kind"] == "prop" else "skip"
                    if check["decision"] != decision:
                        raise ValueError("discharge decision mismatch")
                linked_checks = set()
            for step_number, row in enumerate(trace):
                _fields(row, "action depth applied" + (" retrieval_id" if dynamic else "") +
                        (" phase goal_index" if discharge_window else "") + (" check_id" if inspecting else ""))
                bounded_int(row["depth"], 0, max_depth - 1)
                allowed = actions
                discharge = False
                if discharge_window:
                    bounded_int(row["goal_index"], 0, discharge_window - 1)
                    discharge = row["phase"] == "discharge"
                    if discharge:
                        if row["action"] != "assumption" or row["retrieval_id"] is not None:
                            raise ValueError("invalid discharge action")
                    elif row["phase"] != "expand" or row["goal_index"] != 0 or row["action"] == "assumption":
                        raise ValueError("invalid expansion action")
                if inspecting:
                    if discharge:
                        check_id = row["check_id"]
                        bounded_int(check_id, 0, len(checks) - 1)
                        check = checks[check_id]
                        if (check_id in linked_checks or check["decision"] != "attempt" or
                                (check["at_step"], check["depth"], check["goal_index"]) !=
                                (step_number, row["depth"], row["goal_index"])):
                            raise ValueError("foreign discharge inspection")
                        linked_checks.add(check_id)
                    elif row["check_id"] is not None:
                        raise ValueError("inspection attached to expansion")
                if dynamic:
                    query_id = row["retrieval_id"]
                    if query_id is None:
                        if row["depth"] != 0 and not discharge:
                            raise ValueError("unrecorded subgoal retrieval")
                        allowed = initial_actions
                    else:
                        bounded_int(query_id, 0, len(queries) - 1)
                        if queries[query_id]["depth"] != row["depth"]:
                            raise ValueError("foreign retrieval depth")
                        allowed = {"assumption", "intro", "constructor",
                                   *("apply _root_." + n for n in queries[query_id]["selected"])}
                if row["action"] not in allowed or type(row["applied"]) is not bool:
                    raise ValueError("unauthorized search action")
            if inspecting and linked_checks != {c["id"] for c in checks if c["decision"] == "attempt"}:
                raise ValueError("uncharged discharge attempt")
            if path is not None and (type(path) is not list or not 1 <= len(path) <= used):
                raise ValueError("invalid search path")
            fragments = []
            cursor = 0
            for step in path or []:
                if discharge_window:
                    _fields(step, "action goal_index")
                    action, index = step["action"], step["goal_index"]
                    bounded_int(index, 0, discharge_window - 1)
                    if index and action != "assumption":
                        raise ValueError("only assumption can discharge a later goal")
                    # A replay path must be a chronological subsequence of
                    # successful, charged operations, not a new tactic proposal.
                    while cursor < len(trace) and not (trace[cursor]["applied"] and
                            trace[cursor]["action"] == action and trace[cursor]["goal_index"] == index):
                        cursor += 1
                    if cursor == len(trace):
                        raise ValueError("uncharged path action")
                    cursor += 1
                else:
                    action, index = step, 0
                if type(action) is not str or action not in actions:
                    raise ValueError("invalid search path action")
                fragments.append((f"(all_goals skip); (rotate_left {index}); " if index else "") + f"(focus ({action}))")
            expected = "solve | " + "; ".join(fragments) if path else None
            if expected is not None and len(expected.encode()) > 4096:
                expected = None
            if script != expected or (script is None and report["application"] is not None):
                raise ValueError("search script mismatch")
            result.update(search_steps_observed=used, search_report=report,
                application_attempts=sum(row["action"].startswith("apply ") for row in trace),
                native_sha256=replay.digest(report))
            if dynamic:
                result["retrievals_observed"] = len(queries)
            if inspecting:
                result.update(discharge_checks_observed=len(checks),
                              discharge_skips=sum(c["decision"] == "skip" for c in checks))
            if cycling:
                result.update(cycle_checks_observed=len(cycle_checks),
                    cycle_prunes=sum(c["decision"] == "prune" for c in cycle_checks),
                    cycle_nodes_observed=sum(c["nodes"] for c in cycle_checks))
            if assigned:
                result.update({f"cycle_{f}_observed": sum(c[f] for c in cycle_checks) for f in
                    ("expr_nodes", "level_nodes", "term_dereferences", "level_dereferences")})
            if script is not None:
                self._replay_binding(pin, source, capture, event_id, script)
                self._accept_application(result, report["application"], source, capture, event_id, script)
                # Bind summary to both search accounting and its replay receipts.
                result["native_sha256"] = replay.digest(report)
        except (ValueError, TypeError, KeyError) as exc:
            result.update(ok=False, status="ERROR", reason=str(exc)[:400],
                          closing_reproduced=False, extracted_candidate=None)
        return result

    def discover_batch(self, pin, capture, index, scope, *, seed=None, **limits):
        """Run an explicitly budgeted discovery plan; emit unadmitted short drafts.

        Receipts are validated before use; the bounded batch trace retains their
        content hashes and outcome summaries, not duplicate full event snapshots.
        Whole-source/all-pin/heartbeat admission remains the caller's next stage.
        """
        from .arena_providers import plan_local_applications

        batch = plan_local_applications(self.record, capture, index, scope, seed=seed, **limits)
        source = seed.source if seed is not None else self.context.reference_source
        self._check(pin, source)
        if capture.get("origin") != self._origin(pin):
            raise ValueError("foreign capture origin")
        batch.update(schema="jevops-local-application-batch/v1", attempts=[],
                     evidence_mode=self._origin(pin)["evidence_mode"], reserved_processes=0,
                     attempted_processes=0, application_attempts=0, roundtrip_attempts=0)
        searching = batch["request"].get("search") in {"backward-v1", "subgoal-v1"}
        dynamic = batch["request"].get("search") == "subgoal-v1"
        inspecting = batch["request"].get("discharge_filter", "none") != "none"
        cycling = batch["request"].get("cycle_guard", "none") != "none"
        assigned = batch["request"].get("cycle_key") == "assigned-v1"
        assigned_counts = tuple(f"cycle_{f}_observed" for f in
            ("expr_nodes", "level_nodes", "term_dereferences", "level_dereferences"))
        if searching:
            batch.update(search_steps_reserved=0, search_steps_observed=0, unknown_search_processes=0)
        if dynamic:
            batch.update(retrievals_reserved=0, retrievals_observed=0)
        if inspecting:
            batch.update(discharge_checks_reserved=0, discharge_checks_observed=0, discharge_skips=0)
        if cycling:
            batch.update(cycle_checks_reserved=0, cycle_checks_observed=0, cycle_prunes=0, cycle_nodes_observed=0)
        if assigned:
            batch.update(dict.fromkeys(assigned_counts, 0))
        if batch["status"] == "BUDGET_EXHAUSTED":
            return batch
        batch["status"] = "ABSTAINED"
        seen = {source_hash(source), source_hash(self.context.reference_source)}
        for application in batch["applications"]:
            if len(batch["drafts"]) == batch["request"]["cap"]:
                batch["truncated"] = True
                break
            result = (self.discover_search if searching else self.discover_application)(
                pin, source, capture, **application)
            for key in ("reserved_processes", "attempted_processes", "application_attempts", "roundtrip_attempts"):
                batch[key] += result[key]
            if searching:
                batch["search_steps_reserved"] += result["search_steps_reserved"]
                batch["search_steps_observed"] += result["search_steps_observed"] or 0
                batch["unknown_search_processes"] += int(result["attempted_processes"] > 0 and
                                                         result["search_steps_observed"] is None)
            if dynamic:
                batch["retrievals_reserved"] += result["retrievals_reserved"]
                batch["retrievals_observed"] += result["retrievals_observed"] or 0
            if inspecting:
                for key in ("discharge_checks_reserved", "discharge_checks_observed", "discharge_skips"):
                    batch[key] += result[key] or 0
            if cycling:
                for key in ("cycle_checks_reserved", "cycle_checks_observed", "cycle_prunes", "cycle_nodes_observed"):
                    batch[key] += result[key] or 0
            if assigned:
                for key in assigned_counts:
                    batch[key] += result[key] or 0
            batch["native_verifier_calls"] += result["attempted_processes"] if self.runner is None else 0
            outcome = {**application, "status": result["status"], "closing_reproduced": result["closing_reproduced"],
                       "receipt_sha256": result.get("native_sha256"), "binding": result["binding"]}
            batch["attempts"].append(outcome)
            if result["status"] in {"ERROR", "BUDGET_EXHAUSTED"}:
                outcome["reason"] = result.get("reason")
                batch.update(status=result["status"], truncated=True)
                break
            if searching:
                outcome["search_accounting"] = {k: v for k, v in result["search_report"].items()
                    if k not in {"application", "lean_githash", "lean_version"}}
                if "native" not in result:
                    outcome["status"] = "NO_CHECKED_CLOSURE"
                    continue
            outcome["baseline_outcome"] = result["native"]["search"]["baseline"]
            outcome["search_outcome"] = result["native"]["search"]["proposed"]
            outcome["roundtrip_outcome"] = (result["native"]["roundtrip"]["proposed"]
                if result["native"]["roundtrip"] is not None else None)
            if not result["closing_reproduced"]:
                outcome["status"] = "NO_CHECKED_CLOSURE"
                continue
            candidate = result["extracted_candidate"]
            target = replay.replace_event(source, capture["trace"]["events"][application["event_id"]], candidate)
            identity, tokens = source_hash(target), reference_tokens(target, self.context.statement)
            outcome.update(candidate=candidate, source_sha256=identity, tokens=tokens)
            if identity in seen:
                outcome["status"] = "DUPLICATE"
            elif tokens >= batch["base_tokens"]:
                outcome["status"] = "NOT_SHORTER"
            else:
                seen.add(identity)
                label = f"local-application-{len(batch['drafts'])}"
                outcome.update(status="DRAFT", label=label)
                batch["proposals"].append({"event_id": application["event_id"], "candidate": candidate})
                batch["drafts"].append({"name": self.record["name"], "label": label, "source": target,
                    "provenance": f"unadmitted {batch['evidence_mode']} extracted application; "
                                  f"request {batch['request']['request_sha256']}; event {application['event_id']}"})
                batch["origins"].append({"label": label, **application, "receipt_sha256": result["native_sha256"]})
        if batch["status"] not in {"ERROR", "BUDGET_EXHAUSTED"} and batch["drafts"]:
            batch["status"] = "FIXTURE_DRAFTS_ONLY" if self.runner is not None else "DRAFTS_ONLY"
        return batch
