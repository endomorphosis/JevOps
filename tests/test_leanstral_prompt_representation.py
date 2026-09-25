"""Same-contract format experiments; all generated responses here are fixtures."""
import json

import pytest

from jevops.arena import content_hash
from jevops.leanstral_context_profile import probe_data, render_probe
from jevops.leanstral_prompt_attention import (CONTEXT_REPORT_SCHEMA, attention_report, attention_study,
    main, markdown_results)
from jevops.leanstral_prompt_feedback import lab_from_study
from jevops.leanstral_prompt_lab import render
from tests.test_leanstral_prompt_attention import generator, parent


def make_study(parent):
    return attention_study(parent, seed=173, experiment="context-format")


@pytest.fixture
def report(parent, tmp_path):
    study = make_study(parent)
    lab = lab_from_study(tmp_path / "representation", study)
    base_generator = generator(lab.cases, lab.arms)
    def generate(messages, arm):
        raw = base_generator(messages, arm)
        raw["usage"] = {"prompt_tokens": 100 if arm.probe_representation == "lean_goal" else 150,
                        "completion_tokens": 20}
        return raw
    return lab_from_study(lab.directory, study, generator=generate).run()


def test_single_factor_preserves_instruction_oracle_and_all_facts(parent, tmp_path):
    study = make_study(parent)
    a, b = study["arms"]
    assert {k for k in a if a[k] != b[k]} == {"name", "probe_representation"}
    assert a["contract"] == b["contract"] == "json_tactic"
    assert not a["identifier_check"] and not b["identifier_check"]
    assert study["limits"]["max_calls"] == 48 and study["limits"]["max_native_requests"] == 0
    lab = lab_from_study(tmp_path / "preview", study)
    assert not lab.directory.exists()
    assert len({c.expected for c in lab.cases}) == 12
    for case in lab.cases:
        lean_messages, lean_id = render(case, lab.arms[0])
        json_messages, json_id = render(case, lab.arms[1])
        assert lean_id == json_id and lean_messages[0] == json_messages[0]  # system instruction identical
        data = probe_data(case)
        structured = json.loads(render_probe(case, "json_locals"))
        text = render_probe(case, "lean_goal")
        assert structured == {"goal": data["goal"], "propositions": [data["goal"]], "locals": data["locals"]}
        assert text.splitlines()[1:-1] == [f"{h['name']} : {h['type']}" for h in data["locals"]]
        assert case.expected not in json.dumps(lean_messages) and case.expected not in json.dumps(json_messages)
        assert "position" not in structured and "distractors" not in structured


def test_selection_does_not_consume_confirmation_or_saved_rewards(parent):
    expected = make_study(parent)
    for row in parent["rows"]:
        if row["split"] == "confirmation":
            row.update(response="private holdout", split="development", metadata=None)
        else:
            row["success"] = False
    parent["nomination"] = parent["groups"] = "untrusted"
    assert make_study(parent) == expected
    with pytest.raises(ValueError, match="fresh seed"):
        attention_study(parent, seed=101, experiment="context-format")


def test_report_preserves_common_score_and_reports_paired_token_cost(report):
    result = attention_report(report, experiment="context-format")
    assert result["schema"] == CONTEXT_REPORT_SCHEMA and result["complete"]
    assert result["same_output_contract"] and result["evidence_mode"] == "offline_fixture"
    assert result["paired_confirmation"] == {"tie": 12}
    assert all(g["strict_successes"] == g["envelope_compliant"] == 12 for g in result["groups"])
    assert len(result["token_cost_contrasts"]) == 8
    assert all(c["expected_pairs"] == c["measured_pairs"] == 6 for c in result["token_cost_contrasts"])
    assert all(c["median_json_minus_lean"] == (50 if c["metric"] == "prompt_tokens" else 0)
               for c in result["token_cost_contrasts"])
    assert "same-contract context-format" in markdown_results(result)
    assert not result["promotion"] and not result["native_quality_established"]
    for row in report["rows"]:
        row.update(success=False, normalized_success=False)
    report["groups"] = report["nomination"] = "forged"
    assert attention_report(report, experiment="context-format") == result


@pytest.mark.parametrize("damage", ["temperature", "contract", "identifier_check", "contract_example", "reverse"])
def test_compound_interventions_rejected_even_with_new_plan_hash(report, damage):
    b = report["plan"]["arms"][1]
    if damage == "reverse": report["plan"]["arms"].reverse()
    elif damage == "temperature": b[damage] = 1
    elif damage == "contract": b[damage] = "json"
    else: b[damage] = not b[damage]
    report["plan_id"] = content_hash(report["plan"])
    with pytest.raises(ValueError): attention_report(report, experiment="context-format")


def test_auditors_cannot_silently_reinterpret_another_experiment(report, parent, tmp_path):
    with pytest.raises(ValueError): attention_report(report)
    study = attention_study(parent, seed=179)
    lab = lab_from_study(tmp_path / "old-design", study)
    old = lab_from_study(lab.directory, study, generator=generator(lab.cases, lab.arms)).run()
    assert attention_report(old)["complete"]
    with pytest.raises(ValueError): attention_report(old, experiment="context-format")


def test_unknown_experiment_rejected_without_calls(parent):
    with pytest.raises(ValueError): attention_study(parent, seed=173, experiment="auto-best")
    with pytest.raises(ValueError): attention_report({}, experiment="auto-best")


def test_missing_telemetry_is_not_zero_cost(report):
    for row in report["rows"]: row["metadata"].pop("usage")
    result = attention_report(report, experiment="context-format")
    assert result["complete"]  # Outcome known, token costs not known.
    assert all(c["measured_pairs"] == 0 and c["median_json_minus_lean"] is None
               for c in result["token_cost_contrasts"])


def test_missing_response_is_unknown_and_missing_pair_cannot_win(report):
    report["rows"][0].pop("response")
    result = attention_report(report, experiment="context-format")
    assert not result["complete"] and result["paired_confirmation"] == {}
    assert sum(g["unmeasured"] for g in result["groups"]) == 1


def test_cli_requires_explicit_experiment_and_refuses_overwrite(report, tmp_path, capsys):
    source = tmp_path / "report.json"; source.write_text(json.dumps(report))
    out, md = tmp_path / "summary.json", tmp_path / "results.md"
    args = ["--report", str(source), "--experiment", "context-format", "--output", str(out), "--markdown", str(md)]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["model_calls"] == 0
    assert json.loads(out.read_text())["schema"] == CONTEXT_REPORT_SCHEMA
    assert "same-contract context-format" in md.read_text()
    before = out.read_bytes(), md.read_bytes()
    with pytest.raises(FileExistsError): main(args)
    assert (out.read_bytes(), md.read_bytes()) == before
