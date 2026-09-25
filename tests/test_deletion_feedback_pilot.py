"""Historical rejection hints must not become proof authority or neural pruning."""
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path

import pytest

from tests.test_prompt_template_pilot import pilot
from tests.test_deletion_order_pilot import unpack

ARCHIVE = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/evidence/prompt-deletion-ids-2026-09-23"


def inputs():
    return [json.loads((ARCHIVE / name).read_text()) for name in ("plan.json", "native-plan.json", "native-triage.json")]


def history_digest():
    return hashlib.sha256((ARCHIVE / "archive-manifest.json").read_bytes()).hexdigest()


def test_bound_rejections_reuse_history_checker_and_deduplicate(pilot):
    plan, native_plan, native = inputs()
    feedback = pilot.deletion_rejection_feedback(plan["record"], plan, native_plan, native)
    assert [r["edit_ids"] for r in feedback["observations"]] == [[1], [64]]
    assert all(r["outcome_reported"] == "REJECTED" and r["version"]["lean_tag"] == "v4.26.0"
               for r in feedback["observations"])
    assert not feedback["history_authenticated"] and not feedback["prune_actions"]
    assert feedback["fresh_verification_required"]
    assert all(len(r["context_id"]) == len(r["request_id"]) == len(r["dependency_digest"]) == 64
               for r in feedback["observations"])
    native["rows"] *= 2
    assert pilot.deletion_rejection_feedback(plan["record"], plan, native_plan, native) == feedback


@pytest.mark.parametrize("damage", ["record", "plan", "catalog", "target", "source", "request", "context", "pin",
    "measurement", "dependency", "report_outcome", "diagnostic", "duplicate_nested_json", "unrun_receipt", "review"])
def test_mismatched_history_is_rejected(pilot, damage):
    plan, native_plan, native = inputs()
    record = copy.deepcopy(plan["record"])
    row = next(r for r in native["rows"] if r["status"] == "REJECTED")
    receipt = row["receipt"]
    observation = json.loads(receipt["observations_json"])
    if damage == "record": record["src"] += "\n"
    elif damage == "plan": plan["seed"] += 1
    elif damage == "catalog": plan["catalog_sha256"] = "0" * 64
    elif damage == "target": receipt["target"] = "wrong"
    elif damage == "source": receipt["candidate_sha256"] = "0" * 64
    elif damage == "request": receipt["request_id"] = "0" * 64
    elif damage == "context": row["context_id"] = "0" * 64
    elif damage == "pin": row["pin"]["git_commit"] = "f" * 40
    elif damage == "duplicate_nested_json": receipt["observations_json"] = '{"report":{},"report":{}}'
    elif damage == "unrun_receipt": row["status"] = "NOT_RUN_AFTER_NON_SUCCESS"
    elif damage == "review": native_plan["reviewed_source_sha256"] = []
    else:
        if damage == "measurement": observation["measurement"] = "unmatched"
        elif damage == "dependency": observation["dependency_digest"] = "0" * 64
        elif damage == "report_outcome": observation["report"]["outcome"] = "VERIFIED"
        elif damage == "diagnostic": observation["report"]["diagnostics"] = [{"message": 42}]
        receipt["observations_json"] = json.dumps(observation)
    with pytest.raises(ValueError):
        pilot.deletion_rejection_feedback(record, plan, native_plan, native)


@pytest.mark.parametrize("status", ["ERROR", "TIMEOUT", "UNAVAILABLE", "BUDGET_EXHAUSTED"])
def test_infrastructure_failure_is_not_a_negative_training_label(pilot, status):
    plan, native_plan, native = inputs()
    row = next(r for r in native["rows"] if r["status"] == "REJECTED")
    row["status"] = row["receipt"]["outcome"] = status
    row["receipt"]["observations_json"] = "{}"
    feedback = pilot.deletion_rejection_feedback(plan["record"], plan, native_plan, native)
    assert len(feedback["observations"]) == 1
    assert all(r["candidate_sha256"] != row["source_sha256"] for r in feedback["observations"])


def test_explicit_archive_hashes_and_byte_limits_precede_use(pilot, tmp_path, monkeypatch):
    plan = inputs()[0]
    feedback, binding = pilot.load_deletion_feedback(plan["record"], ARCHIVE, history_digest())
    assert len(feedback["observations"]) == 2 and len(binding["files"]) == 3
    with pytest.raises(ValueError, match="manifest identity"):
        pilot.load_deletion_feedback(plan["record"], ARCHIVE, "0" * 64)
    for name in ("archive-manifest.json", "plan.json", "native-plan.json", "native-triage.json"):
        (tmp_path / name).write_bytes((ARCHIVE / name).read_bytes())
    (tmp_path / "native-triage.json").write_text("{}")
    with pytest.raises(ValueError, match="artifact identity"):
        pilot.load_deletion_feedback(plan["record"], tmp_path, history_digest())
    from jevops import refactor_prompts
    monkeypatch.setattr(refactor_prompts, "MAX_FILE_BYTES", 16)
    with pytest.raises(ValueError, match="byte limit"):
        pilot.load_deletion_feedback(plan["record"], ARCHIVE, history_digest())


