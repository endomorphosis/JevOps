"""Offline fixtures for prompt checking, never live model or proof evidence."""
from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from jevops.arena import content_hash, source_hash
from jevops.leanstral_context_profile import profile_cases, probe_data
from jevops.leanstral_prompt_attention import (attention_cases, attention_report, attention_study,
    main, markdown_results, tactic_diagnostic)
from jevops.leanstral_prompt_contracts import bind_response, request_binding
from jevops.leanstral_prompt_feedback import development_digest, lab_from_study
from jevops.leanstral_prompt_lab import Arm, PromptLab, arena_case, proposal_from_policy, render
from tests.test_arena_trial import RECORD


def generator(cases, arms, callback=None):
    index = {content_hash(render(c, a, r)[0]): c for c in cases for a in arms for r in range(2)}
    def generate(messages, arm):
        case = index[content_hash(messages)]
        tactic = callback(case, arm) if callback else case.expected
        raw = json.dumps({"tactic": tactic})
        return {"text": raw, "finish_reason": "stop", "fixture": True,
                "client_binding": bind_response(request_binding(messages, arm), raw)}
    return generate


@pytest.fixture
def parent(tmp_path):
    cases = profile_cases(seed=101, distractors=(32,))
    a = Arm("anchor", contract="json_tactic", probe_representation="lean_goal", roles="system_user",
            stop=("<|im_end|>",), contract_example=True)
    arms = (a, replace(a, name="second", temperature=1))
    return PromptLab(tmp_path / "parent", cases, arms=arms, seed=101, max_calls=24,
                     confirmation_policy="all_arms", generator=generator(cases, arms)).run()


def run_study(parent, tmp_path, callback=None):
    study = attention_study(parent, seed=137)
    lab = lab_from_study(tmp_path, study)
    return lab_from_study(tmp_path, study, generator=generator(lab.cases, lab.arms, callback)).run()


def test_reproducible_fresh_nonce_per_cell_and_full_cross():
    cases = attention_cases(seed=137)
    assert len(cases) == 12 and cases == attention_cases(seed=137)
    assert cases != attention_cases(seed=139)
    assert len({probe_data(c)["goal"] for c in cases}) == 12
    assert len({c.expected for c in cases}) == 12
    for split in ("development", "confirmation"):
        assert {(probe_data(c)["distractors"], probe_data(c)["position"]) for c in cases if c.split == split} == {
            (s, p) for s in (16, 128) for p in ("head", "middle", "tail")}


@pytest.mark.parametrize("seed", [True, -1, 2**32])
def test_invalid_seed_fails_before_io(seed):
    with pytest.raises(ValueError): attention_cases(seed=seed)


def test_single_factor_unchanged_contract_and_context(parent, tmp_path):
    study = attention_study(parent, seed=137)
    a, b = study["arms"]
    assert {k for k in a if a[k] != b[k]} == {"name", "identifier_check"}
    assert a["contract"] == b["contract"] == "json_tactic"
    assert study["limits"]["max_calls"] == 48 and study["limits"]["max_native_requests"] == 0
    assert study["limits"]["confirmation_policy"] == "all_arms"
    lab = lab_from_study(tmp_path / "no-io", study)
    assert not lab.directory.exists()
    for c in lab.cases:
        left, lid = render(c, lab.arms[0])
        right, rid = render(c, lab.arms[1])
        assert lid == rid and left[-1] == right[-1]  # Exact same user context.
        assert right[0]["content"].startswith(left[0]["content"])
        assert "character for character" in right[0]["content"]
        assert c.expected not in json.dumps(right)


def test_parent_selection_ignores_confirmation_and_saved_rewards(parent):
    study = attention_study(parent, seed=137)
    for row in parent["rows"]:
        if row["split"] == "confirmation":
            row.update(split="development", response="holdout secret", metadata="ignored")
        else:
            row.update(success=False, official_score=999)
    parent["groups"] = parent["nomination"] = "ignore"
    assert attention_study(parent, seed=137) == study


@pytest.mark.parametrize("damage", ["seed", "incomplete", "unmeasured", "already_checked", "wrong_contract"])
def test_missing_evidence_or_invalid_anchor_cannot_launch_study(parent, damage):
    seed = 101 if damage == "seed" else 137
    row = next(r for r in parent["rows"] if r["split"] == "development")
    if damage == "incomplete": parent["rows"].remove(row)
    if damage == "unmeasured": row.pop("response")
    if damage in ("already_checked", "wrong_contract"):
        for a in parent["plan"]["arms"]:
            if damage == "already_checked": a["identifier_check"] = True
            else: a["contract"] = "json"
        parent["plan_id"] = content_hash(parent["plan"])
    with pytest.raises(ValueError): attention_study(parent, seed=seed)


