"""Proof-data checks are not candidate-source or metric admission."""
from dataclasses import replace
import os
from pathlib import Path
import socket
import tempfile

import pytest

from jevops import arena_replay as replay
from jevops import arena_lean as native
from jevops.arena import content_hash
from jevops.arena_isolation import DockerIsolation, IsolationUnavailable
from jevops.arena_source import ExplicitTermPolicy
from jevops.expr_dag import SCHEMA, METADATA_POLICY
from jevops.lean import VersionPin

PIN = VersionPin("v4.26.0", "fixture")
STATEMENT = "theorem example_replay (h : True) : True"
RECORD = {"name": "example_replay", "statement": STATEMENT,
          "src": STATEMENT + " := by have redundant := h; exact redundant",
          "version_info": [{PIN.lean_tag: PIN.git_commit}]}
CANDIDATE = STATEMENT + " := by exact h"


def artifact(environment, target="example_replay", tag="4.26.0", githash="a" * 40):
    return {"target": target, "level_parameters": [], "dag": {
        "schema": SCHEMA, "metadata_policy": METADATA_POLICY, "environment": environment,
        "lean_version": tag, "lean_githash": githash, "levels": [], "expressions": [
            ["const", [["s", "True"]], []], ["bvar", "0"],
            ["lam", [["s", "h"]], "explicit", "0", "1"],
            ["forall", [["s", "h"]], "explicit", "0", "0"]], "roots": ["2", "3"]}}


def envelope(payload, report):
    return {"schema": replay.STAGE_SCHEMA, **{k:payload[k] for k in
        ("mode", "request_id", "environment", "target")},
        "lean_version": "4.26.0", "lean_githash": "a" * 40, "report": report}


def fixture_stage(payload):
    report = {"status": "EXPORTED", "reason": "", "export": artifact(payload["environment"], payload["target"])}
    if payload["mode"] == "check":
        assert "candidate" not in payload
        report = {"status": "PROOF_DATA_CHECKED", "reason": "", "axioms": [], "reference_axioms": []}
    return envelope(payload, report)


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("fixture dependencies"))
    with tempfile.TemporaryDirectory(prefix="jev-replay-", dir="/tmp") as root:
        with socket.socket(socket.AF_UNIX) as channel:
            endpoint = Path(root) / "docker.sock"; channel.bind(str(endpoint))
            executable = tmp_path / "docker"; executable.write_text("#!/bin/false"); executable.chmod(0o700)
            profile = DockerIsolation(endpoint, "sha256:" + "b" * 64, executable)
            binding = native.ProjectBinding(PIN, tmp_path / "lean", tmp_path, "", project_backed=False)
            def build(**kwargs):
                return replay.ArenaTermReplay(RECORD, binding, isolation=profile,
                    **{"max_processes":2, "stage_runner":fixture_stage, **kwargs})
            yield build


def test_reuses_libraries_without_their_cli_entrypoints():
    source = replay.driver_source()
    assert source.count("import Lean\n") == 1
    assert source.count("unsafe def main") == 1
    assert "def exportTheorem" in source and "unsafe def prefixState" in source
    assert 'JEVOPS_EXPR_DAG:' not in source and 'JEVOPS_ARENA:' not in source


def test_fixture_never_claims_native_proof_source_or_cost_admission(factory):
    result = factory().evaluate(CANDIDATE)
    assert result["status"] == "FIXTURE_PROOF_DATA_CHECKED"
    assert result["processes_reserved"] == result["process_attempts"] == 2
    for key in ("proof_data_checked", "candidate_source_verified", "metric_integrity_established",
                "independent_kernel", "promoted", "training_enabled", "checker_executes_candidate_source"):
        assert result[key] is False
    assert result["source_export_binding"] == "UNESTABLISHED" and result["official_score"] is None


@pytest.mark.parametrize("budget", [0, 1])
def test_reserve_both_stages_before_any_execution(factory, budget):
    adapter = factory(max_processes=budget, stage_runner=lambda *_: pytest.fail("must reserve first"))
    result = adapter.evaluate(CANDIDATE)
    assert result["status"] == "BUDGET_EXHAUSTED"
    assert result["process_attempts"] == result["processes_reserved"] == 0


def test_exact_budget_and_no_observation_reuse(factory):
    adapter = factory()
    assert adapter.evaluate(CANDIDATE)["status"] == "FIXTURE_PROOF_DATA_CHECKED"
    assert adapter.evaluate(CANDIDATE)["status"] == "BUDGET_EXHAUSTED"
    adapter = factory(max_processes=4)
    first, second = adapter.evaluate(CANDIDATE), adapter.evaluate(CANDIDATE)
    assert second["process_attempts"] == second["processes_reserved"] == 4
    assert first["stages"][0]["envelope_sha256"] != second["stages"][0]["envelope_sha256"]


@pytest.mark.parametrize("failure,status", [(IsolationUnavailable("missing"), "UNAVAILABLE"),
                                           (TimeoutError(), "TIMEOUT"), (ValueError("broken"), "ERROR")])
def test_failed_producer_never_falls_back_or_refunds_reservation(factory, failure, status):
    def fail(_): raise failure
    result = factory(stage_runner=fail).evaluate(CANDIDATE)
    assert result["status"] == status and result["processes_reserved"] == 2 and result["process_attempts"] == 1


@pytest.mark.parametrize("damage", ["target", "environment", "cycle", "extra", "universe", "toolchain", "forged_flag"])
def test_malicious_producer_data_rejected_before_checker(factory, damage):
    def run(payload):
        assert payload["mode"] == "produce"
        data = fixture_stage(payload); export = data["report"]["export"]
        if damage == "target": export["target"] = "another"
        elif damage == "environment": export["dag"]["environment"] = "c" * 64
        elif damage == "cycle": export["dag"]["expressions"][2][4] = "2"
        elif damage == "extra": export["declarations"] = ["a new axiom"]
        elif damage == "universe": export["level_parameters"] = [[["s", "u"]], [["s", "u"]]]
        elif damage == "toolchain": export["dag"]["lean_githash"] = "c" * 40
        else: data["report"]["theorem_ok"] = True
        return data
    result = factory(stage_runner=run).evaluate(CANDIDATE)
    assert result["status"] == "ERROR" and result["process_attempts"] == 1