def test_matched_plan_changes_only_feedback_and_display_order(pilot):
    plan = pilot.make_deletion_feedback_plan(ARCHIVE, history_digest())
    assert plan == pilot.make_deletion_feedback_plan(ARCHIVE, history_digest())
    assert [r["slot"] for r in plan["schedule"]] == list(range(8))
    assert Counter(r["arm"] for r in plan["schedule"]) == {name: 2 for name in plan["arms"]}
    assert plan["max_model_calls"] == 8 and plan["max_output_tokens_total"] == 8192
    for repetition in range(2):
        requests = [a["requests"][repetition] for a in plan["arms"].values()]
        assert len({r["request_id"] for r in requests}) == 1
        for order in ("forward", "reverse"):
            control, treatment = [plan["arms"][prefix + order]["requests"][repetition]
                                  for prefix in ("no-feedback-", "feedback-")]
            c_system, c_head, c_ref, c_data, c_tail = unpack(control)
            t_system, t_head, t_ref, t_data, t_tail = unpack(treatment)
            assert (c_system, c_head, c_ref, c_tail) == (t_system, t_head, t_ref, t_tail)
            assert len(c_data["historical_rejections"]["observations"]) == 0
            assert len(t_data["historical_rejections"]["observations"]) == 2
            t_data["historical_rejections"]["observations"] = []
            assert c_data == t_data
            entries = c_data["edit_catalog"]["entries"]
            assert {e["edit_id"] for e in entries} == set(range(1, 65))
            assert entries == (plan["edit_catalog"]["entries"] if order == "forward" else
                               list(reversed(plan["edit_catalog"]["entries"])))


def test_old_id_requests_remain_unchanged(pilot):
    old, current = inputs()[0], pilot.make_deletion_id_plan()
    for name in old["arms"]:
        assert old["arms"][name]["requests"] == current["arms"][name]["requests"]


def test_rejected_ids_are_still_admissible_and_never_counted_as_proof(pilot, monkeypatch, tmp_path):
    import re
    plan = pilot.make_deletion_feedback_plan(ARCHIVE, history_digest())
    monkeypatch.setattr(pilot, "validate_volume", lambda _: tmp_path)
    monkeypatch.setattr(pilot.leanstral, "server_profile", lambda: {"declared_context_per_slot": 8192})
    monkeypatch.setattr(pilot.leanstral, "health_status", lambda _: (200, ""))
    calls = []
    def generate(prompt, **kwargs):
        assert prompt is None
        calls.append(kwargs["messages"])
        request_id = re.search(r"Request: ([0-9a-f]{16})", kwargs["messages"][1]["content"])[1]
        return json.dumps({"request_id": request_id, "edit_id": 1})
    monkeypatch.setattr(pilot.llm_router, "generate_text", generate)
    monkeypatch.setattr(pilot.llm_router, "get_last_generation_trace", lambda: {
        "fixture": False, "fallback_used": False, "response_model": "leanstral_local",
        "endpoint": pilot.leanstral.endpoint(pilot.leanstral.BASE_URL), "finish_reason": "stop"})
    pilot.run(tmp_path, {}, plan)
    pilot.run(tmp_path, {}, plan)
    result = json.loads((tmp_path / "generation.json").read_text())
    assert len(calls) == 8 and result["native_executions"] == 0 and len(result["candidate_files"]) == 1
    assert all(r["native_verified"] is None and r["status"] == "parsed" for r in result["rows"])


def test_feedback_cli_requires_explicit_history_and_snapshot(pilot, monkeypatch, tmp_path):
    args = ["pilot", "--study", "deletion-feedback", "--generate", "--preparation-root", str(tmp_path),
            "--output", str(tmp_path / "run")]
    monkeypatch.setattr(pilot.leanstral, "server_profile", lambda: pytest.fail("no network"))
    for extra in ([], ["--feedback-history", str(ARCHIVE), "--feedback-manifest-sha256", history_digest()]):
        monkeypatch.setattr(pilot.sys, "argv", args + extra)
        with pytest.raises(SystemExit) as exc:
            pilot.main()
        assert exc.value.code == 2