def test_previous_binding_hashes_remain_valid_when_check_disabled():
    arm = Arm("old", contract="json_tactic")
    old = asdict(arm); old.pop("identifier_check")
    messages = [{"role": "user", "content": "unchanged"}]
    assert request_binding(messages, arm) == content_hash({"messages": messages, "arm": old})
    assert request_binding(messages, arm) != request_binding(messages, replace(arm, identifier_check=True))


def test_prior_report_without_new_field_still_audits(parent):
    expected = development_digest(parent)
    for a in parent["plan"]["arms"]: a.pop("identifier_check")
    parent["plan_id"] = content_hash(parent["plan"])
    # Plan identities change in this fixture, but all old bindings/prompts remain valid.
    result = development_digest(parent)
    assert result["observations"] == expected["observations"]


def test_one_edit_is_failure_not_fuzzy_acceptance(parent, tmp_path):
    report = run_study(parent, tmp_path / "run", lambda c, a: c.expected[:-1] if a.identifier_check else c.expected)
    summary = attention_report(report)
    assert summary["complete"] and summary["same_output_contract"]
    assert summary["paired_confirmation"] == {"control_only_success": 12}
    own = [g for g in summary["groups"] if g["arm"] == "identifier-check"]
    assert all(g["strict_successes"] == 0 and g["envelope_compliant"] == 12 for g in own)
    assert all(g["diagnostics"] == {"unknown_identifier_one_edit_from_target": 12} for g in own)
    assert not summary["promotion"] and not summary["native_quality_established"]
    assert "independent theorems" in markdown_results(summary)


def test_diagnostics_distinguish_wrong_type_from_unknown_and_other_tactic():
    c = attention_cases(seed=137)[0]
    wrong = next(h["name"] for h in probe_data(c)["locals"] if h["type"] == "Nat")
    for tactic, expected in ((c.expected, "exact_oracle"), (None, "unparsed"),
            ("exact " + wrong, "wrong_hypothesis_type"), ("exact x", "unknown_identifier"),
            ("assumption", "other_tactic"), (c.expected + "a", "unknown_identifier_one_edit_from_target")):
        assert tactic_diagnostic(c, tactic) == expected


@pytest.mark.parametrize("damage", ["raw", "prompt", "binding", "duplicate", "contract", "seed", "split", "repetition"])
def test_audit_rejects_inconsistent_receipts(parent, tmp_path, damage):
    report = run_study(parent, tmp_path / "run")
    row = report["rows"][0]
    if damage == "raw": row["response"] += " "
    elif damage == "prompt":
        row["messages"][0]["content"] += " secretly alter instruction"
        row["prompt_sha256"] = content_hash(row["messages"])
    elif damage == "binding": row["metadata"]["client_binding"]["request_sha256"] = "0" * 64
    elif damage == "duplicate": report["rows"].append(deepcopy(row))
    elif damage == "split": row["split"] = "madeup"
    elif damage == "repetition": row["repetition"] = True
    else:
        if damage == "contract": report["plan"]["arms"][1]["contract"] = "json"
        else: report["plan"]["seed"] += 1
        report["plan_id"] = content_hash(report["plan"])
    with pytest.raises(ValueError): attention_report(report)


def test_saved_rewards_and_nomination_ignored(parent, tmp_path):
    report = run_study(parent, tmp_path / "run")
    expected = attention_report(report)
    for r in report["rows"]: r.update(success=False, normalized_success=False)
    report["nomination"] = report["groups"] = "forged"
    assert attention_report(report) == expected


def test_missing_response_is_unknown_not_a_success(parent, tmp_path):
    report = run_study(parent, tmp_path / "run")
    report["rows"][0].pop("response")
    summary = attention_report(report)
    assert not summary["complete"] and not summary["paired_confirmation"]
    assert sum(g["unmeasured"] for g in summary["groups"]) == 1


def test_new_instruction_cannot_leak_into_arena():
    arm = Arm("check", identifier_check=True)
    with pytest.raises(ValueError, match="not an Arena"):
        proposal_from_policy(arena_case(RECORD), arm, generator=lambda *_: pytest.fail("no call"))
    with pytest.raises(ValueError): Arm("bad", identifier_check=1)


def test_cli_generates_report_and_markdown_without_calls_or_overwrite(parent, tmp_path, capsys):
    report = run_study(parent, tmp_path / "run")
    src = tmp_path / "source.json"; src.write_text(json.dumps(report))
    out, md = tmp_path / "summary.json", tmp_path / "results.md"
    args = ["--report", str(src), "--output", str(out), "--markdown", str(md)]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["model_calls"] == 0
    assert json.loads(out.read_text())["complete"] and "Strict successes" in md.read_text()
    before = out.read_bytes(), md.read_bytes()
    with pytest.raises(FileExistsError): main(args)
    assert (out.read_bytes(), md.read_bytes()) == before
