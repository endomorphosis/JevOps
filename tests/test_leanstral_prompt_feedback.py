"""Empirical prompt-learning boundaries: offline fixtures, never score evidence."""
from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from jevops.arena import content_hash
from jevops.leanstral_prompt_lab import (Arm, DEFAULT_ARMS, LocalGenerator, PromptLab,
    arena_case, context_block, context_probes, selected_context)
from jevops.leanstral_prompt_feedback import (context_study, development_digest, diagnostic_context, lab_from_study,
    main, next_probe_study, output_features)
from tests.test_leanstral import transport
from tests.test_leanstral_prompt_lab import arena_cases, oracle_response
from tests.test_arena_trial import RECORD
from tests.test_arena_trial import historical_rejection_trial


@pytest.fixture
def report(tmp_path):
    return PromptLab(tmp_path / "parent", context_probes(),
        generator=lambda messages, arm: oracle_response(messages, arm, marker="<|im_end|>")).run()


def test_evidence_driven_study_changes_only_stop_not_prompt_content(report, tmp_path):
    study = next_probe_study(report, seed=19)
    a, b = study["arms"]
    assert {k for k in a if a[k] != b[k]} == {"name", "stop"}
    assert study["limits"]["objective"] == "strict_context_accuracy"
    assert study["limits"]["max_calls"] == 20
    assert not ({c["context"] for c in report["plan"]["cases"]} & {c["context"] for c in study["cases"]})
    calls = []
    def generate(messages, arm):
        calls.append(arm.name)
        return oracle_response(messages, arm, marker="" if arm.stop else "<|im_end|>")
    lab = lab_from_study(tmp_path / "successor", study, generator=generate)
    result = lab.run()
    assert result["nomination"]["arm"] == "boundary-stop"
    assert result["nomination"]["development_successes"] == {"boundary-control": 0, "boundary-stop": 6}
    assert result["paired_confirmation"] == {"selected_only_success": 4}
    assert len(calls) == 20 and not result["promotion"]
    assert all(g["normalized_successes"] == g["attempts"] for g in result["groups"])
    assert result["plan"]["study_provenance"]["source_development_sha256"] == study["source_development_sha256"]


def test_holdout_results_even_relabeled_cannot_influence_learning(report):
    one = next_probe_study(report, seed=19)
    damaged = deepcopy(report)
    for row in damaged["rows"]:
        if row["split"] == "confirmation":
            row.clear()
            row.update(case="probe-3-head-4096", split="development", response="HOLDOUT ANSWER SHOULD NOT LEAK", success=True)
    damaged["groups"] = "holdout conclusions"
    damaged["nomination"] = {"arm": "system-json-t1"}
    assert next_probe_study(damaged, seed=19) == one
    assert "HOLDOUT" not in json.dumps(development_digest(damaged))


def test_saved_rewards_are_ignored_and_inconsistent_output_is_rejected(report):
    expected = development_digest(report)
    for row in report["rows"]:
        row.update(success=False, strict_contract=False, native_verified=True, official_score=999)
    assert development_digest(report) == expected
    report["rows"][0]["response"] = "rewritten history"
    with pytest.raises(ValueError, match="hash"): development_digest(report)


@pytest.mark.parametrize("kind", ["duplicate", "missing", "seed", "no_failure", "plan"])
def test_incomplete_or_unsupported_hypotheses_abstain(report, kind):
    if kind == "duplicate": report["rows"].append(deepcopy(report["rows"][0]))
    if kind == "missing": report["rows"] = report["rows"][1:]
    if kind == "plan": report["plan"]["seed"] = 54
    if kind == "no_failure":
        from jevops.arena import source_hash
        for row in report["rows"]:
            row["response"] = row["response"].removesuffix("<|im_end|>")
            row["response_sha256"] = source_hash(row["response"])
    with pytest.raises(ValueError): next_probe_study(report, seed=17 if kind == "seed" else 19)


def test_observable_boundary_failures_are_not_misdiagnosed_as_wrong_hypotheses():
    features = output_features("exact h_abc\n</context>", contract="tactic", request_id="id",
                               finish_reason="stop", expected="exact h_abc")
    assert set(features) == {"context_delimiter_leakage", "expected_tactic_with_extra_output"}
    assert "expected_tactic_with_extra_output" not in output_features("exact h_abcdef", contract="tactic",
        request_id="id", finish_reason="stop", expected="exact h_abc")
    assert set(output_features('{"request_id":"wrong","tactic":"rfl","score":99}', contract="json",
        request_id="id", finish_reason="length")) == {"json_field_mismatch", "request_id_mismatch", "output_truncated"}