@pytest.mark.parametrize("damage", ["request", "outcome", "axiom", "expanded_axiom", "extra"])
def test_checker_receipts_are_bound_and_bounded(factory, damage):
    def run(payload):
        data = fixture_stage(payload)
        if payload["mode"] == "check":
            if damage == "request": data["request_id"] = "old request"
            elif damage == "outcome": data["report"]["status"] = "VERIFIED"
            elif damage == "axiom": data["report"]["axioms"] = ["sorryAx"]
            elif damage == "expanded_axiom": data["report"]["axioms"] = ["propext"]
            else: data["report"]["source_verified"] = True
        return data
    assert factory(stage_runner=run).evaluate(CANDIDATE)["status"] == "ERROR"


def test_dependency_change_between_stages_does_not_check_or_admit(factory, monkeypatch):
    def run(payload):
        data = fixture_stage(payload)
        monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("changed"))
        return data
    result = factory(stage_runner=run).evaluate(CANDIDATE)
    assert result["status"] == "ERROR" and result["process_attempts"] == 1


@pytest.mark.parametrize("raw", [b'{}', b'JEVOPS_ARENA_REPLAY:{}\nJEVOPS_ARENA_REPLAY:{}',
    b'JEVOPS_ARENA_REPLAY:{"a":1,"a":2}', b'JEVOPS_ARENA_REPLAY:{"a":NaN}',
    b'JEVOPS_ARENA_REPLAY:{"a":1e999}', b'JEVOPS_ARENA_REPLAY:[]'])
def test_strict_stage_json(raw):
    with pytest.raises(ValueError): replay.parse_stage(raw)


def measured_stage(payload):
    data = fixture_stage(payload)
    if payload["mode"] == "measure":
        assert "reference" not in payload
        assert payload["measurement"] == replay.COLD_METHOD
        data["report"].update(measurement=replay.COLD_METHOD,
                              raw_heartbeats=10000 if payload["candidate"] == RECORD["src"] else 5000)
    else:
        assert payload["mode"] == "check"
        assert not {"candidate", "raw_heartbeats", "measurement"} & payload.keys()
    return data


def test_cold_measurement_is_explicit_and_distinct_from_legacy_context(factory):
    ordinary = factory()
    cold = factory(cold_measurement=True, stage_runner=measured_stage)
    assert ordinary.environment != cold.environment
    assert "measurement" not in ordinary.evaluate(CANDIDATE)
    result = cold.evaluate(CANDIDATE)
    assert result["status"] == "FIXTURE_PROOF_DATA_CHECKED"
    assert result["measurement"] == replay.COLD_METHOD != native.METHOD
    assert result["producer_reported_raw_heartbeats"] == 5000
    assert result["counter_authority"] == "untrusted_producer"
    assert [s["mode"] for s in result["stages"]] == ["measure", "check"]
    assert all(s["parent_stage_wall_ms"] >= 0 for s in result["stages"])
    assert not result["metric_integrity_established"] and not result["candidate_source_verified"]


@pytest.mark.parametrize("raw", [True, -1, 1.5, "10", None, float("nan"), float("inf"), 2**63])
def test_cold_invalid_counters_never_reach_checker(factory, raw):
    def damaged(payload):
        assert payload["mode"] == "measure"
        data = measured_stage(payload)
        data["report"]["raw_heartbeats"] = raw
        return data
    result = factory(cold_measurement=True, stage_runner=damaged).evaluate(CANDIDATE)
    assert result["status"] == "ERROR" and result["process_attempts"] == 1


@pytest.mark.parametrize("damage", ["method", "missing", "extra", "mode"])
def test_cold_measurement_envelope_cannot_masquerade_as_another_method(factory, damage):
    def damaged(payload):
        assert payload["mode"] == "measure"
        data = measured_stage(payload)
        if damage == "method": data["report"]["measurement"] = native.METHOD
        elif damage == "missing": data["report"].pop("raw_heartbeats")
        elif damage == "extra": data["report"]["metric_integrity_established"] = True
        else: data["mode"] = "produce"
        return data
    result = factory(cold_measurement=True, stage_runner=damaged).evaluate(CANDIDATE)
    assert result["status"] == "ERROR" and result["process_attempts"] == 1


@pytest.mark.parametrize("budget", [0, 1, 15])
@pytest.mark.parametrize("guard", [False, True])
def test_cold_batch_reserves_entire_protocol_before_launch(factory, budget, guard):
    adapter = factory(cold_measurement=True, max_processes=budget,
                      export_size_guard=guard,
                      stage_runner=lambda _: pytest.fail("no partial protocol"))
    result = adapter.cold_comparison(CANDIDATE)
    assert result["status"] == "BUDGET_EXHAUSTED"
    assert result["process_attempts"] == result["processes_reserved"] == 0
    assert result["samples"] == [] and result["plan"]["required_process_units"] == 16


