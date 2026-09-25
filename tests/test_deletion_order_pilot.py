"""Presentation permutations must not change the admitted Lean action space."""
from collections import Counter
import json
from pathlib import Path

import pytest

from tests.test_prompt_template_pilot import pilot


def unpack(request):
    system, user = request["messages"]
    assert system["role"] == "system" and user["role"] == "user"
    head, rest = user["content"].split("<context>\n", 1)
    context, tail = rest.split("\n</context>", 1)
    reference, edit = context.rsplit("\n", 1)
    return system["content"], head, reference, json.loads(edit), tail


def test_order_plan_is_paired_balanced_and_preserves_all_problem_data(pilot):
    plan, original = pilot.make_deletion_order_plan(), pilot.make_local_edit_plan()
    assert plan == pilot.make_deletion_order_plan()
    assert [slot["slot"] for slot in plan["schedule"]] == list(range(8))
    assert Counter(slot["arm"] for slot in plan["schedule"]) == {name: 2 for name in plan["arms"]}
    assert plan["record"] == original["record"] and plan["settings"] == original["settings"]
    assert plan["native_protocol"] == original["native_protocol"]
    assert plan["max_model_calls"] == 8 and plan["max_output_tokens_total"] == 8192
    expected_reference, expected_edit = original["case"]["context"].rsplit("\n", 1)
    for repetition in range(2):
        baseline = original["arms"]["delete-span"]["requests"][repetition]
        instruction, contract = baseline["messages"][0]["content"].rsplit("\n", 1)
        sizes = set()
        for treatment in plan["arms"].values():
            assert treatment["action"] == "delete-span"
            request = treatment["requests"][repetition]
            system, head, reference, edit, tail = unpack(request)
            assert request["request_id"] == baseline["request_id"]
            assert system == instruction and reference == expected_reference
            ordered = json.loads(expected_edit)
            if treatment["span_order"] == "reverse":
                ordered["allowed_delete_lines_inclusive"].reverse()
            assert edit == ordered  # Includes every unchanged numbered proof line.
            assert {tuple(s) for s in edit["allowed_delete_lines_inclusive"]} == set(plan["allowed_delete_lines_inclusive"])
            assert request["messages"][1]["content"].count(contract) == 1
            if treatment["contract_position"] == "before":
                assert head.startswith(contract + "\n") and tail == ""
            else:
                assert head == "Request: " + request["request_id"] + "\n" and tail == "\n" + contract
            sizes.add(sum(len(m["content"]) for m in request["messages"]))
        assert len(sizes) == 1


def test_old_local_edit_requests_are_byte_identical(pilot):
    archive = Path(pilot.ROOT) / "papers/completion/lean_refactor_arena/evidence/prompt-local-edits-2026-09-23/plan.json"
    old, current = json.loads(archive.read_text()), pilot.make_local_edit_plan()
    for name in old["arms"]:
        assert old["arms"][name]["requests"] == current["arms"][name]["requests"]


def test_order_run_reuses_strict_checker_and_reservations(pilot, monkeypatch, tmp_path):
    plan = pilot.make_deletion_order_plan()
    monkeypatch.setattr(pilot, "validate_volume", lambda _: tmp_path)
    monkeypatch.setattr(pilot.leanstral, "server_profile", lambda: {"declared_context_per_slot": 8192})
    monkeypatch.setattr(pilot.leanstral, "health_status", lambda _: (200, ""))
    calls = []
    def generate(prompt, **kwargs):
        import re
        assert prompt is None
        calls.append(kwargs["messages"])
        request_id = re.search(r"Request: ([0-9a-f]{16})", kwargs["messages"][1]["content"])[1]
        return json.dumps({"request_id": request_id, "delete_lines": plan["allowed_delete_lines_inclusive"][0]})
    monkeypatch.setattr(pilot.llm_router, "generate_text", generate)
    monkeypatch.setattr(pilot.llm_router, "get_last_generation_trace", lambda: {
        "fixture": False, "fallback_used": False, "response_model": "leanstral_local",
        "endpoint": pilot.leanstral.endpoint(pilot.leanstral.BASE_URL), "finish_reason": "stop"})
    pilot.run(tmp_path, {}, plan)
    pilot.run(tmp_path, {}, plan)
    report = json.loads((tmp_path / "generation.json").read_text())
    assert len(calls) == report["requests_reserved"] == 8
    assert report["native_executions"] == 0
    assert len(report["candidate_files"]) == 1
    assert all(r["status"] == "parsed" and r["native_verified"] is None for r in report["rows"])


@pytest.mark.parametrize("study", ["deletion-order", "deletion-ids"])
def test_live_order_study_requires_snapshot_before_network(pilot, monkeypatch, tmp_path, study):
    monkeypatch.setattr(pilot.sys, "argv", ["pilot", "--study", study, "--generate",
        "--preparation-root", str(tmp_path), "--output", str(tmp_path / "run")])
    monkeypatch.setattr(pilot.leanstral, "server_profile", lambda: pytest.fail("no network without snapshot"))
    with pytest.raises(SystemExit) as exc:
        pilot.main()
    assert exc.value.code == 2
