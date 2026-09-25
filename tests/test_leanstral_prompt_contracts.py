"""Offline client-binding/contract experiments, never proof or live model evidence."""
from dataclasses import replace
import json

import pytest

from jevops.arena import content_hash, source_hash
from jevops.leanstral_context_profile import profile_cases
from jevops.leanstral_prompt_contracts import (ClientBindingError, bind_response, check_binding,
    comparison_report, main, request_binding, request_id_study)
from jevops.leanstral_prompt_feedback import development_digest, lab_from_study, output_features
from jevops.leanstral_prompt_lab import Arm, LocalGenerator, PromptLab, arena_case, parse_response, proposal_from_policy, render
from tests.test_leanstral import transport
from tests.test_arena_trial import RECORD


def generator(cases, arms, *, wrong_id=False, wrong_tactic=False, binding=True):
    index = {content_hash(render(c, a, r)[0]): (c, render(c, a, r)[1])
             for c in cases for a in arms for r in range(2)}
    def generate(messages, arm):
        case, rid = index[content_hash(messages)]
        obj = {"tactic": "exact not_the_hypothesis" if wrong_tactic else case.expected}
        if arm.contract == "json":
            obj["request_id"] = "wrong-id" if wrong_id and arm.probe_representation == "lean_goal" else rid
        raw = json.dumps(obj)
        result = {"text": raw, "finish_reason": "stop", "fixture": True}
        if binding: result["client_binding"] = bind_response(request_binding(messages, arm), raw)
        return result
    return generate


@pytest.fixture
def parent(tmp_path):
    cases = profile_cases(seed=107, distractors=(32,))
    base = Arm("lean", contract="json", contract_example=True, probe_representation="lean_goal", stop=("<|im_end|>",))
    arms = (base, replace(base, name="json", probe_representation="json_locals"))
    return PromptLab(tmp_path / "parent", cases, arms=arms, max_calls=24, seed=107,
        confirmation_policy="all_arms", generator=generator(cases, arms, wrong_id=True)).run()


def test_request_id_study_uses_failure_evidence_not_saved_winner(parent):
    study = request_id_study(parent, seed=109)
    a, b = study["arms"]
    assert parent["nomination"]["arm"] == "json"  # Study diagnoses another arm's observed failure.
    assert a["probe_representation"] == b["probe_representation"] == "lean_goal"
    assert {k for k in a if a[k] != b[k]} == {"name", "contract"}
    assert a["contract"] == "json" and b["contract"] == "json_tactic"
    assert study["limits"]["max_calls"] == 24 and study["limits"]["max_native_requests"] == 0
    assert study["limits"]["confirmation_policy"] == "all_arms"
    assert study["source_development_sha256"] == development_digest(parent)["development_sha256"]
    assert not {c["expected"] for c in study["cases"]} & {c["expected"] for c in parent["plan"]["cases"]}


def test_holdout_and_saved_scores_cannot_influence_contract_study(parent):
    expected = request_id_study(parent, seed=109)
    for row in parent["rows"]:
        if row["split"] == "confirmation":
            row.update(split="development", response="never consume confirmation", metadata="ignored")
        else: row.update(success=True, native_verified=True, official_score=999)
    parent["groups"] = parent["nomination"] = "not evidence"
    assert request_id_study(parent, seed=109) == expected


@pytest.mark.parametrize("damage", ["seed", "incomplete", "no_symptom", "unmeasured"])
def test_study_abstains_without_measured_evidence(parent, damage):
    seed = 107 if damage == "seed" else 109
    row = next(r for r in parent["rows"] if r["split"] == "development")
    if damage == "incomplete": parent["rows"].remove(row)
    if damage == "unmeasured": row.pop("response")
    if damage == "no_symptom":
        for r in parent["rows"]:
            if r["split"] == "development":
                obj = json.loads(r["response"]); obj["tactic"] = "exact wrong"
                r["response"] = json.dumps(obj); r["response_sha256"] = source_hash(r["response"])
                r["metadata"]["client_binding"]["response_sha256"] = r["response_sha256"]
    with pytest.raises(ValueError): request_id_study(parent, seed=seed)


def test_old_parser_stays_strict_and_new_parser_is_not_a_fallback():
    old, new = Arm("old", contract="json"), Arm("new", contract="json_tactic")
    raw = '{"request_id":"foreign","tactic":"exact h"}'
    assert parse_response(raw, old, "ours", "stop")["tactic"] is None
    assert parse_response(raw, new, "ours", "stop")["tactic"] is None
    assert parse_response('{"tactic":"exact h"}', old, "ours", "stop")["tactic"] is None
    assert parse_response('{"tactic":"exact h"}', new, "ours", "stop")["tactic"] == "exact h"
    features = output_features(raw, contract="json", request_id="ours", finish_reason="stop", expected="exact h")
    assert set(features) == {"request_id_mismatch", "oracle_tactic_in_invalid_envelope"}


@pytest.mark.parametrize("raw", ['{"tactic":"exact h","tactic":"exact h"}', '{"tactic":false}',
    '{"tactic":"exact h","extra":true}', '```json\n{"tactic":"exact h"}\n```',
    '{"tactic":"by exact h"}', '{"tactic":""}', 'null'])
def test_new_envelope_rejects_invalid_outputs(raw):
    assert parse_response(raw, Arm("new", contract="json_tactic"), "id", "stop")["tactic"] is None