def test_cold_exact_budget_unique_requests_balanced_repeats_and_no_promotion(factory):
    requests = []
    adapter = None
    def run(payload):
        assert adapter.reserved == 16  # Every sample, not just this pair, prepaid.
        if payload["mode"] == "measure": requests.append(payload["request_id"])
        return measured_stage(payload)
    adapter = factory(cold_measurement=True, max_processes=16, stage_runner=run)
    result = adapter.cold_comparison(CANDIDATE, seed=32, noise_floor_raw=10)
    assert result["status"] == "FIXTURE_OBSERVED"
    assert result["processes_reserved"] == result["process_attempts"] == 16
    assert len(requests) == len(set(requests)) == len(result["samples"]) == 8
    assert result["comparison"]["both_lower_in_observations"] is True
    assert result["comparison"]["authoritative"] is False
    for row in result["comparison"]["producer_reported_raw_by_order"].values():
        assert row == {"control": [10000, 10000], "candidate": [5000, 5000]}
    for key in ("promoted", "training_enabled", "promotion_eligible", "candidate_source_verified",
                "metric_integrity_established", "receipt_cache_enabled"):
        assert result[key] is False
    assert not adapter._tickets and result["official_score"] is None
    assert adapter.cold_comparison(CANDIDATE)["status"] == "BUDGET_EXHAUSTED"


def test_cold_seed_floor_and_method_are_frozen_and_deterministic(factory):
    def observe(**kwargs):
        return factory(cold_measurement=True, max_processes=16, stage_runner=measured_stage).cold_comparison(CANDIDATE, **kwargs)
    first, same, changed, floor = observe(), observe(), observe(seed=18), observe(noise_floor_raw=5000)
    assert first["plan"] == same["plan"]
    assert len({r["plan_id"] for r in (first, changed, floor)}) == 3
    assert floor["comparison"]["both_lower_in_observations"] is False
    assert set(floor["comparison"]["heartbeat_relations"].values()) == {"UNKNOWN"}


@pytest.mark.parametrize("count,expected", [(0, "EQUAL"), (10000, "EQUAL"), (15000, "HIGHER")])
def test_cold_zero_exact_identity_and_regressions_are_not_wins(factory, count, expected):
    def run(payload):
        data = measured_stage(payload)
        if payload["mode"] == "measure":
            data["report"]["raw_heartbeats"] = count if count == 0 or payload["candidate"] == CANDIDATE else 10000
        return data
    result = factory(cold_measurement=True, max_processes=16, stage_runner=run).cold_comparison(CANDIDATE)
    assert result["status"] == "FIXTURE_OBSERVED"
    assert not result["comparison"]["both_lower_in_observations"]
    assert set(result["comparison"]["heartbeat_relations"].values()) == {expected}


@pytest.mark.parametrize("status", ["REJECTED", "UNAVAILABLE", "ERROR"])
def test_cold_failed_control_stops_without_retry_refund_or_comparison(factory, status):
    def fail(payload): return envelope(payload, {"status": status, "reason": "fixture failure"})
    # Choose the control-first block first, regardless of shuffle implementation.
    seed = next(i for i in range(100) if factory(cold_measurement=True, max_processes=0)
                .cold_comparison(CANDIDATE, seed=i)["plan"]["schedule"][0]["arm"] == "control")
    adapter = factory(cold_measurement=True, max_processes=16, stage_runner=fail)
    result = adapter.cold_comparison(CANDIDATE, seed=seed)
    assert result["status"] == "INCOMPLETE" and result["reason"].startswith(status)
    assert result["processes_reserved"] == 16 and result["process_attempts"] == 1
    assert len(result["samples"]) == 1 and result["comparison"] is None and not adapter._tickets


def test_cold_checker_failure_does_not_turn_a_low_counter_into_a_win(factory):
    def fail(payload):
        if payload["mode"] == "check": return envelope(payload, {"status": "REJECTED", "reason": "kernel_rejected"})
        return measured_stage(payload)
    result = factory(cold_measurement=True, max_processes=16, stage_runner=fail).cold_comparison(CANDIDATE)
    assert result["status"] == "INCOMPLETE" and result["process_attempts"] == 2
    assert result["comparison"] is None


def test_cold_duplicate_reservation_cannot_double_charge_or_reexecute(factory):
    adapter = factory(cold_measurement=True, max_processes=4, stage_runner=measured_stage)
    ticket, = adapter._reserve(1)
    assert adapter._evaluate(CANDIDATE, ticket)["status"] == "FIXTURE_PROOF_DATA_CHECKED"
    again = adapter._evaluate(CANDIDATE, ticket)
    assert again["status"] == "ERROR" and "consumed_reservation" in again["reason"]
    assert again["processes_reserved"] == again["process_attempts"] == 2


def test_cold_report_budget_stops_and_accounts_for_omitted_sample(factory, monkeypatch):
    monkeypatch.setattr(replay, "MAX_COLD_REPORT", 1)
    result = factory(cold_measurement=True, max_processes=16, stage_runner=measured_stage).cold_comparison(CANDIDATE)
    assert result["status"] == "BUDGET_EXHAUSTED" and result["reason"] == "cold_report_byte_budget"
    assert result["process_attempts"] == 2 and result["processes_reserved"] == 16
    assert result["omitted_sample"]["status"] == "FIXTURE_PROOF_DATA_CHECKED"
    assert result["comparison"] is None


@pytest.mark.parametrize("kwargs", [{"repetitions": 0}, {"repetitions": True}, {"repetitions": 6},
    {"seed": -1}, {"seed": 2**32}, {"seed": True}, {"noise_floor_raw": -1}, {"noise_floor_raw": 0.1}])
def test_cold_invalid_protocol_never_reserves_or_calls(factory, kwargs):
    adapter = factory(cold_measurement=True, max_processes=16, stage_runner=lambda _: pytest.fail("invalid"))
    with pytest.raises(ValueError): adapter.cold_comparison(CANDIDATE, **kwargs)
    assert adapter.reserved == adapter.attempts == 0


def test_cold_requires_explicit_mode_and_invalid_source_is_free(factory):
    with pytest.raises(ValueError, match="explicit cold"):
        factory().cold_comparison(CANDIDATE)
    with pytest.raises(ValueError, match="boolean"):
        factory(cold_measurement=1)
    result = factory(cold_measurement=True, max_processes=16).cold_comparison("theorem wrong : True := by trivial")
    assert result["status"] == "REJECTED" and result["processes_reserved"] == 0