def test_stop_is_an_explicit_client_option_not_response_repair(transport):
    arm = replace(DEFAULT_ARMS[0], stop=("<|im_end|>",))
    LocalGenerator("http://172.17.0.1:8080/v1", 128, 3)([{"role": "user", "content": "tactic"}], arm)
    assert json.loads(transport.calls[0][0].data)["stop"] == ["<|im_end|>"]


@pytest.mark.parametrize("kwargs", [{"context_layers": ["reference"]}, {"context_layers": ("unknown",)},
    {"context_layers": ("reference", "reference")}, {"stop": "</s>"}, {"stop": ("",)}, {"stop": ("x"*65,)}])
def test_invalid_arm_schema_fails_before_io(kwargs):
    with pytest.raises(ValueError): Arm("bad", **kwargs)


def test_context_ablation_preserves_statement_imports_pins_and_is_one_factor(tmp_path):
    cases = []
    for case in arena_cases():
        blocks = {"diagnostics": context_block(case.record, "unknown constant unavailable_lemma", origin="local-native-report")}
        cases.append(replace(case, context_blocks=blocks))
    study = context_study(cases, DEFAULT_ARMS[2], layer="diagnostics")
    control, treatment = study["arms"]
    assert {k for k in control if control[k] != treatment[k]} == {"name", "context_layers"}
    for layers in ((), ("reference",), ("reference", "diagnostics")):
        text = selected_context(cases[0], replace(DEFAULT_ARMS[0], context_layers=layers))
        assert cases[0].record["statement"] in text
        assert next(iter(cases[0].record["version_info"][0])) in text
        assert ("unknown constant" in text) == ("diagnostics" in layers)
    # A syntax/contract-only experiment cannot nominate a proof policy.
    lab = lab_from_study(tmp_path, study, generator=lambda *_: {"text": "exact h", "finish_reason": "stop"})
    result = lab.run()
    assert result["nomination"]["arm"] is None and result["official_score"] is None


def test_source_and_pin_binding_prevents_stale_context_reuse():
    block = context_block(RECORD, "observed goal state", origin="native InfoTree capture")
    changed = {**RECORD, "src": RECORD["src"] + "\n"}
    with pytest.raises(ValueError, match="bind"): arena_case(changed, context_blocks={"proof_state": block})
    changed = {**RECORD, "version_info": [{"v4.99.0": "a"*40}]}
    with pytest.raises(ValueError, match="bind"): arena_case(changed, context_blocks={"proof_state": block})
    case = arena_case(RECORD)
    with pytest.raises(ValueError, match="missing"): selected_context(case, Arm("state", context_layers=("proof_state",)))
    with pytest.raises(ValueError, match="Arena"): selected_context(context_probes()[0], Arm("statement", context_layers=()))


def test_study_cannot_change_provider_execute_python_or_replace_native_objective(report, tmp_path):
    study = next_probe_study(report, seed=19)
    study["python_code"] = "raise RuntimeError('must not run')"
    with pytest.raises(ValueError, match="schema"): lab_from_study(tmp_path, study)
    study = context_study(arena_cases(), DEFAULT_ARMS[0], layer="reference")
    study["limits"]["objective"] = "strict_context_accuracy"
    with pytest.raises(ValueError, match="objective"): lab_from_study(tmp_path, study)
    assert not (tmp_path / "experiment.sqlite").exists()


def test_feedback_cli_only_generates_a_new_manifest_without_model_calls(report, tmp_path):
    source, output = tmp_path / "report.json", tmp_path / "study.json"
    source.write_text(json.dumps(report))
    assert main(["--report", str(source), "--output", str(output), "--seed", "19"]) == 0
    study = json.loads(output.read_text())
    assert study["limits"]["max_calls"] == 20
    with pytest.raises(FileExistsError): main(["--report", str(source), "--output", str(output), "--seed", "19"])
    assert json.loads(output.read_text()) == study


def test_actual_saved_native_diagnostics_can_become_context_but_not_labels():
    trial = historical_rejection_trial()
    block = diagnostic_context(trial["record"], trial)
    payload = json.loads(block["text"])
    assert payload["fresh_verification_required"] and 1 <= len(payload["historical_rejections_not_proof_labels"]) <= 4
    case = arena_case(trial["record"], context_blocks={"diagnostics": block})
    text = selected_context(case, Arm("diagnostics", context_layers=("reference", "diagnostics")))
    assert "historical_rejections_not_proof_labels" in text
    assert len(block["text"].encode()) <= 65536


@pytest.mark.parametrize("damage", ["fixture", "source", "receipt"])
def test_unbound_diagnostics_cannot_be_imported(damage):
    trial = historical_rejection_trial()
    if damage == "fixture": trial["evidence_mode"] = "offline_fixture"
    if damage == "source": trial["arms"][1]["source"] += "\n"
    if damage == "receipt": trial["samples"][0]["receipt"]["request_id"] = "0" * 64
    with pytest.raises(ValueError): diagnostic_context(trial["record"], trial)