def test_truncated_outputs_and_eos_artifacts_are_not_strict_success():
    arm = Arm("new", contract="json_tactic")
    assert parse_response('{"tactic":"exact h"}', arm, "id", "length")["tactic"] is None
    assert not parse_response('{"tactic":"exact h"}<|im_end|>', arm, "id", "stop")["strict_contract"]


def test_context_request_oracle_and_limits_unchanged_across_treatments(parent, tmp_path):
    lab = lab_from_study(tmp_path / "not-created", request_id_study(parent, seed=109))
    for case in lab.cases:
        old, old_id = render(case, lab.arms[0])
        new, new_id = render(case, lab.arms[1])
        assert old_id == new_id
        # Both inherit user-only roles; split after the instruction/context boundary.
        assert old[-1]["content"].split("<context>")[-1] == new[-1]["content"].split("<context>")[-1]
        assert case.expected not in json.dumps(old) and case.expected not in json.dumps(new)
        assert "exact h_example" in new[0]["content"]
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize("damage", ["missing", "prompt", "arm", "raw", "schema"])
def test_client_binding_rejects_swapped_or_mutated_response(damage):
    arm = Arm("new", contract="json_tactic")
    messages = [{"role": "user", "content": "first request"}]
    raw = '{"tactic":"exact h"}'
    binding = bind_response(request_binding(messages, arm), raw)
    if damage == "missing": binding = None
    elif damage == "prompt": messages[0]["content"] = "different request"
    elif damage == "arm": arm = replace(arm, name="different-arm")
    elif damage == "raw": raw += " "
    else: binding["schema"] = "forged"
    with pytest.raises(ClientBindingError): check_binding(binding, messages, arm, raw)


def test_actual_local_client_attaches_binding_outside_the_model_json(transport):
    arm = Arm("new", contract="json_tactic")
    messages = [{"role": "user", "content": "fixture request"}]
    transport.payload["choices"][0]["message"]["content"] = '{"tactic":"exact h"}'
    result = LocalGenerator("http://172.17.0.1:8080/v1", 128, 3)(messages, arm)
    check_binding(result["client_binding"], messages, arm, result["text"])
    assert "client_binding" not in json.loads(result["text"])
    assert json.loads(transport.calls[0][0].data)["messages"] == messages


def test_missing_binding_is_unknown_not_a_successful_simplified_contract(parent, tmp_path):
    study = request_id_study(parent, seed=109)
    setup = lab_from_study(tmp_path / "run", study)
    report = lab_from_study(tmp_path / "run", study, generator=generator(setup.cases, setup.arms, binding=False)).run()
    own = [r for r in report["rows"] if r["arm"] == "client-bound-tactic"]
    assert len(own) == 12 and all(r["success"] is None and r["status"] == "client_binding_mismatch" for r in own)
    assert report["nomination"]["arm"] is None


def test_comparison_distinguishes_task_accuracy_from_changed_contract(parent, tmp_path):
    study = request_id_study(parent, seed=109)
    setup = lab_from_study(tmp_path / "run", study)
    result = lab_from_study(tmp_path / "run", study, generator=generator(setup.cases, setup.arms, wrong_id=True)).run()
    comparison = comparison_report(result)
    assert comparison["complete"] and not comparison["prior_scores_changed"] and not comparison["promotion"]
    assert all(g["exact_tactics_ignoring_envelope_diagnostic_only"] == 6 for g in comparison["groups"])
    assert all(g["strict_successes_under_declared_contract"] == (0 if g["declared_contract"] == "json" else 6)
               for g in comparison["groups"])
    assert all(g["client_bound_responses"] == 6 for g in comparison["groups"])
    result["nomination"] = result["groups"] = "not used for reporting"
    for row in result["rows"]: row["success"] = not row["success"]
    assert comparison_report(result) == comparison
    row = result["rows"][0]
    row["response"] = row["response"] + " "
    row["response_sha256"] = source_hash(row["response"])
    with pytest.raises(ClientBindingError): comparison_report(result)


def test_wrong_tactic_does_not_pass_with_valid_client_binding(parent, tmp_path):
    study = request_id_study(parent, seed=109)
    setup = lab_from_study(tmp_path / "run", study)
    result = lab_from_study(tmp_path / "run", study, generator=generator(setup.cases, setup.arms, wrong_tactic=True)).run()
    assert all(r["success"] is False for r in result["rows"])
    assert result["nomination"]["arm"] is None and comparison_report(result)["complete"]


def test_retrieval_only_contract_cannot_enter_arena_proposals():
    case = arena_case(RECORD)
    arm = Arm("new", contract="json_tactic")
    with pytest.raises(ValueError, match="retrieval-only"): render(case, arm)
    with pytest.raises(ValueError, match="retrieval-only"):
        proposal_from_policy(case, arm, generator=lambda *_: pytest.fail("must not call generator"))


def test_saved_client_binding_is_checked_by_development_learner(parent):
    row = next(r for r in parent["rows"] if r["split"] == "development")
    row["metadata"]["client_binding"]["request_sha256"] = "0" * 64
    with pytest.raises(ClientBindingError): development_digest(parent)


def test_plan_cli_writes_only_and_never_overwrites(parent, tmp_path, capsys):
    path = tmp_path / "parent.json"; path.write_text(json.dumps(parent))
    out = tmp_path / "study.json"
    args = ["--report", str(path), "--output", str(out), "--seed", "109"]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["model_calls"] == 0
    saved = out.read_bytes()
    with pytest.raises(FileExistsError): main(args)
    assert out.read_bytes() == saved