def test_falsy_injected_runner_is_still_a_fixture_not_native_evidence(factory):
    class Runner:
        def __bool__(self): return False
        def __call__(self, payload): return measured_stage(payload)
    result = factory(cold_measurement=True, max_processes=16, stage_runner=Runner()).cold_comparison(CANDIDATE)
    assert result["status"] == "FIXTURE_OBSERVED" and result["evidence_mode"] == "offline_fixture"
    assert all(s["observation"]["status"] == "FIXTURE_PROOF_DATA_CHECKED" and
               s["observation"]["proof_data_checked"] is False for s in result["samples"])


@pytest.mark.parametrize("failure,status", [(IsolationUnavailable("gone"), "UNAVAILABLE"),
                                           (TimeoutError(), "TIMEOUT"), (ValueError("stale"), "ERROR")])
def test_cold_setup_failures_do_not_reserve_or_masquerade_as_rejections(factory, monkeypatch, failure, status):
    adapter = factory(cold_measurement=True, max_processes=16, stage_runner=measured_stage)
    def fail(_): raise failure
    monkeypatch.setattr(adapter, "_validate_context", fail)
    result = adapter.cold_comparison(CANDIDATE)
    assert result["status"] == status and result["comparison"] is None
    assert result["process_attempts"] == result["processes_reserved"] == 0


def test_cold_context_mutation_between_samples_preserves_history_without_comparison(factory, monkeypatch):
    measured = 0
    def run(payload):
        nonlocal measured
        if payload["mode"] == "measure":
            measured += 1
            if measured == 2:
                monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: "changed dependency")
        return measured_stage(payload)
    result = factory(cold_measurement=True, max_processes=16, stage_runner=run).cold_comparison(CANDIDATE)
    assert result["status"] == "INCOMPLETE" and result["comparison"] is None
    assert result["process_attempts"] == 3 and result["processes_reserved"] == 16
    assert [s["observation"]["status"] for s in result["samples"]] == ["FIXTURE_PROOF_DATA_CHECKED", "ERROR"]


def sized_artifact(environment, *, duplicate=False):
    # Sharing an inner let in the outer value grows the expanded tree, not the
    # unique DAG. These are codec fixtures, not native kernel-check evidence.
    value = artifact(environment)
    value["dag"]["expressions"] = [
        ["const", [["s", "True"]], []], ["bvar", "0"],
        ["let", [["s", "y"]], False, "0", "1", "1"],
        ["let", [["s", "x"]], False, "0", "2" if duplicate else "1", "2"],
        ["lam", [["s", "h"]], "explicit", "0", "3"],
        ["forall", [["s", "h"]], "explicit", "0", "0"]]
    value["dag"]["roots"] = ["4", "5"]
    return value


def test_export_size_policy_is_opt_in_context_bound_and_parent_derived(factory):
    plain = factory(cold_measurement=True, stage_runner=measured_stage)
    guarded = factory(cold_measurement=True, stage_runner=measured_stage, export_size_guard=True)
    assert plain.environment != guarded.environment
    assert plain.evaluate(CANDIDATE)["checked_export_size"] is None
    result = guarded.evaluate(CANDIDATE)
    size = result["checked_export_size"]
    assert result["status"] == "FIXTURE_PROOF_DATA_CHECKED"
    assert result["export_size_policy"] == replay.EXPORT_SIZE_POLICY
    assert size["export_sha256"] == result["export_sha256"]
    assert size["proof"]["unique_expression_nodes"] == 3
    assert size["proof"]["expanded_expression_nodes"] == 3
    assert size["type"]["unique_expression_nodes"] == 2
    assert size["type"]["expanded_expression_nodes"] == 3
    assert size["expression_nodes"] == 4 and size["level_nodes"] == 0
    assert not result["proof_data_checked"] and not result["metric_integrity_established"]


@pytest.mark.parametrize("growth", ["proof", "type", "expanded_only", "payload", "late_repeat"])
def test_size_growth_cannot_be_compensated_by_fewer_source_tokens_or_heartbeats(factory, growth):
    candidates = 0
    def run(payload):
        nonlocal candidates
        data = measured_stage(payload)
        if payload["mode"] == "measure":
            is_candidate = payload["candidate"] == CANDIDATE
            candidates += int(is_candidate)
            if growth == "expanded_only":
                data["report"]["export"] = sized_artifact(payload["environment"], duplicate=is_candidate)
            elif growth == "payload":
                wire = data["report"]["export"]["dag"]
                metadata = [[[["s", "debug"]], ["string", "x" * (4096 if is_candidate else 1)]]]
                wire["expressions"].insert(2, ["mdata", metadata, "1"])
                wire["expressions"][3][4] = "2"
                wire["roots"] = ["3", "4"]
            elif is_candidate and (growth != "late_repeat" or candidates == 4):
                if growth == "type":
                    wire = data["report"]["export"]["dag"]
                    wire["expressions"].append(["mdata", [], "3"])
                    wire["roots"][1] = "4"
                else:
                    data["report"]["export"] = sized_artifact(payload["environment"])
        return data
    adapter = factory(cold_measurement=True, max_processes=16, stage_runner=run, export_size_guard=True)
    result = adapter.cold_comparison(CANDIDATE)
    assert result["status"] == "GUARD_REJECTED" and result["reason"] == "checked_export_size_growth"
    assert result["comparison"]["both_lower_in_observations"]  # Costs alone would look better.
    sizes = result["export_size_comparison"]
    assert sizes["nonregressing"] is False and sizes["source_or_heartbeat_attestation"] is False
    assert sizes["violations"] and not sizes["constant_bodies_unfolded"]
    metrics = {v["metric"] for v in sizes["violations"]}
    if growth == "expanded_only": assert metrics == {"proof.expanded_expression_nodes"}
    if growth == "payload": assert metrics == {"serialized_export_bytes"}
    if growth == "type": assert "type.unique_expression_nodes" in metrics
    assert result["processes_reserved"] == result["process_attempts"] == 16
    assert not adapter._tickets and len(result["samples"]) == 8
    assert not any(result[k] for k in ("promotion_eligible", "metric_integrity_established",
                                      "candidate_source_verified", "training_enabled"))