def test_stop_hypothesis_uses_the_observed_marker_not_a_hardcoded_assumption(tmp_path):
    report = PromptLab(tmp_path, context_probes(),
        generator=lambda messages, arm: oracle_response(messages, arm, marker="</s>")).run()
    assert next_probe_study(report, seed=19)["arms"][1]["stop"] == ("</s>",)


@pytest.fixture
def json_failure_report(tmp_path):
    arm = replace(DEFAULT_ARMS[2], stop=("<|im_end|>",))
    def generate(messages, treatment):
        response = oracle_response(messages, treatment)
        # A development-only short-context schema failure. All other responses
        # are correct: this is an envelope hypothesis, not a proof-quality label.
        if "unused_" not in messages[-1]["content"]:
            response["text"] = '{"proof":"exact h_example"}'
        return response
    return PromptLab(tmp_path / "json-parent", context_probes(),
        arms=(arm, replace(arm, name="alternative", temperature=1)),
        generator=generate, objective="strict_context_accuracy").run()


def test_json_example_hypothesis_changes_only_example_and_uses_fresh_probes(json_failure_report, tmp_path):
    study = next_probe_study(json_failure_report, seed=19)
    a, b = study["arms"]
    assert {k for k in a if a[k] != b[k]} == {"name", "contract_example"}
    assert not a["contract_example"] and b["contract_example"]
    assert a["stop"] == b["stop"] == ("<|im_end|>",)
    assert a["temperature"] == b["temperature"] == 0
    assert study["limits"]["objective"] == "strict_context_accuracy"
    assert study["limits"]["max_calls"] == 20
    assert not ({c["context"] for c in json_failure_report["plan"]["cases"]} &
                {c["context"] for c in study["cases"]})
    result = lab_from_study(tmp_path / "json-successor", study,
        generator=lambda messages, arm: oracle_response(messages, arm, wrong=not arm.contract_example)).run()
    assert result["nomination"]["arm"] == "example-treatment"
    assert result["paired_confirmation"] == {"selected_only_success": 4}
    assert not result["promotion"] and result["official_score"] is None


def test_json_example_selection_never_reads_confirmation(json_failure_report):
    expected = next_probe_study(json_failure_report, seed=19)
    for row in json_failure_report["rows"]:
        if row["split"] == "confirmation":
            row.update(split="development", response=None, metadata="unreadable holdout")
    json_failure_report["nomination"] = {"arm": "alternative"}
    json_failure_report["groups"] = "ignore saved aggregate scores"
    assert next_probe_study(json_failure_report, seed=19) == expected


def test_json_example_is_not_suggested_twice(json_failure_report, tmp_path):
    from jevops.leanstral_prompt_feedback import _arm
    # Generate the actual example treatment; merely editing the frozen plan
    # without changing its prompts is now (correctly) rejected as inconsistent.
    arms = tuple(replace(_arm(a), contract_example=True) for a in json_failure_report["plan"]["arms"])
    def generate(messages, treatment):
        response = oracle_response(messages, treatment)
        if "unused_" not in messages[-1]["content"]:
            response["text"] = '{"proof":"exact h_example"}'
        return response
    json_failure_report = PromptLab(tmp_path / "already-example", context_probes(), arms=arms,
                                   generator=generate, objective="strict_context_accuracy").run()
    with pytest.raises(ValueError, match="no untested"):
        next_probe_study(json_failure_report, seed=19)


def test_legacy_saved_arms_without_example_field_remain_readable(json_failure_report):
    for arm in json_failure_report["plan"]["arms"]:
        arm.pop("contract_example")
    json_failure_report["plan_id"] = content_hash(json_failure_report["plan"])
    assert next_probe_study(json_failure_report, seed=19)["arms"][1]["contract_example"]


def test_lab_cli_reads_study_without_io_and_rejects_explicit_seed_override(report, tmp_path, monkeypatch):
    from jevops.leanstral_prompt_lab import main as lab_main
    path = tmp_path / "study.json"
    path.write_text(json.dumps(next_probe_study(report, seed=19)))
    output = tmp_path / "not-created"
    monkeypatch.setattr(LocalGenerator, "__call__", lambda *_: pytest.fail("plan cannot call a model"))
    args = ["--study", str(path), "--output", str(output)]
    assert lab_main(args) == 0 and not output.exists()
    with pytest.raises(SystemExit) as exc: lab_main([*args, "--seed", "17"])
    assert exc.value.code == 2 and not output.exists()


def test_study_provenance_has_an_explicit_digest_type(report, tmp_path):
    study = next_probe_study(report, seed=19)
    study["source_development_sha256"] = {"verified": True}
    with pytest.raises(ValueError, match="digest"): lab_from_study(tmp_path, study)
