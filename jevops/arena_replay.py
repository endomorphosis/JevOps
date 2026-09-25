"""Isolated proof-data export/rechecking, not source or cost admission.

Reuses the native challenge/bindings, structural DAG codec and Docker owner.
Same Lean kernel in a separate process, NOT an independent kernel. No candidate
native artifacts are imported by the checker. Export/source correspondence is
deliberately unestablished; this diagnostic cannot promote or train a proof.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict
import json
import math
from pathlib import Path
import random
import re
import subprocess
import tempfile
import time

from .arena import (TOKENIZER_ID, VerificationRequest, content_hash, intake_error,
                    reference_tokens, source_hash, _units)
from .arena_isolation import DockerIsolation, IsolationUnavailable, capture_process
from .arena_lean import BOUNDARY_FILES, DRIVER, NativeLeanVerifier, ProjectBinding, pinned_lean, MAX_PREFIX
from .arena_pareto import heartbeat_relation
from .arena_source import ExplicitTermPolicy, SourceMismatch, UnsupportedSource, match_export, parse_source
from .expr_dag import CODEC, _name, _unique_pairs, root_summaries, validate_dag
from .lean import VersionPin
from .proof_ca import canonical_json

REPLAY = Path(__file__).with_name("lean") / "ArenaReplay.lean"
SCHEMA = "jevops-arena-term-replay/v1"
STAGE_SCHEMA = "jevops-arena-term-replay-stage/v1"
MARKER = "JEVOPS_ARENA_REPLAY:"
MAX_IO = 16_777_216
COLD_METHOD = "fresh-process-single-command-raw-heartbeats/v1"
COLD_SCHEMA = "jevops-arena-cold-observations/v1"
MAX_COLD_REPORT = 67_108_864
EXPORT_SIZE_POLICY = "nonexpanding-checked-proof-and-type/v1"
SIZE_METRICS = ("unique_expression_nodes", "expanded_expression_nodes", "expression_depth")


def driver_source() -> str:
    """Compose trusted library prefixes, without compiling/mounting .olean files.

    Exact unique namespace delimiters fail closed if either CLI library layout
    changes. These source bytes are included in the immutable replay identity.
    """
    chunks = ["import Lean\n"]
    for path, namespace in ((CODEC, "JevOpsDAG"), (DRIVER, "JevOpsArena")):
        source = path.read_text()
        boundary = "\nend " + namespace + "\n"
        if not source.startswith("import Lean\n") or source.count(boundary) != 1:
            raise ValueError("unsupported trusted library layout")
        chunks.append(source[len("import Lean\n"):].split(boundary)[0] + boundary)
    source = REPLAY.read_text()
    if not source.startswith("import Lean\n"):
        raise ValueError("unsupported trusted replay layout")
    return "\n".join([*chunks, source[len("import Lean\n"):]])


def parse_stage(output: bytes) -> dict:
    if len(output) > MAX_IO:
        raise ValueError("replay output byte budget")
    rows = [s[len(MARKER):] for s in output.decode().splitlines() if s.startswith(MARKER)]
    if len(rows) != 1:
        raise ValueError("exactly one stage envelope required")
    def bad_number(_):
        raise ValueError("non-finite or fractional protocol number")
    data = json.loads(rows[0], object_pairs_hook=_unique_pairs,
                      parse_float=bad_number, parse_constant=bad_number)
    if not isinstance(data, dict):
        raise ValueError("stage object required")
    return data


def validate_export(artifact, *, target, environment, node_budget, toolchain):
    if not isinstance(artifact, dict) or set(artifact) != {"target", "level_parameters", "dag"}:
        raise ValueError("export fields")
    if artifact["target"] != target:
        raise ValueError("export target mismatch")
    params = artifact["level_parameters"]
    if not isinstance(params, list) or len(params) > 256:
        raise ValueError("universe parameter budget")
    for param in params:
        _name(param)
    if len({canonical_json(p) for p in params}) != len(params):
        raise ValueError("duplicate universe parameter")
    stats = validate_dag(artifact["dag"], environment=environment, node_budget=node_budget, toolchain=toolchain)
    if len(artifact["dag"]["roots"]) != 2:
        raise ValueError("proof and type roots required")
    return stats


def _export_size(artifact: dict, *, environment: str, node_budget: int) -> dict:
    """Parent-derived structural costs, not producer-supplied measurement fields.

    Call only after the fresh checker succeeds. Constant bodies and source
    elaboration work are outside this scope; this is not heartbeat attestation.
    Reuse the canonical codec instead of expanding potentially exponential trees.
    """
    roots = root_summaries(artifact["dag"], environment=environment, node_budget=node_budget)
    if len(roots) != 2:
        raise ValueError("proof and type sizes required")
    return {"export_sha256": content_hash(artifact), "proof": roots[0], "type": roots[1],
            "level_nodes": len(artifact["dag"]["levels"]),
            "expression_nodes": len(artifact["dag"]["expressions"]),
            "serialized_export_bytes": len(canonical_json(artifact).encode())}


def _size_comparison(samples: list[dict], orders: dict) -> dict:
    """Every candidate size must fit every control in its process-order stratum.

    This is a private reducer of this invocation's checked observations, NOT an
    API for admitting serialized reports. Preserve all ranges and violations;
    no mean, best repeat, or source-token saving can compensate for term growth.
    """
    by_order, violations = {}, []
    for order in orders:
        rows = {arm: [s["observation"]["checked_export_size"] for s in samples
                      if s["order"] == order and s["arm"] == arm] for arm in ("control", "candidate")}
        if not rows["control"] or len(rows["control"]) != len(rows["candidate"]) or any(
                r is None for values in rows.values() for r in values):
            raise ValueError("complete checked export sizes required")
        ranges = {}
        for root, metric in [(r, m) for r in ("proof", "type") for m in SIZE_METRICS] + [
                (None, m) for m in ("level_nodes", "expression_nodes", "serialized_export_bytes")]:
            key = f"{root}.{metric}" if root else metric
            values = {arm: [(r[root] if root else r)[metric] for r in records] for arm, records in rows.items()}
            if any(type(v) is not int or v < 0 for group in values.values() for v in group):
                raise ValueError("integer export sizes required")
            ranges[key] = {arm: {"min": min(v), "max": max(v)} for arm, v in values.items()}
            if max(values["candidate"]) > min(values["control"]):
                violations.append({"order": order, "metric": key,
                    "control_min": min(values["control"]), "candidate_max": max(values["candidate"])})
        by_order[order] = ranges
    return {"policy": EXPORT_SIZE_POLICY, "scope": "exported-proof-and-type-only",
            "ranges_by_order": by_order, "violations": violations, "nonregressing": not violations,
            "constant_bodies_unfolded": False, "source_or_heartbeat_attestation": False}


class ArenaTermReplay:
    """Single-owner two-stage diagnostic. No cache, proof promotion or model IO.

    Both invocation units are reserved before a producer can run. Reserved but
    unused units are not refunded; attempts count launches/preflight attempts.
    An injected runner is always labeled an offline fixture, never native proof.
    """
    def __init__(self, record, binding: ProjectBinding, *, isolation: DockerIsolation,
                 max_processes: int = 0, timeout: float = 60, node_budget: int = 20_000,
                 max_heartbeats: int = 2_000_000, stage_runner=None, cold_measurement: bool = False,
                 source_policy: ExplicitTermPolicy | None = None, export_size_guard: bool = False):
        if type(isolation) is not DockerIsolation:
            raise ValueError("explicit rootless Docker isolation required; no host fallback")
        if not 0 <= _units(max_processes, "max_processes") <= 256:
            raise ValueError("bounded process budget")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError("finite 0..300 second stage timeout required")
        if not 1 <= _units(node_budget, "node_budget") <= 50_000:
            raise ValueError("node budget")
        if not 1 <= _units(max_heartbeats, "max_heartbeats") <= 10_000_000:
            raise ValueError("heartbeat budget")
        if stage_runner is not None and not callable(stage_runner):
            raise ValueError("trusted fixture runner must be callable")
        if type(cold_measurement) is not bool:
            raise ValueError("cold_measurement must be a boolean")
        if source_policy is not None and type(source_policy) is not ExplicitTermPolicy:
            raise ValueError("explicit typed source policy required")
        if type(export_size_guard) is not bool or export_size_guard and not cold_measurement:
            raise ValueError("export_size_guard requires a boolean and explicit cold measurement")
        self.guard = NativeLeanVerifier({binding.pin: binding}, max_processes=0,
            timeout=timeout, max_heartbeats=max_heartbeats, isolation=isolation)
        self.context = self.guard.context(record)
        if intake_error(self.context.reference_source, self.context.statement):
            raise ValueError("trusted reference violates intake policy")
        if len(binding.prefix.encode()) > MAX_PREFIX:
            raise ValueError("prefix byte budget")
        self.binding, self.isolation = binding, isolation
        self.max_processes, self.timeout = max_processes, timeout
        self.node_budget, self.max_heartbeats = node_budget, max_heartbeats
        self.stage_runner = stage_runner
        self.cold_measurement = cold_measurement
        self.source_policy = source_policy
        self.export_size_guard = self._export_size_guard = export_size_guard
        self._source_policy_record = source_policy.record() if source_policy is not None else None
        self.source = driver_source()
        self.code_identity = self._code_identity()
        self.environment = content_hash({"schema": SCHEMA, "context": asdict(self.context),
            "replay_code": self.code_identity, "node_budget": node_budget,
            "measurement": COLD_METHOD if cold_measurement else None,
            "source_policy": source_policy.record() if source_policy is not None else None,
            "export_size_policy": EXPORT_SIZE_POLICY if export_size_guard else None,
            "source_export_binding": "UNESTABLISHED"})
        self.reserved = self.attempts = 0
        self._tickets: set[int] = set()

    def _code_identity(self):
        return content_hash({"driver": source_hash(driver_source()),
            "adapter": source_hash(Path(__file__).read_text()),
            "native_boundary": {str(p): source_hash(p.read_text()) for p in BOUNDARY_FILES},
            "comparison": source_hash(Path(__file__).with_name("arena_pareto.py").read_text()),
            "source_matcher": source_hash(Path(__file__).with_name("arena_source.py").read_text()),
            "codec_validator": source_hash(CODEC.parent.parent.joinpath("expr_dag.py").read_text())})

    def _validate_context(self, source):
        if type(self.export_size_guard) is not bool or self.export_size_guard != self._export_size_guard:
            raise ValueError("export_size_policy_changed_start_new_context")
        if (self.source_policy.record() if self.source_policy is not None else None) != self._source_policy_record:
            raise ValueError("source_policy_changed_start_new_context")
        self.guard.validate_request(VerificationRequest(self.context, source, self.binding.pin))
        if self._code_identity() != self.code_identity:
            raise ValueError("replay_code_changed_start_new_context")

    def _run_stage(self, payload):
        self.attempts += 1
        if self.stage_runner is not None:
            return self.stage_runner(payload)
        deadline = time.monotonic() + self.timeout
        raw = canonical_json(payload).encode()
        if len(raw) > MAX_IO:
            raise ValueError("stage input byte budget")
        with ExitStack() as stack:
            scratch = stack.enter_context(tempfile.TemporaryDirectory(prefix="jevops-replay-"))
            driver = Path(scratch) / "ArenaReplay.lean"
            driver.write_text(self.source); driver.chmod(0o444)
            stdin = stack.enter_context(tempfile.TemporaryFile())
            stdin.write(raw); stdin.seek(0)
            command, env = stack.enter_context(self.isolation.launch(self.binding.lean,
                self.binding.search_paths, driver, scratch=scratch, deadline=deadline))
            out, err, code = capture_process(command, stdin=stdin, env=env,
                timeout=deadline-time.monotonic(), output_limit=MAX_IO)
            if code:
                raise ValueError(f"replay driver exit {code}: " + (err + out).decode(errors="replace")[:800])
            return parse_stage(out)

    def _check_envelope(self, data, payload):
        if not isinstance(data, dict) or set(data) != {"schema", "mode", "request_id", "environment",
                                                     "target", "lean_version", "lean_githash", "report"}:
            raise ValueError("stage envelope fields")
        if (data["schema"] != STAGE_SCHEMA or any(data[k] != payload[k] for k in
                ("mode", "request_id", "environment", "target"))
                or data["lean_version"] != self.binding.pin.lean_tag.removeprefix("v")
                or not isinstance(data["lean_githash"], str)
                or not re.fullmatch(r"[0-9a-f]{40}", data["lean_githash"])):
            raise ValueError("stage identity mismatch")
        if not isinstance(data["report"], dict):
            raise ValueError("stage report object required")

    def _reserve(self, samples: int) -> tuple[int, ...]:
        """Single-owner atomic batch reservation; no refund or ticket reuse."""
        if not 1 <= _units(samples, "samples") <= 128:
            raise ValueError("bounded nonempty reservation required")
        if self.max_processes - self.reserved < 2 * samples:
            return ()
        tickets = tuple(range(self.reserved + 2, self.reserved + 2 * samples + 1, 2))
        self.reserved += 2 * samples
        self._tickets.update(tickets)
        return tickets

    def evaluate(self, source: str) -> dict:
        return self._evaluate(source)

    def _evaluate(self, source: str, ticket: int | None = None) -> dict:
        result = {"schema": SCHEMA, "status": "ERROR", "reason": "", "environment": self.environment,
            "candidate_sha256": source_hash(source), "candidate_source": source, "target": self.context.problem,
            "challenge": asdict(self.context), "replay_code_identity": self.code_identity,
            "node_budget": self.node_budget, "max_heartbeats": self.max_heartbeats,
            "evidence_mode": "offline_fixture" if self.stage_runner is not None else "local_lean",
            "proof_data_checked": False, "candidate_source_verified": False,
            "source_policy": self.source_policy.record() if self.source_policy is not None else None,
            "source_structure": None, "source_execution_attested": False,
            "source_export_binding": "UNESTABLISHED", "metric_integrity_established": False,
            "export_size_policy": EXPORT_SIZE_POLICY if self._export_size_guard else None,
            "checked_export_size": None,
            "independent_kernel": False, "promoted": False, "training_enabled": False,
            "official_score": None, "execution_policy": self.isolation.policy,
            "separate_proof_data_checker": True,
            "checker_executes_candidate_source": False, "stages": []}
        if self.cold_measurement:
            result.update(measurement=COLD_METHOD, producer_reported_raw_heartbeats=None,
                          measured_branches_per_producer=1, counter_authority="untrusted_producer")
        try:
            if ticket is not None:
                if type(ticket) is not int or ticket not in self._tickets:
                    raise ValueError("invalid_or_consumed_reservation")
                self._tickets.remove(ticket)
            self._validate_context(source)
            error = intake_error(source, self.context.statement)
            if error:
                result.update(status="REJECTED", reason=error)
                return result
            plan = (parse_source(source, self.context.statement, self.source_policy)
                    if self.source_policy is not None else None)
            if ticket is None:
                tickets = self._reserve(1)
                if not tickets:
                    result.update(status="BUDGET_EXHAUSTED", reason="two_stage_reserve_required")
                    return result
                ticket = tickets[0]
                self._tickets.remove(ticket)
            request = content_hash({"environment": self.environment, "source": source_hash(source),
                                    "reservation": ticket})
            base = {"request_id": request, "environment": self.environment, "target": self.context.problem,
                    "prefix": self.binding.prefix, "node_budget": self.node_budget,
                    "max_heartbeats": self.max_heartbeats}
            payload = {**base, "mode": "measure" if self.cold_measurement else "produce", "candidate": source}
            if self.cold_measurement:
                payload["measurement"] = COLD_METHOD
            start = time.monotonic()
            produced = self._run_stage(payload)
            producer_wall_ms = round((time.monotonic() - start) * 1000, 3)
            self._check_envelope(produced, payload)
            self._validate_context(source)
            report = produced["report"]
            result["stages"].append({"mode": payload["mode"], "status": report.get("status"),
                                     "parent_stage_wall_ms": producer_wall_ms,
                                     "envelope_sha256": content_hash(produced)})
            if report.get("status") != "EXPORTED":
                if report.get("status") not in {"REJECTED", "UNAVAILABLE", "UNSUPPORTED", "ERROR"}:
                    raise ValueError("unknown producer outcome")
                result.update(status=report["status"], reason=str(report.get("reason", ""))[:500])
                return result
            fields = {"status", "reason", "export"}
            if self.cold_measurement:
                fields |= {"measurement", "raw_heartbeats"}
            if set(report) != fields or report["reason"] != "":
                raise ValueError("export report fields")
            if self.cold_measurement:
                raw = _units(report["raw_heartbeats"], "raw_heartbeats")
                if report["measurement"] != COLD_METHOD or raw > 2**63 - 1:
                    raise ValueError("cold measurement identity or integer range")
                result["producer_reported_raw_heartbeats"] = raw
            artifact = report["export"]
            stats = validate_export(artifact, target=self.context.problem, environment=self.environment,
                node_budget=self.node_budget, toolchain=(produced["lean_version"], produced["lean_githash"]))
            result.update(export_sha256=content_hash(artifact), export_artifact=artifact, export_stats=stats)
            if plan is not None:
                result["source_structure"] = match_export(plan, artifact["dag"], environment=self.environment,
                    node_budget=self.node_budget, toolchain=(produced["lean_version"], produced["lean_githash"]))
            # Fresh process receives only trusted challenge plus bounded terms.
            # Candidate source, its flags, diagnostics and metrics are omitted.
            payload = {**base, "mode": "check", "export": artifact,
                "reference": self.context.reference_source, "allowed_axioms": list(self.context.allowed_axioms)}
            start = time.monotonic()
            checked = self._run_stage(payload)
            checker_wall_ms = round((time.monotonic() - start) * 1000, 3)
            self._check_envelope(checked, payload)
            self._validate_context(source)
            if content_hash(artifact) != result["export_sha256"]:
                raise ValueError("export_changed_during_checker")
            report = checked["report"]
            status = report.get("status")
            if status not in {"PROOF_DATA_CHECKED", "REJECTED", "UNAVAILABLE", "UNSUPPORTED", "ERROR"}:
                raise ValueError("unknown checker outcome")
            if checked["lean_githash"] != produced["lean_githash"]:
                raise ValueError("producer/checker toolchain mismatch")
            if status == "PROOF_DATA_CHECKED":
                if set(report) != {"status", "reason", "axioms", "reference_axioms"} or report["reason"] != "":
                    raise ValueError("checker success fields")
                for key in ("axioms", "reference_axioms"):
                    if not isinstance(report[key], list) or any(a not in self.context.allowed_axioms for a in report[key]):
                        raise ValueError("checker axiom policy")
                if set(report["axioms"]) - set(report["reference_axioms"]):
                    raise ValueError("checker axiom expansion")
                if self._export_size_guard:
                    result["checked_export_size"] = _export_size(artifact,
                        environment=self.environment, node_budget=self.node_budget)
            result["stages"].append({"mode": "check", "envelope": checked,
                                     "parent_stage_wall_ms": checker_wall_ms})
            result.update(status=("FIXTURE_PROOF_DATA_CHECKED" if self.stage_runner is not None else status)
                          if status == "PROOF_DATA_CHECKED" else status,
                          reason=str(report.get("reason", ""))[:500],
                          proof_data_checked=status == "PROOF_DATA_CHECKED" and self.stage_runner is None)
            if plan is not None and status == "PROOF_DATA_CHECKED":
                result["source_export_binding"] = ("FIXTURE_EXPLICIT_TERM_STRUCTURE_CHECKED"
                    if self.stage_runner is not None else "EXPLICIT_TERM_STRUCTURE_CHECKED")
        except UnsupportedSource as exc:
            result.update(status="UNSUPPORTED", reason=str(exc))
        except SourceMismatch as exc:
            result.update(status="REJECTED", reason="source_export_mismatch:" + str(exc))
        except (TimeoutError, subprocess.TimeoutExpired):
            result.update(status="TIMEOUT", reason="replay_stage_timeout")
        except IsolationUnavailable as exc:
            result.update(status="UNAVAILABLE", reason=str(exc)[:500])
        except Exception as exc:
            result.update(status="ERROR", reason=f"{type(exc).__name__}: {str(exc)[:500]}")
        finally:
            result.update(processes_reserved=self.reserved, process_attempts=self.attempts,
                          receipt_cache_enabled=False)
        return result

    def cold_comparison(self, source: str, *, repetitions: int = 2, seed: int = 17,
                        noise_floor_raw: int = 0) -> dict:
        """Fixed one-pin diagnostic, NEVER a selector/promotion receipt.

        Both execution orders get 2..5 repetitions. Order is between fresh
        processes, not branches. Reserve every producer AND checker up front;
        fail-stop without retries or refund. No cached observations are used.
        """
        if not self.cold_measurement:
            raise ValueError("explicit cold measurement adapter required")
        if not 2 <= _units(repetitions, "repetitions") <= 5:
            raise ValueError("two to five repetitions per order required")
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("uint32 seed required")
        _units(noise_floor_raw, "noise_floor_raw")
        arms = {"control": self.context.reference_source, "candidate": source}
        orders = {"control-first": ("control", "candidate"), "candidate-first": ("candidate", "control")}
        blocks = [(order, rep) for order in orders for rep in range(repetitions)]
        random.Random(seed).shuffle(blocks)
        schedule = [{"arm": arm, "order": order, "repetition": rep}
                    for order, rep in blocks for arm in orders[order]]
        plan = {"schema": COLD_SCHEMA, "environment": self.environment, "measurement": COLD_METHOD,
                "tokenizer_id": TOKENIZER_ID, "arms": arms, "schedule": schedule, "seed": seed,
                "repetitions_per_order": repetitions, "noise_floor_raw": noise_floor_raw,
                "required_process_units": 2 * len(schedule), "retries": 0,
                "report_byte_budget": MAX_COLD_REPORT, "selection": "none"}
        plan["export_size_policy"] = EXPORT_SIZE_POLICY if self._export_size_guard else None
        result = {"schema": COLD_SCHEMA, "status": "ERROR", "reason": "", "plan": plan,
            "plan_id": content_hash(plan), "samples": [], "comparison": None,
            "challenge": asdict(self.context), "replay_code_identity": self.code_identity,
            "evidence_mode": "offline_fixture" if self.stage_runner is not None else "local_lean",
            "metric_integrity_established": False, "candidate_source_verified": False,
            "source_policy": self.source_policy.record() if self.source_policy is not None else None,
            "source_execution_attested": False,
            "source_export_binding": "UNESTABLISHED", "promoted": False, "training_enabled": False,
            "promotion_eligible": False, "official_score": None, "receipt_cache_enabled": False}
        result["export_size_comparison"] = None
        before_reserved, before_attempts = self.reserved, self.attempts
        tickets = ()
        try:
            self._validate_context(source)
            if error := intake_error(source, self.context.statement):
                result.update(status="REJECTED", reason=error)
                return result
            if self.source_policy is not None:
                # Every arm must satisfy the same frozen source policy, before
                # reserving the entire batch. No weaker reference-only bypass.
                for value in arms.values():
                    parse_source(value, self.context.statement, self.source_policy)
            tickets = self._reserve(len(schedule))
            if not tickets:
                result.update(status="BUDGET_EXHAUSTED", reason="full_cold_schedule_reserve_required")
                return result
            # Leave room for delimiters, final counters/comparison and an
            # omitted-sample identity. At most twenty observations are retained.
            retained_bytes = len(canonical_json(result).encode()) + 16_384
            for slot, ticket in zip(schedule, tickets):
                sample = {**slot, "observation": self._evaluate(arms[slot["arm"]], ticket)}
                retained_bytes += len(canonical_json(sample).encode())
                if retained_bytes > MAX_COLD_REPORT:
                    result.update(status="BUDGET_EXHAUSTED", reason="cold_report_byte_budget",
                                  omitted_sample={**slot, "observation_sha256": content_hash(sample),
                                                  "status": sample["observation"]["status"]})
                    return result
                result["samples"].append(sample)
                observation = sample["observation"]
                expected = "FIXTURE_PROOF_DATA_CHECKED" if self.stage_runner is not None else "PROOF_DATA_CHECKED"
                if observation["status"] != expected:
                    result.update(status="INCOMPLETE", reason=observation["status"] + ":" + observation["reason"])
                    return result
            self._validate_context(source)
            rows = {order: {arm: [s["observation"]["producer_reported_raw_heartbeats"] for s in result["samples"]
                                  if s["order"] == order and s["arm"] == arm] for arm in arms} for order in orders}
            relations = {order: heartbeat_relation(row["candidate"], row["control"], noise_floor_raw=noise_floor_raw)
                         for order, row in rows.items()}
            tokens = {arm: reference_tokens(value, self.context.statement) for arm, value in arms.items()}
            result.update(status="FIXTURE_OBSERVED" if self.stage_runner is not None else "OBSERVED",
                comparison={"producer_reported_raw_by_order": rows, "heartbeat_relations": relations,
                            "proof_tokens": tokens, "both_lower_in_observations": tokens["candidate"] < tokens["control"]
                            and all(r == "LOWER" for r in relations.values()), "authoritative": False})
            if self.source_policy is not None:
                result["source_export_binding"] = ("FIXTURE_EXPLICIT_TERM_STRUCTURE_CHECKED"
                    if self.stage_runner is not None else "EXPLICIT_TERM_STRUCTURE_CHECKED")
            if self._export_size_guard:
                result["export_size_comparison"] = _size_comparison(result["samples"], orders)
                if not result["export_size_comparison"]["nonregressing"]:
                    result.update(status="GUARD_REJECTED", reason="checked_export_size_growth")
        except UnsupportedSource as exc:
            result.update(status="UNSUPPORTED", reason=str(exc))
        except (TimeoutError, subprocess.TimeoutExpired):
            result.update(status="TIMEOUT", reason="cold_setup_timeout")
        except IsolationUnavailable as exc:
            result.update(status="UNAVAILABLE", reason=str(exc)[:500])
        except Exception as exc:
            result.update(status="ERROR", reason=f"{type(exc).__name__}: {str(exc)[:500]}")
        finally:
            self._tickets.difference_update(tickets)  # Cancel unused reservations, without refund.
            result.update(processes_reserved=self.reserved - before_reserved,
                          process_attempts=self.attempts - before_attempts,
                          lifetime_processes_reserved=self.reserved, lifetime_process_attempts=self.attempts)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", required=True)
    parser.add_argument("--elan-home", type=Path, required=True)
    parser.add_argument("--tag", default="v4.26.0")
    parser.add_argument("--docker-socket", type=Path, required=True)
    parser.add_argument("--docker-image-id", required=True)
    parser.add_argument("--max-processes", type=int, default=0)
    parser.add_argument("--cold", action="store_true", help="bounded single-branch observation batch; no promotion")
    parser.add_argument("--explicit-source", action="store_true",
                        help="require canonical explicit-term/export structure matching; not execution/cost attestation")
    parser.add_argument("--export-size-guard", action="store_true",
                        help="require nonexpanding checked proof/type exports in --cold comparisons")
    parser.add_argument("--repetitions", type=int, default=2, help="per process order; cold mode only")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--noise-floor-raw", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.export_size_guard and not args.cold:
        parser.error("--export-size-guard requires --cold")
    if args.output and args.output.exists():
        parser.error("output must be a new evidence file")
    pin = VersionPin(args.tag, "local-stdlib-replay-smoke")
    statement = "theorem replay_smoke (h : True) : True"
    record = {"name": "replay_smoke", "statement": statement,
              "src": statement + " := by have redundant := h; exact redundant",
              "version_info": [{pin.lean_tag: pin.git_commit}]}
    policy = ExplicitTermPolicy(("True.intro",)) if args.explicit_source else None
    if args.explicit_source:
        record["src"] = statement + " := by exact @_root_.True.intro"
    binding = ProjectBinding(pin, pinned_lean(args.elan_home, args.tag), Path.cwd(), "", project_backed=False)
    adapter = ArenaTermReplay(record, binding, max_processes=args.max_processes,
                             isolation=DockerIsolation(args.docker_socket, args.docker_image_id),
                             cold_measurement=args.cold, source_policy=policy, export_size_guard=args.export_size_guard)
    candidate = statement + (" := by exact @h" if args.explicit_source else " := by exact h")
    result = (adapter.cold_comparison(candidate, repetitions=args.repetitions, seed=args.seed,
                                     noise_floor_raw=args.noise_floor_raw) if args.cold else adapter.evaluate(candidate))
    result["arena_problem"] = False
    encoded = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        with args.output.open("x") as stream:
            stream.write(encoded + "\n")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