@pytest.mark.parametrize("smaller", [False, True])
def test_equal_or_smaller_checked_exports_pass_only_the_structural_guard(factory, smaller):
    def run(payload):
        data = measured_stage(payload)
        if payload["mode"] == "measure" and smaller and payload["candidate"] == RECORD["src"]:
            data["report"]["export"] = sized_artifact(payload["environment"])
        return data
    result = factory(cold_measurement=True, max_processes=16, stage_runner=run,
                     export_size_guard=True).cold_comparison(CANDIDATE)
    assert result["status"] == "FIXTURE_OBSERVED"
    assert result["export_size_comparison"]["nonregressing"]
    assert result["plan"]["export_size_policy"] == replay.EXPORT_SIZE_POLICY
    assert not result["promotion_eligible"] and not result["metric_integrity_established"]


def test_guarded_checker_failure_produces_no_checked_size_or_comparison(factory):
    def run(payload):
        if payload["mode"] == "check":
            return envelope(payload, {"status": "REJECTED", "reason": "kernel_rejected"})
        return measured_stage(payload)
    result = factory(cold_measurement=True, max_processes=16, stage_runner=run,
                     export_size_guard=True).cold_comparison(CANDIDATE)
    assert result["status"] == "INCOMPLETE" and result["export_size_comparison"] is None
    assert result["comparison"] is None
    assert result["samples"][0]["observation"]["checked_export_size"] is None


@pytest.mark.parametrize("mode", ["measure", "check"])
def test_producer_or_checker_cannot_supply_its_own_size_summary(factory, mode):
    def run(payload):
        data = measured_stage(payload)
        if payload["mode"] == mode:
            data["report"]["checked_export_size"] = {"proof": {"expanded_expression_nodes": 0}}
        return data
    result = factory(cold_measurement=True, stage_runner=run, export_size_guard=True).evaluate(CANDIDATE)
    assert result["status"] == "ERROR" and result["checked_export_size"] is None


def test_export_mutation_after_check_cannot_change_which_term_was_measured(factory):
    def run(payload):
        data = measured_stage(payload)
        if payload["mode"] == "check":
            payload["export"].update(sized_artifact(payload["environment"]))
        return data
    result = factory(cold_measurement=True, stage_runner=run, export_size_guard=True).evaluate(CANDIDATE)
    assert result["status"] == "ERROR" and "export_changed_during_checker" in result["reason"]
    assert result["checked_export_size"] is None and not result["proof_data_checked"]


@pytest.mark.parametrize("during", [False, True])
def test_size_policy_cannot_be_removed_during_an_epoch(factory, during):
    adapter = None
    def run(payload):
        adapter.export_size_guard = False
        return measured_stage(payload)
    adapter = factory(cold_measurement=True, stage_runner=run, export_size_guard=True)
    if not during: adapter.export_size_guard = False
    result = adapter.evaluate(CANDIDATE)
    assert result["status"] == "ERROR" and "export_size_policy_changed" in result["reason"]
    assert result["process_attempts"] == int(during) and result["checked_export_size"] is None


@pytest.mark.parametrize("kwargs", [{"export_size_guard": True},
    *({"cold_measurement": True, "export_size_guard": value} for value in (None, 1, {}, "on"))])
def test_size_policy_requires_explicit_cold_mode_and_boolean(factory, kwargs):
    with pytest.raises(ValueError, match="export_size_guard"):
        factory(**kwargs)


def test_size_guard_cli_requires_cold_before_toolchain_or_docker_access(monkeypatch, capsys):
    import sys
    monkeypatch.setattr(sys, "argv", ["arena_replay", "--smoke", "--export-size-guard",
        "--elan-home", "/missing", "--docker-socket", "/missing.sock", "--docker-image-id", "missing"])
    monkeypatch.setattr(replay, "pinned_lean", lambda *_: pytest.fail("invalid CLI must not probe Lean"))
    with pytest.raises(SystemExit) as caught:
        replay.main()
    assert caught.value.code == 2 and "requires --cold" in capsys.readouterr().err


def test_explicit_source_policy_is_opt_in_bound_and_not_native_admission(factory):
    ordinary = factory()
    adapter = factory(source_policy=ExplicitTermPolicy())
    assert ordinary.environment != adapter.environment
    result = adapter.evaluate(STATEMENT + " := by exact @h")
    assert result["status"] == "FIXTURE_PROOF_DATA_CHECKED", result
    assert result["source_export_binding"] == "FIXTURE_EXPLICIT_TERM_STRUCTURE_CHECKED"
    assert result["source_structure"]["structure_matches"]
    for key in ("proof_data_checked", "candidate_source_verified", "source_execution_attested",
                "metric_integrity_established", "promoted", "training_enabled"):
        assert result[key] is False
    # It never silently upgrades or restricts legacy behavior.
    assert ordinary.evaluate(CANDIDATE)["source_export_binding"] == "UNESTABLISHED"


@pytest.mark.parametrize("body", ["by skip", "by exact h", "by exact @h --more", "by exact @missing"])
def test_explicit_unsupported_source_never_starts_producer(factory, body):
    result = factory(source_policy=ExplicitTermPolicy(),
        stage_runner=lambda _: pytest.fail("no unsupported syntax fallback")).evaluate(STATEMENT + " := " + body)
    assert result["status"] == "UNSUPPORTED", result
    assert result["process_attempts"] == result["processes_reserved"] == 0


