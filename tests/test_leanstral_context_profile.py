"""Offline empirical-context experiments; fixtures are never Leanstral results."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from jevops.arena import content_hash
from jevops.leanstral_context_profile import (development_anchor, development_profile, main,
    probe_data, profile_cases, profile_study, render_probe)
from jevops.leanstral_prompt_feedback import development_digest, lab_from_study, next_probe_study, output_features
from jevops.leanstral_prompt_lab import Arm, Case, PromptLab, arena_case, context_probes, render
from tests.test_arena_trial import RECORD


def generator_for(cases, arms, response=None):
    lookup = {content_hash(render(c, a, r)[0]): (c, render(c, a, r)[1])
              for c in cases for a in arms for r in range(2)}
    def generate(messages, arm):
        case, request_id = lookup[content_hash(messages)]
        tactic = response(case, arm) if response else case.expected
        if arm.contract == "json": tactic = json.dumps({"request_id": request_id, "tactic": tactic})
        return {"text": tactic, "finish_reason": "stop", "fixture": True}
    return generate


def run_study(tmp_path, *, response=None, parent=None):
    study = profile_study(seed=73, distractors=(8, 32), parent=parent)
    lab = lab_from_study(tmp_path, study)
    return lab_from_study(tmp_path, study,
        generator=generator_for(lab.cases, lab.arms, response=response)).run()


def test_full_factor_matrix_fresh_holdouts_and_identical_facts():
    cases = profile_cases(seed=71)
    assert len(cases) == 12 and cases == profile_cases(seed=71) and cases != profile_cases(seed=72)
    goals = {}
    for split in ("development", "confirmation"):
        own = [c for c in cases if c.split == split]
        assert Counter((probe_data(c)["distractors"], probe_data(c)["position"]) for c in own) == Counter({
            (n, p): 1 for n in (16, 128) for p in ("head", "middle", "tail")})
        goals[split] = {probe_data(c)["goal"] for c in own}
        for case in own:
            data = probe_data(case)
            goal = render_probe(case, "lean_goal")
            obj = json.loads(render_probe(case, "json_locals"))
            assert obj["locals"] == data["locals"] and obj["goal"] == data["goal"]
            assert all(f"{h['name']} : {h['type']}" in goal for h in obj["locals"])
            assert case.expected not in goal and case.expected not in json.dumps(obj)
            assert "distractors" not in obj and "position" not in obj
    assert not goals["development"] & goals["confirmation"]


@pytest.mark.parametrize("sizes", [(), [], (1,), (True,), (513,), (4, 4), (32, 8), (2, 4, 8)])
def test_bounded_design_rejects_invalid_factors(sizes):
    with pytest.raises(ValueError): profile_cases(distractors=sizes)


@pytest.mark.parametrize("damage", ["duplicate", "type", "goal", "count", "position", "oracle", "extra"])
def test_inconsistent_structured_context_fails_before_generation(damage):
    case = profile_cases(distractors=(8,))[0]
    value = json.loads(case.context)
    if damage == "duplicate": value["locals"][1] = value["locals"][0]
    elif damage == "type": value["locals"][1]["type"] = "ArbitraryTerm"
    elif damage == "goal": value["goal"] = "True"
    elif damage == "count": value["distractors"] += 1
    elif damage == "position": value["position"] = "tail"
    elif damage == "extra": value["answer"] = case.expected
    else: case = replace(case, expected="exact wrong")
    with pytest.raises(ValueError):
        render(replace(case, context=json.dumps(value)), Arm("probe", probe_representation="lean_goal"))


def test_one_format_factor_budget_and_all_arms_confirmation_predeclared(tmp_path):
    study = profile_study(seed=71)
    a, b = study["arms"]
    assert {k for k in a if a[k] != b[k]} == {"name", "probe_representation"}
    assert study["limits"]["max_calls"] == 48 and study["limits"]["confirmation_policy"] == "all_arms"
    assert study["limits"]["max_native_requests"] == 0
    lab = lab_from_study(tmp_path / "unused", study)
    assert not (tmp_path / "unused").exists()
    for case in lab.cases:
        messages = [render(case, arm) for arm in lab.arms]
        assert messages[0][1] == messages[1][1]
        assert all(case.expected not in json.dumps(m[0]) for m in messages)


def test_baseline_tie_does_not_skip_the_other_confirmatory_format(tmp_path):
    report = run_study(tmp_path)
    assert report["nomination"]["arm"] == "context-lean"
    assert report["calls_reserved"] == 48 and report["confirmation_complete"]
    assert report["paired_confirmation"] == {"tie": 12}
    assert report["confirmation_pairwise_against_baseline"] == {"context-json": {"tie": 12}}
    assert Counter(r["arm"] for r in report["rows"] if r["split"] == "confirmation") == {
        "context-lean": 12, "context-json": 12}
    assert report["plan"]["mode"] == "offline_fixture" and not report["promotion"]
    profile = development_profile(report)
    assert profile["fully_measured"] and len(profile["cells"]) == 12
    assert not profile["confirmation_consumed"] and profile["context_window_limit"] is None
    assert not profile["native_quality_established"] and not profile["followup_hypotheses"]


def test_profile_recomputes_failures_by_size_position_and_representation(tmp_path):
    def respond(case, arm):
        data = probe_data(case)
        if arm.probe_representation == "json_locals" and data["distractors"] == 32 and data["position"] == "middle":
            return "exact wrong"
        return case.expected
    report = run_study(tmp_path, response=respond)
    profile = development_profile(report)
    failures = [c for c in profile["cells"] if c["strict_contract_oracle_mismatches"]]
    assert report["confirmation_pairwise_against_baseline"] == {"context-json": {"tie": 10, "baseline_only_success": 2}}
    assert len(failures) == 1 and failures[0]["strict_contract_oracle_mismatches"] == 2
    assert (failures[0]["distractors"], failures[0]["position"], failures[0]["representation"]) == (32, "middle", "json_locals")
    assert profile["followup_hypotheses"][0]["symptom"] == "well_formed_output_misses_context_oracle"
    changed = deepcopy(report)
    for row in changed["rows"]:
        if row["split"] == "confirmation":
            row.update(split="development", response="HOLDOUT SECRET", metadata="ignored", response_sha256="not read")
        else: row.update(success=True, normalized_success=True, official_score=999)
    changed["nomination"] = changed["groups"] = "ignore saved conclusions"
    assert development_profile(changed) == profile
    assert development_anchor(changed) == development_anchor(report)


def test_partial_transport_failure_is_unknown_and_cannot_nominate_or_teach(tmp_path):
    report = run_study(tmp_path, response=lambda c, a: c.expected if a.name == "context-lean"
                       else (_ for _ in ()).throw(TimeoutError("do not save secret")))
    assert report["nomination"]["arm"] is None and not report["confirmation_complete"]
    assert all(r["success"] is None for r in report["rows"] if r["arm"] == "context-json")
    profile = development_profile(report)
    assert not profile["fully_measured"] and not profile["followup_hypotheses"]
    assert sum(c["unmeasured"] for c in profile["cells"]) == 12
    assert "do not save secret" not in json.dumps(report)
    with pytest.raises(ValueError, match="measured"): development_anchor(report)
    with pytest.raises(ValueError, match="unmeasured"): next_probe_study(report, seed=79)


def test_prompt_self_hash_cannot_disguise_a_different_treatment(tmp_path):
    report = run_study(tmp_path)
    row = next(r for r in report["rows"] if r["split"] == "development")
    row["messages"][-1]["content"] += "Hidden treatment change"
    row["prompt_sha256"] = content_hash(row["messages"])
    with pytest.raises(ValueError, match="frozen case/arm"): development_digest(report)


def test_probe_formatter_never_substitutes_for_arena_context():
    with pytest.raises(ValueError, match="not Arena"):
        render(arena_case(RECORD), Arm("wrong", probe_representation="json_locals"))
    with pytest.raises(ValueError): render(context_probes()[0], Arm("wrong", probe_representation="json_locals"))


def test_parent_anchor_fresh_study_changes_only_measured_format_factor(tmp_path):
    parent = run_study(tmp_path / "parent")
    study = profile_study(seed=79, distractors=(8,), parent=parent)
    assert study["source_development_sha256"] == development_digest(parent)["development_sha256"]
    assert study["limits"]["max_calls"] == 24
    assert not {c["expected"] for c in study["cases"]} & {c["expected"] for c in parent["plan"]["cases"]}
    with pytest.raises(ValueError, match="fresh"): profile_study(seed=73, parent=parent)


def test_literal_placeholder_is_an_observed_wording_hypothesis_not_a_parser_relaxation(tmp_path):
    cases = context_probes(71)
    arms = (Arm("anchor", contract="json", stop=("<|im_end|>",)),
            Arm("second", contract="json", stop=("<|im_end|>",), temperature=1))
    generate = generator_for(cases, arms, response=lambda c, a: "the tactic body without by"
                             if c.name == cases[0].name else c.expected)
    report = PromptLab(tmp_path, cases, arms=arms, generator=generate, seed=71).run()
    assert "literal_contract_placeholder" in output_features('{"request_id":"id","tactic":"the tactic body without by"}',
        contract="json", request_id="id", finish_reason="stop")
    study = next_probe_study(report, seed=79)
    a, b = study["arms"]
    assert {k for k in a if a[k] != b[k]} == {"name", "json_contract_style"}
    assert b["json_contract_style"] == "descriptive"


def test_profile_successor_preserves_factors_instead_of_substituting_easy_probes(tmp_path):
    cases = profile_cases(seed=71, distractors=(8, 32))
    arms = (Arm("anchor", contract="json", probe_representation="json_locals"),
            Arm("second", contract="json", probe_representation="json_locals", temperature=1))
    generate = generator_for(cases, arms, response=lambda c, a: "the tactic body without by"
                             if probe_data(c)["position"] == "head" else c.expected)
    report = PromptLab(tmp_path, cases, arms=arms, generator=generate, seed=71, max_calls=48).run()
    study = next_probe_study(report, seed=79)
    assert {probe_data(Case(**c))["distractors"] for c in study["cases"]} == {8, 32}
    assert len(study["cases"]) == 12 and study["arms"][1]["probe_representation"] == "json_locals"


def test_cli_generates_only_no_calls_and_no_overwrite(tmp_path, capsys):
    destination = tmp_path / "study.json"
    assert main(["--output", str(destination), "--distractors", "8", "32", "--seed", "71"]) == 0
    assert json.loads(capsys.readouterr().out)["model_calls"] == 0
    before = destination.read_bytes()
    with pytest.raises(FileExistsError): main(["--output", str(destination)])
    assert destination.read_bytes() == before
    report = run_study(tmp_path / "run")
    saved = tmp_path / "report.json"; saved.write_text(json.dumps(report))
    profile = tmp_path / "profile.json"
    assert main(["--profile-report", str(saved), "--output", str(profile)]) == 0
    assert json.loads(profile.read_text()) == development_profile(report)


def test_all_arms_policy_requires_full_budget_and_legacy_study_still_loads(tmp_path):
    cases = context_probes()
    arms = tuple(Arm(f"arm-{i}") for i in range(3))
    with pytest.raises(ValueError, match="budget"):
        PromptLab(tmp_path, cases, arms=arms, max_calls=26, confirmation_policy="all_arms")
    study = profile_study(distractors=(8,))
    study["limits"].pop("confirmation_policy")
    assert lab_from_study(tmp_path, study).plan["confirmation_policy"] == "nominee"
