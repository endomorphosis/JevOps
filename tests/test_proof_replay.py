from __future__ import annotations

import copy
from functools import partial
import hashlib
from pathlib import Path
import shutil

import pytest

from jevops.proof_state import capture_source
from jevops import proof_replay as replay
from jevops.router_tuning import _lean_compiler

ENV = "a" * 64
SOURCE = "theorem replay_demo (p : Prop) (h : p) : p := by\n  exact id h\n"


@pytest.fixture(scope="module")
def captured(tmp_path_factory):
    if shutil.which("lean") is None:
        pytest.skip("requires Lean")
    project = tmp_path_factory.mktemp("replay")
    capture = capture_source(SOURCE, project_root=project, environment_sha256=ENV)
    assert capture["ok"], capture
    proposal = replay.closing_proposals(SOURCE, capture, candidates=("assumption",), limit=1)[0]
    return project, capture, proposal["event_id"]


@pytest.mark.parametrize("candidate,status", [("assumption", "closed_kernel_checked"),
    ("skip", "open_goals"), ("rfl", "rejected"), ("sorry", "rejected"),
    ("run_tac Lean.Elab.Tactic.setGoals []", "rejected"),
    ("run_tac (← Lean.Elab.Tactic.getMainGoal).assign (Lean.mkConst ``True.intro)", "rejected")])
def test_native_replay_does_not_confuse_empty_goal_list_with_valid_proof(captured, candidate, status):
    project, capture, event = captured
    before = copy.deepcopy(capture)
    result = replay.replay_candidate(SOURCE, capture, event, candidate, project_root=project, environment_sha256=ENV)
    assert result["ok"], result
    assert result["native"]["baseline"]["status"] == "closed_kernel_checked"
    assert result["native"]["proposed"]["status"] == status
    assert result["closing_reproduced"] == (status == "closed_kernel_checked")
    assert not result["proof_admitted"] and not result["whole_source_checked"]
    assert capture == before


def test_native_unknown_tactic_has_no_positive_receipt(captured):
    project, capture, event = captured
    result = replay.replay_candidate(SOURCE, capture, event, "not_a_tactic", project_root=project, environment_sha256=ENV)
    assert not result["ok"] and not result["closing_reproduced"]


@pytest.mark.parametrize("damage", ["source", "trace", "exporter", "environment", "event", "bool_event", "bytes"])
def test_stale_context_and_request_fail_before_native_execution(captured, monkeypatch, damage):
    project, c, event = captured
    c = copy.deepcopy(c)
    source, candidate = SOURCE, "assumption"
    if damage == "source":
        source += "\n"
    elif damage == "trace":
        c["trace"]["events"].pop()
    elif damage == "exporter":
        c["exporter_sha256"] = "0" * 64
    elif damage == "environment":
        c["dependency_environment_sha256"] = "b" * 64
    elif damage == "event":
        event = -1
    elif damage == "bool_event":
        event = True
    else:
        candidate = "x" * 4097
    def forbidden(*a, **k):
        pytest.fail("invalid request reached native executor")
    monkeypatch.setattr(replay.ps, "_run_bounded", forbidden)
    with pytest.raises(ValueError):
        replay.replay_candidate(source, c, event, candidate, project_root=project, environment_sha256=ENV)


def test_forged_native_anchor_does_not_match_regenerated_context(captured):
    project, capture, event = captured
    forged = copy.deepcopy(capture)
    forged["trace"]["events"][event]["namespace"] = [["s", "fake"]]
    forged["trace_sha256"] = replay.digest(forged["trace"])
    result = replay.replay_candidate(SOURCE, forged, event, "assumption", project_root=project, environment_sha256=ENV)
    assert not result["ok"] and "anchor" in result["reason"]


def test_replacement_never_edits_theorem_envelope(captured):
    _, capture, event = captured
    target = replay.replace_event(SOURCE, capture["trace"]["events"][event], "assumption")
    assert target == SOURCE.replace("exact id h", "assumption")
    fake = {**capture["trace"]["events"][event], "start": "0"}
    with pytest.raises(ValueError):
        replay.replace_event(SOURCE, fake, "assumption")
    assert len(replay.closing_proposals(SOURCE, capture, candidates=("assumption", "assumption"))) == 1


def test_native_shorter_replay_is_whole_source_checked_before_becoming_teacher(captured):
    project, capture, event = captured
    calls = []
    compiler = _lean_compiler(project_root=project, kernel_only=True, export_dags=True, environment_sha256=ENV)
    def compile_one(source):
        calls.append(source)
        return compiler(source)
    class Evaluation(dict):
        def __getitem__(self, key):
            assert key not in ("source", "target"), "evaluation data leaked"
            return super().__getitem__(key)
    rows = [{"id": "train", "split": "train", "source": SOURCE},
            *[Evaluation(id=s, split=s) for s in ("validation", "canary", "holdout")]]
    result = replay.collect_replay_pairs(rows, capture_fn=lambda _: capture,
        replay_fn=partial(replay.replay_candidate, project_root=project, environment_sha256=ENV),
        compile_fn=compile_one, environment_sha256=ENV,
        proposal_fn=lambda s, c: [{"event_id": event, "candidate": "rfl"},
                                  {"event_id": event, "candidate": "assumption"}])
    assert result["ok"] and result["compile_calls"] == 2, result
    assert len(result["pairs"]) == 1 and len(calls) == 2
    pair = result["pairs"][0]
    assert pair["teacher_admitted"] and pair["expression_nonregression"]
    assert pair["source_tokens"] > pair["target_tokens"]
    assert pair["target_text"] == SOURCE.replace("exact id h", "assumption")
    assert [a["status"] for a in result["attempts"]] == ["rejected", "admitted_candidate"]
    assert result["excluded_ids"] == ["validation", "canary", "holdout"]
    assert not result["model_trained"] and result["official_score"] is None