def test_explicit_export_substitution_rejected_without_checker_or_refund(factory):
    # Fixture export uses h, but the claim explicitly asks for True.intro.
    result = factory(source_policy=ExplicitTermPolicy(("True.intro",))).evaluate(
        STATEMENT + " := by exact @_root_.True.intro")
    assert result["status"] == "REJECTED" and result["reason"].startswith("source_export_mismatch:")
    assert result["process_attempts"] == 1 and result["processes_reserved"] == 2
    assert result["source_export_binding"] == "UNESTABLISHED"


def test_explicit_shape_match_does_not_bypass_kernel_failure(factory):
    def run(payload):
        data = fixture_stage(payload)
        if payload["mode"] == "check":
            data["report"] = {"status": "REJECTED", "reason": "kernel_rejected"}
        return data
    result = factory(source_policy=ExplicitTermPolicy(), stage_runner=run).evaluate(STATEMENT + " := by exact @h")
    assert result["source_structure"]["structure_matches"] and result["status"] == "REJECTED"
    assert result["source_export_binding"] == "UNESTABLISHED"
    assert not result["proof_data_checked"] and not result["candidate_source_verified"]


def test_explicit_checker_never_receives_source_or_source_authority_flags(factory):
    def run(payload):
        if payload["mode"] == "check":
            assert not {"candidate", "source_policy", "source_structure", "theorem_ok"} & payload.keys()
        return fixture_stage(payload)
    result = factory(source_policy=ExplicitTermPolicy(), stage_runner=run).evaluate(STATEMENT + " := by exact @h")
    assert result["status"] == "FIXTURE_PROOF_DATA_CHECKED"


def test_explicit_policy_cannot_change_inside_an_epoch(factory):
    adapter = factory(source_policy=ExplicitTermPolicy())
    adapter.source_policy = None
    result = adapter.evaluate(CANDIDATE)
    assert result["status"] == "ERROR" and "source_policy_changed" in result["reason"]
    assert result["process_attempts"] == result["processes_reserved"] == 0


def test_explicit_policy_mutation_during_production_stops_before_checker(factory):
    adapter = None
    def run(payload):
        adapter.source_policy = ExplicitTermPolicy(("True.intro",))
        return fixture_stage(payload)
    adapter = factory(source_policy=ExplicitTermPolicy(), stage_runner=run)
    result = adapter.evaluate(STATEMENT + " := by exact @h")
    assert result["status"] == "ERROR" and "source_policy_changed" in result["reason"]
    assert result["process_attempts"] == 1 and result["processes_reserved"] == 2


def test_explicit_cold_protocol_requires_same_policy_on_reference_before_reserving(factory):
    adapter = factory(source_policy=ExplicitTermPolicy(), cold_measurement=True, max_processes=16,
                      stage_runner=lambda _: pytest.fail("unsupported reference must not run"))
    result = adapter.cold_comparison(STATEMENT + " := by exact @h")
    assert result["status"] == "UNSUPPORTED" and result["comparison"] is None
    assert result["process_attempts"] == result["processes_reserved"] == 0


def test_explicit_cold_fixture_checks_every_sample_without_cost_authority(factory):
    setup = factory()
    record = {**RECORD, "src": STATEMENT + " := by exact @h"}
    adapter = replay.ArenaTermReplay(record, setup.binding, isolation=setup.isolation,
        source_policy=ExplicitTermPolicy(), cold_measurement=True, max_processes=16, stage_runner=measured_stage)
    result = adapter.cold_comparison(record["src"])
    assert result["status"] == "FIXTURE_OBSERVED", result
    assert result["source_export_binding"] == "FIXTURE_EXPLICIT_TERM_STRUCTURE_CHECKED"
    assert all(s["observation"]["source_structure"]["structure_matches"] for s in result["samples"])
    assert result["process_attempts"] == result["processes_reserved"] == 16
    assert not result["comparison"]["authoritative"] and not result["candidate_source_verified"]
    assert not result["promotion_eligible"] and not result["metric_integrity_established"]


@pytest.mark.parametrize("policy", [True, {}, "explicit-term", ()])
def test_explicit_source_policy_requires_typed_caller_dependency(factory, policy):
    with pytest.raises(ValueError, match="typed source policy"):
        factory(source_policy=policy)


@pytest.fixture
def live_profile():
    if os.environ.get("JEVOPS_ARENA_DOCKER_TESTS") != "1":
        pytest.skip("explicit Docker/Lean opt-in required")
    return DockerIsolation(Path(os.environ["JEVOPS_ARENA_DOCKER_SOCKET"]), os.environ["JEVOPS_ARENA_DOCKER_IMAGE"])


@pytest.fixture
def live_adapter(live_profile, tmp_path):
    binding = native.ProjectBinding(PIN, native.pinned_lean(Path(os.environ["ELAN_HOME"]), PIN.lean_tag),
                                    tmp_path, "", project_backed=False)
    return replay.ArenaTermReplay(RECORD, binding, isolation=live_profile, max_processes=2)


def test_live_fresh_process_checks_exported_term(live_adapter):
    result = live_adapter.evaluate(CANDIDATE)
    assert result["status"] == "PROOF_DATA_CHECKED", result
    assert result["proof_data_checked"] and not result["candidate_source_verified"]
    assert result["process_attempts"] == 2 and not result["promoted"]


@pytest.mark.parametrize("kind", ["wrong_type", "bad_proof", "missing_constant", "wrong_universes", "changed_target", "sorry_axiom"])
def test_live_checker_rejects_untrusted_structural_terms(live_adapter, kind):
    payload = {"mode":"check", "request_id":"live-malicious-data", "environment":live_adapter.environment,
        "target":RECORD["name"], "prefix":"", "reference":RECORD["src"],
        "max_heartbeats":200000, "node_budget":20000, "allowed_axioms":list(live_adapter.context.allowed_axioms)}
    # Get the real toolchain identity from an actual isolated export.
    candidate = STATEMENT + " := by sorry" if kind == "sorry_axiom" else CANDIDATE
    produced = live_adapter._run_stage({**payload, "mode":"produce", "candidate":candidate})
    assert produced["report"]["status"] == "EXPORTED", produced
    export = artifact(live_adapter.environment, githash=produced["lean_githash"])
    if kind == "wrong_type": export["dag"]["expressions"][0][1] = [["s","False"]]
    elif kind == "bad_proof": export["dag"]["expressions"][1] = ["const",[["s","Nat"],["s","zero"]],[]]
    elif kind == "missing_constant": export["dag"]["expressions"][1] = ["const",[["s","nonexistent_helper"]],[]]
    elif kind == "wrong_universes": export["level_parameters"] = [[["s","u"]]]
    elif kind == "changed_target": export["target"] = "wrong_target"
    else: export = produced["report"]["export"]
    result = live_adapter._run_stage({**payload,"export":export})
    expected = "UNSUPPORTED" if kind == "missing_constant" else "REJECTED"
    assert result["report"]["status"] == expected, result
    if kind == "bad_proof": assert result["report"]["reason"] == "kernel_rejected"
    if kind == "sorry_axiom": assert result["report"]["reason"] == "axiom_expansion"


def test_live_valid_substituted_export_does_not_establish_source_correspondence(live_adapter, monkeypatch):
    # This is an explicit remaining limitation, not an acceptance test for
    # source binding: independently checking valid data cannot identify which
    # source was actually elaborated by an adversarial producer.
    run = live_adapter._run_stage
    def substitute(payload):
        if payload["mode"] == "produce":
            payload = {**payload, "candidate": CANDIDATE}
        return run(payload)  # actual isolated producer and actual fresh checker
    monkeypatch.setattr(live_adapter, "_run_stage", substitute)
    unproved = STATEMENT + " := by skip"
    result = live_adapter.evaluate(unproved)
    assert result["status"] == "PROOF_DATA_CHECKED", result
    assert result["candidate_sha256"] == replay.source_hash(unproved)
    assert result["candidate_source_verified"] is result["metric_integrity_established"] is result["promoted"] is False


@pytest.mark.parametrize("prefix,target,statement,proof", [
    ("universe u\n", "universe_replay", "theorem universe_replay {α : Sort u} (x : α) : x = x", "by rfl"),
    ("namespace Demo\nsection\nvariable (h : True)\ninclude h\n", "Demo.sample",
     "theorem sample : True", "by exact h"),
])
def test_live_universes_and_scopes(live_adapter, prefix, target, statement, proof):
    record = {**RECORD, "name":target, "statement":statement, "src":statement + " := " + proof}
    adapter = replay.ArenaTermReplay(record, replace(live_adapter.binding, prefix=prefix),
                                     isolation=live_adapter.isolation, max_processes=2)
    result = adapter.evaluate(record["src"])
    assert result["status"] == "PROOF_DATA_CHECKED", result


def test_live_cold_measurement_counter_and_export_share_one_producer(live_adapter):
    adapter = replay.ArenaTermReplay(RECORD, live_adapter.binding, isolation=live_adapter.isolation,
                                     max_processes=2, cold_measurement=True)
    result = adapter.evaluate(CANDIDATE)
    assert result["status"] == "PROOF_DATA_CHECKED", result
    assert type(result["producer_reported_raw_heartbeats"]) is int
    assert result["producer_reported_raw_heartbeats"] > 0
    assert [s["mode"] for s in result["stages"]] == ["measure", "check"]
    assert not result["candidate_source_verified"] and not result["metric_integrity_established"]


def test_live_process_warmth_only_gain_disappears_in_cold_measurements(live_adapter):
    # TRUSTED adversarial instrumentation for a real isolated canary. The old
    # two-branch driver lets the first branch warm worker-local scratch state.
    # This is not an optimizer-generated candidate or a production-safe tactic.
    prefix = '''import Lean
open Lean Elab Tactic
def canaryWork (n : Nat) : TacticM Unit := do
  for _ in [:n] do
    evalTactic (← `(tactic| skip))
elab "canaryReference" : tactic => do
  canaryWork 100
  IO.FS.writeFile "/tmp/jevops-warmth-canary" "warm"
  evalTactic (← `(tactic| exact True.intro))
elab "canaryCandidate" : tactic => do
  unless (← (System.FilePath.mk "/tmp/jevops-warmth-canary").pathExists) do canaryWork 1000
  evalTactic (← `(tactic| exact True.intro))
'''
    statement = "theorem warmth_control : True"
    reference, candidate = (statement + " := by " + tactic for tactic in ("canaryReference", "canaryCandidate"))
    record = {**RECORD, "name": "warmth_control", "statement": statement, "src": reference}
    binding = replace(live_adapter.binding, prefix=prefix)
    paired, code = native.run_native(binding, {"request_id": "warmth-canary", "target": record["name"],
        "prefix": prefix, "reference": reference, "candidate": candidate, "max_heartbeats": 2000000,
        "candidate_first": False}, timeout=60, isolation=live_adapter.isolation)
    assert code == 0 and paired["report"]["outcome"] == "VERIFIED", paired
    assert paired["report"]["raw_heartbeats"] < paired["report"]["reference_raw_heartbeats"], paired
    adapter = replay.ArenaTermReplay(record, binding, isolation=live_adapter.isolation,
                                     max_processes=4, cold_measurement=True)
    control, changed = adapter.evaluate(reference), adapter.evaluate(candidate)
    assert control["status"] == changed["status"] == "PROOF_DATA_CHECKED", (control, changed)
    assert changed["producer_reported_raw_heartbeats"] > control["producer_reported_raw_heartbeats"], (control, changed)
    assert changed["metric_integrity_established"] is changed["promoted"] is False