def test_local_replay_success_cannot_override_whole_source_failure(captured):
    project, capture, event = captured
    result = replay.collect_replay_pairs([{"id": "train", "split": "train", "source": SOURCE}],
        capture_fn=lambda _: capture,
        replay_fn=partial(replay.replay_candidate, project_root=project, environment_sha256=ENV),
        compile_fn=lambda _: {"theorem_ok": False}, environment_sha256=ENV,
        proposal_fn=lambda s, c: [{"event_id": event, "candidate": "assumption"}])
    assert not result["ok"] and not result["pairs"]
    assert result["attempts"][0]["replay"]["closing_reproduced"]
    assert "whole-source" in result["attempts"][0]["reason"]


def test_native_crlf_and_unicode_source_offsets_are_preserved(captured):
    project, _, _ = captured
    source = ("-- λ\n" + SOURCE).replace("\n", "\r\n")
    capture = capture_source(source, project_root=project, environment_sha256=ENV)
    assert capture["ok"] and not capture["trace"]["elaboration_errors"], capture
    exact = [e for e in capture["trace"]["events"] if e["start"] is not None and
             source.encode()[int(e["start"]):int(e["end"])].decode() == "exact id h"]
    assert exact
    result = replay.replay_candidate(source, capture, int(exact[-1]["id"]), "assumption",
                                     project_root=project, environment_sha256=ENV)
    assert result["closing_reproduced"], result
    assert capture["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()


def test_native_shared_unresolved_witness_abstains(captured):
    project, _, _ = captured
    source = "theorem coupled : 2 ≤ 5 := by\n  apply Nat.le_trans\n  · exact Nat.le_refl 2\n  · decide\n"
    capture = capture_source(source, project_root=project, environment_sha256=ENV)
    assert capture["ok"] and not capture["trace"]["elaboration_errors"]
    events = [e for e in capture["trace"]["events"] if e["status"] == "captured" and e["start"] is not None
              and source.encode()[int(e["start"]):int(e["end"])] == b"exact Nat.le_refl 2"]
    assert events
    result = replay.replay_candidate(source, capture, int(events[-1]["id"]), "rfl",
                                     project_root=project, environment_sha256=ENV)
    assert result["ok"] and not result["closing_reproduced"], result
    assert result["native"]["baseline"]["status"] == "rejected"
    assert "open local telescope" in result["native"]["baseline"]["reason"]


def test_native_sorry_baseline_cannot_create_closing_label(captured):
    project, _, _ = captured
    source = SOURCE.replace("exact id h", "sorry")
    capture = capture_source(source, project_root=project, environment_sha256=ENV)
    assert capture["ok"]
    event = next(e for e in reversed(capture["trace"]["events"]) if e["status"] == "captured")
    result = replay.replay_candidate(source, capture, int(event["id"]), "assumption",
                                     project_root=project, environment_sha256=ENV)
    assert result["ok"] and not result["closing_reproduced"], result
    assert result["native"]["baseline"]["status"] == "rejected"
    assert result["native"]["proposed"]["status"] == "closed_kernel_checked"


def test_tactic_cannot_hide_an_axiom_by_replacing_the_elaborator_environment(captured):
    project, _, _ = captured
    source = "import Lean\naxiom replayBad : True\ntheorem probe : True := by\n  exact True.intro\n"
    capture = capture_source(source, project_root=project, environment_sha256=ENV)
    event = next(e for e in reversed(capture["trace"]["events"]) if e["status"] == "captured")
    candidate = ("run_tac do\n"
                 "  (← Lean.Elab.Tactic.getMainGoal).assign (Lean.mkConst `replayBad)\n"
                 "  Lean.Elab.Tactic.setGoals []\n"
                 "  Lean.setEnv (← Lean.importModules #[{module := `Lean}] {})")
    result = replay.replay_candidate(source, capture, int(event["id"]), candidate,
                                     project_root=project, environment_sha256=ENV)
    assert result["ok"] and not result["closing_reproduced"], result
    assert result["native"]["baseline"]["status"] == "closed_kernel_checked"
    assert result["native"]["proposed"]["status"] == "rejected"
    assert "forbidden axioms" in result["native"]["proposed"]["reason"]


def test_opaque_have_survives_cleared_origin_and_replay_generalizes_it(captured):
    project, _, _ = captured
    source = "theorem opaque_have (n : Nat) (hn : n = n) : n = n := by\n  have h := hn\n  clear hn\n  exact h\n"
    capture = capture_source(source, project_root=project, environment_sha256=ENV)
    assert capture["ok"], capture
    assert not capture["trace"]["elaboration_errors"]
    event = next(e for e in capture["trace"]["events"] if e["start"] is not None and
        source.encode()[int(e["start"]):int(e["end"])] == b"exact h")
    assert event["status"] == "captured", event
    locals_ = event["before"]["metavariables"][0]["locals"]
    assert any(d["name"] == [["s", "h"]] and d["nondep"] and d["value"] is None for d in locals_)
    assert all(d["name"] != [["s", "hn"]] for d in locals_)
    outcome = replay.replay_candidate(source, capture, int(event["id"]), "assumption",
                                      project_root=project, environment_sha256=ENV)
    assert outcome["closing_reproduced"], outcome
    assert not outcome["proof_admitted"] and not outcome["whole_source_checked"]