@pytest.mark.parametrize("tag", ["v4.26.0", "v4.34.0"])
@pytest.mark.parametrize("statement,body,constants", [
    ("theorem linked (h : True) : True", "@h", ()),
    ("theorem linked (f : True -> True) (h : True) : True", "(@f @h)", ()),
    ("theorem linked (A : Prop) (B : Prop) (ha : A) (hb : B) : And A B",
     "(@_root_.And.intro @A @B @ha @hb)", ("And.intro",)),
    ("theorem linked : True", "@_root_.True.intro", ("True.intro",)),
])
def test_live_explicit_source_structure_and_kernel_check(live_profile, tmp_path, tag, statement, body, constants):
    pin = VersionPin(tag, "explicit-source-smoke")
    source = statement + " := by exact " + body
    record = {"name": "linked", "statement": statement, "src": source,
              "version_info": [{pin.lean_tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, native.pinned_lean(Path(os.environ["ELAN_HOME"]), tag),
                                    tmp_path, "", project_backed=False)
    adapter = replay.ArenaTermReplay(record, binding, isolation=live_profile, max_processes=2,
        source_policy=ExplicitTermPolicy(constants), cold_measurement=True)
    result = adapter.evaluate(source)
    assert result["status"] == "PROOF_DATA_CHECKED", result
    assert result["source_export_binding"] == "EXPLICIT_TERM_STRUCTURE_CHECKED"
    assert result["source_structure"]["structure_matches"] and result["proof_data_checked"]
    assert result["producer_reported_raw_heartbeats"] > 0
    assert result["process_attempts"] == result["processes_reserved"] == 2
    assert not any(result[k] for k in ("candidate_source_verified", "source_execution_attested",
                                       "metric_integrity_established", "promoted", "training_enabled"))


def test_live_explicit_source_blocks_proof_irrelevance_substitution(live_adapter, monkeypatch):
    statement = "theorem two_proofs (h1 : True) (h2 : True) : True"
    source = statement + " := by exact @h1"
    record = {**RECORD, "name": "two_proofs", "statement": statement, "src": source}
    adapter = replay.ArenaTermReplay(record, live_adapter.binding, isolation=live_adapter.isolation,
        max_processes=2, source_policy=ExplicitTermPolicy())
    run = adapter._run_stage
    def substitute(payload):
        assert payload["mode"] == "produce"  # mismatch rejected before checker
        return run({**payload, "candidate": statement + " := by exact @h2"})
    monkeypatch.setattr(adapter, "_run_stage", substitute)
    result = adapter.evaluate(source)
    assert result["status"] == "REJECTED" and "local_reference_mismatch" in result["reason"], result
    assert result["process_attempts"] == 1 and result["processes_reserved"] == 2
    assert not result["proof_data_checked"] and result["source_export_binding"] == "UNESTABLISHED"


def test_live_explicit_source_does_not_treat_goal_binder_as_visible_parameter(live_adapter):
    statement = "theorem function_goal : (h : True) -> True"
    record = {**RECORD, "name": "function_goal", "statement": statement,
              "src": statement + " := by intro h; exact h"}
    adapter = replay.ArenaTermReplay(record, live_adapter.binding, isolation=live_adapter.isolation,
        max_processes=2, source_policy=ExplicitTermPolicy())
    result = adapter.evaluate(statement + " := by exact @h")
    assert result["status"] == "UNSUPPORTED" and result["process_attempts"] == result["processes_reserved"] == 0


def test_live_explicit_same_term_does_not_attest_which_source_executed(live_adapter, monkeypatch):
    adapter = replay.ArenaTermReplay(RECORD, live_adapter.binding, isolation=live_adapter.isolation,
        max_processes=2, source_policy=ExplicitTermPolicy(), cold_measurement=True)
    run = adapter._run_stage
    def substitute(payload):
        if payload["mode"] == "measure":
            # A different tactic program produces the very same explicit term.
            # Matching that term cannot authenticate this program's work/cost.
            payload = {**payload, "candidate": STATEMENT + " := by first | exact h | skip"}
        return run(payload)
    monkeypatch.setattr(adapter, "_run_stage", substitute)
    result = adapter.evaluate(STATEMENT + " := by exact @h")
    assert result["status"] == "PROOF_DATA_CHECKED", result
    assert result["source_export_binding"] == "EXPLICIT_TERM_STRUCTURE_CHECKED"
    assert result["source_structure"]["structure_matches"]
    assert not result["source_execution_attested"] and not result["candidate_source_verified"]
    assert not result["metric_integrity_established"] and not result["promoted"]


@pytest.mark.parametrize("tag", ["v4.26.0", "v4.34.0"])
def test_live_size_guard_rejects_larger_explicit_kernel_checked_proof(live_profile, tmp_path, tag):
    pin = VersionPin(tag, "export-size-guard-smoke")
    statement = "theorem size_control (f : True -> True) (h : True) : True"
    reference = statement + " := by exact @h"
    candidate = statement + " := by exact (@f (@f @h))"
    record = {"name": "size_control", "statement": statement, "src": reference,
              "version_info": [{tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, native.pinned_lean(Path(os.environ["ELAN_HOME"]), tag),
                                    tmp_path, "", project_backed=False)
    adapter = replay.ArenaTermReplay(record, binding, isolation=live_profile, max_processes=16,
        source_policy=ExplicitTermPolicy(), cold_measurement=True, export_size_guard=True)
    result = adapter.cold_comparison(candidate)
    assert result["status"] == "GUARD_REJECTED", result
    assert result["reason"] == "checked_export_size_growth"
    assert result["source_export_binding"] == "EXPLICIT_TERM_STRUCTURE_CHECKED"
    assert all(s["observation"]["proof_data_checked"] for s in result["samples"])
    assert all(s["observation"]["checked_export_size"]["export_sha256"] ==
               s["observation"]["export_sha256"] for s in result["samples"])
    assert result["process_attempts"] == result["processes_reserved"] == 16
    assert not result["promotion_eligible"] and not result["source_execution_attested"]
    assert not result["metric_integrity_established"]
