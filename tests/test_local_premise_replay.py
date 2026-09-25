"""Offline protocol fixtures, plus explicitly opt-in native replay/admission."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import partial
import json
import os
from pathlib import Path
import sys

import pytest

from jevops import arena_providers as providers, proof_replay as replay, proof_state as ps
from jevops.arena import content_hash, source_hash
from jevops.arena_trial import Candidate
from jevops.premise_search import Premise, PremiseIndex, PremiseScope
from jevops.scoped_proposals import premise_query

ENV = "a" * 64
STATEMENT = "theorem local_pair : True ∧ True"
BLOCK = "have first : True := True.intro\n    have second : True := first\n    exact second"
SOURCE = STATEMENT + " := by\n  constructor\n  · " + BLOCK + "\n  · exact True.intro\n"
RECORD = {"name": "Suite.local_pair", "statement": STATEMENT, "src": SOURCE,
          "version_info": [{"v4.26.0": "offline-fixture"}]}


def name(value):
    return [["s", part] for part in value.split(".")]


def state():
    # A structural observation fixture, not a native proof receipt.
    return {"schema": ps.STATE_SCHEMA, "goals": [name("goal")],
        "expressions": [["const", name("True"), []]],
        "levels": [], "universe_metavariables": [], "depth": "0", "level_assign_depth": "0",
        "metavariables": [{"id": name("goal"), "name": [], "type": "0", "locals": [],
            "instances": [], "assignment": None, "kind": "natural", "depth": "0",
            "index": "0", "scope_args": "0"}]}


def capture_fixture(source=SOURCE):
    before = state()
    after = {**state(), "goals": [], "metavariables": [], "expressions": []}
    binding = {"source_sha256": source_hash(source), "dependency_environment_sha256": ENV,
        "exporter_sha256": source_hash(ps.EXPORTER.read_text()), "node_budget": 64, "event_budget": 8}
    environment = replay.digest(binding)
    start = source.encode().index(BLOCK.encode())
    event = {"id": "0", "parent": None, "declaration": name("local_pair"), "namespace": [],
        "syntax_kind": name("Lean.Parser.Tactic.tacticSeq"), "start": str(start),
        "end": str(start + len(BLOCK.encode())), "status": "captured", "before": before, "after": after}
    trace = {"schema": ps.TRACE_SCHEMA, "environment": environment, "lean_version": "offline-fixture",
        "lean_githash": "fixture-not-a-native-check", "elaboration_errors": False, "events": [event],
        "proof_admitted": False, "replayable": False}
    return {**binding, "environment": environment, "trace": trace, "trace_sha256": replay.digest(trace),
        "ok": True, "proof_admitted": False, "kernel_typechecked": False, "replayable": False}


def inventory(entries=None, record=RECORD):
    entries = (Premise("True.intro", "True", "fixture-library"),) if entries is None else entries
    return (PremiseIndex(entries, environment_sha256=ENV),
            PremiseScope(content_hash(record), ENV, tuple(p.name for p in entries)))


def batch(capture=None, **kwargs):
    return providers.propose_local_batch(RECORD, capture or capture_fixture(), *inventory(), **kwargs)


def rehash(capture):
    capture["trace_sha256"] = replay.digest(capture["trace"])
    return capture


def test_local_drafts_preserve_other_branch_and_do_not_claim_proof():
    capture = capture_fixture()
    saved = deepcopy(capture)
    result = batch(capture)
    assert result == batch(capture) and capture == saved
    assert result["status"] == "DRAFTS_ONLY" and len(result["drafts"]) == 2
    assert result["events"][0]["observation"]["query"] == "True"
    assert result["events"][0]["observation"]["nodes_visited"] == 1
    assert result["proposals"] == [
        {"event_id": 0, "candidate": "exact _root_.True.intro"},
        {"event_id": 0, "candidate": "apply _root_.True.intro"}]
    for draft, proposal in zip(result["drafts"], result["proposals"]):
        assert draft["source"] == SOURCE.replace(BLOCK, proposal["candidate"])
        assert draft["source"].endswith("\n  · exact True.intro\n")
        assert set(draft) == {"name", "label", "source", "provenance"}
    assert not any(result[k] for k in ("proof_verified", "proof_admitted", "whole_source_checked",
        "promoted", "training_enabled", "native_verifier_calls", "external_calls_attempted"))
    assert result["fresh_verification_required"] and result["official_score"] is None
    assert result["origins"][0]["premise"]["type_text"] == "True"


@pytest.mark.parametrize("field", ["cap", "max_events", "max_query_nodes"])
def test_zero_never_queries_inventory(field, monkeypatch):
    def forbidden(*a, **kw):
        pytest.fail("exhausted budget queried premises")
    monkeypatch.setattr(PremiseIndex, "rank", forbidden)
    result = batch(**{field: 0})
    assert result["status"] == "BUDGET_EXHAUSTED" and not result["drafts"]


@pytest.mark.parametrize("kwargs", [{"cap": True}, {"cap": -1}, {"top_k": 0},
    {"max_scan": 0}, {"max_events": 65}, {"max_query_nodes": 4097}])
def test_invalid_budgets(kwargs):
    with pytest.raises(ValueError):
        batch(**kwargs)


@pytest.mark.parametrize("damage", ["source", "trace", "environment", "exporter", "forged_flag", "declaration"])
@pytest.mark.parametrize("strategy", providers.LOCAL_STRATEGIES)
def test_foreign_or_forged_captures_reject_before_retrieval(damage, strategy, monkeypatch):
    capture = capture_fixture()
    if damage == "source": capture["source_sha256"] = "b" * 64
    elif damage == "trace": capture["trace"]["events"][0]["end"] = "0"
    elif damage == "environment": capture["dependency_environment_sha256"] = "b" * 64
    elif damage == "exporter": capture["exporter_sha256"] = "b" * 64
    elif damage == "forged_flag": capture["proof_admitted"] = True
    else:
        capture["trace"]["events"][0]["declaration"] = name("other")
        rehash(capture)
    monkeypatch.setattr(PremiseIndex, "rank", lambda *a, **kw: pytest.fail("foreign capture queried premises"))
    with pytest.raises(ValueError):
        batch(capture, strategy=strategy)


def test_record_environment_seed_and_scope_bindings():
    capture = capture_fixture()
    index, scope = inventory()
    with pytest.raises(ValueError, match="record"):
        providers.propose_local_batch({**RECORD, "src": SOURCE + "\n"}, capture, index, scope)
    with pytest.raises(ValueError, match="environment"):
        providers.propose_local_batch(RECORD, capture, index, replace(scope, environment_sha256="b" * 64))
    seed = Candidate("seed", SOURCE + "\n", "unverified")
    with pytest.raises(ValueError, match="capture"):
        providers.propose_local_batch(RECORD, capture, index, scope, seed=seed)
    seeded = providers.propose_local_batch(RECORD, capture_fixture(seed.source), index, scope, seed=seed)
    assert seeded["request"]["request_sha256"] != batch()["request"]["request_sha256"]
    excluded = providers.propose_local_batch(RECORD, capture, index,
        replace(scope, excluded_names=("True.intro",)))
    assert not excluded["drafts"]
    assert excluded["request"]["request_sha256"] != batch()["request"]["request_sha256"]


def test_target_aliases_wrappers_unavailable_and_holdouts_excluded():
    entries = (Premise("True.intro", "True", "library"),
        Premise("local_pair", "True", "library", aliases=("Alias.target",)),
        Premise("Wrapper", "True", "library", dependencies=("Alias.target",)),
        Premise("Suite.local_pair", "True", "library"),
        Premise("Hidden", "True", "library"), Premise("Heldout", "True", "library", split="test"))
    index, scope = inventory(entries)
    scope = replace(scope, available_names=(*scope.available_names[:-2], "Heldout", "Alias.target"))
    result = providers.propose_local_batch(RECORD, capture_fixture(), index, scope, top_k=8)
    assert {o["premise"]["name"] for o in result["origins"]} == {"True.intro"}


def test_query_uses_local_types_but_never_values_or_unrelated_nodes():
    s = state()
    s["expressions"].extend([["const", name("Nat"), []], ["const", name("Secret.proof"), []]])
    s["metavariables"][0]["locals"] = [{"id": name("n"), "name": name("n"), "index": "0",
        "type": "1", "value": "2", "nondep": False, "binder": "explicit", "kind": "default"}]
    result = premise_query(s)
    assert result["query"] == "Nat True" and result["nodes_visited"] == 2
    assert premise_query(s, max_query_nodes=1)["status"] == "QUERY_BUDGET"
    assert premise_query(s, max_query_nodes=1)["query"] == ""
    s["goals"].append(name("another"))
    s["metavariables"].append({**deepcopy(s["metavariables"][0]), "id": name("another")})
    assert premise_query(s)["status"] == "REQUIRES_SINGLE_GOAL"


def test_scan_overflow_abstains_and_duplicate_events_are_deduplicated():
    index, scope = inventory((Premise("A.proof", "True", "library"), Premise("B.proof", "True", "library")))
    result = providers.propose_local_batch(RECORD, capture_fixture(), index, scope, max_scan=1)
    assert not result["drafts"] and result["events"][0]["status"] == "SCAN_BUDGET"
    assert result["truncated"]
    capture = capture_fixture()
    capture["trace"]["events"].append({**deepcopy(capture["trace"]["events"][0]), "id": "1"})
    result = batch(rehash(capture))
    assert len(result["drafts"]) == 2
    assert {o["status"] for o in result["events"][1]["outcomes"]} == {"DUPLICATE"}
    assert batch(capture, max_events=1)["truncated"]


def test_nonclosing_and_wrapper_spans_are_not_proposed():
    capture = capture_fixture()
    capture["trace"]["events"][0]["after"] = deepcopy(state())
    assert not batch(rehash(capture))["proposals"]
    capture = capture_fixture()
    capture["trace"]["events"][0]["start"] = "0"
    assert batch(rehash(capture))["events"][0]["status"] == "UNSUPPORTED_SPAN"


def test_small_budget_serves_local_span_before_whole_body():
    capture = capture_fixture()
    local = capture["trace"]["events"][0]
    whole = {**deepcopy(local), "start": str(SOURCE.encode().index(b"constructor")),
             "end": str(len(SOURCE.encode())), "id": "0"}
    local.update(id="1", parent="0")
    capture["trace"]["events"] = [whole, local]
    result = batch(rehash(capture), cap=1)
    assert result["proposals"][0]["event_id"] == 1 and result["truncated"]


@pytest.mark.parametrize("header,kind", [("next val heq =>", "null"),
    ("case branch =>", "null"), ("=>", "Lean.Parser.Tactic.case")])
def test_synthetic_branch_headers_cannot_consume_draft_slots(header, kind):
    # InfoTree fixtures, not a claim that this artificial source compiles.
    source = SOURCE.replace(BLOCK, header + "\n    " + BLOCK)
    record = {**RECORD, "src": source}
    capture = capture_fixture(source)
    local = capture["trace"]["events"][0]
    start = source.encode().index(header.encode())
    synthetic = {**deepcopy(local), "id": "0", "start": str(start),
        "end": str(start + len(header.encode())), "syntax_kind": name(kind)}
    local.update(id="1", parent="0")
    capture["trace"]["events"] = [synthetic, local]
    with pytest.raises(ValueError, match="synthetic branch header"):
        replay.replace_event(source, synthetic, "exact _root_.True.intro")
    result = providers.propose_local_batch(record, rehash(capture), *inventory(record=record), cap=1)
    assert result["events"][0]["status"] == "UNSUPPORTED_SPAN"
    assert result["proposals"][0]["event_id"] == 1


def test_ranking_report_budget_is_bound_and_abstains(monkeypatch):
    monkeypatch.setattr(providers, "LOCAL_RANKING_BYTES", 1)
    result = batch()
    assert result["truncated"] and not result["drafts"]
    assert result["events"][0]["status"] == "REPORT_BUDGET"
    assert "ranking" not in result["events"][0]
    assert result["request"]["ranking_bytes"] == 1


def test_mock_local_success_still_requires_whole_source_check(monkeypatch, tmp_path):
    capture = capture_fixture()
    def transport(cmd, **kwargs):
        # Deliberately mocked transport, not proof/Lean performance evidence.
        closed = {"status": "closed_kernel_checked", "closed_goals_checked": "1",
                  "remaining_goals": "0", "axioms": []}
        native = {"schema": replay.SCHEMA, "environment": cmd[-5],
            "lean_version": capture["trace"]["lean_version"], "lean_githash": capture["trace"]["lean_githash"],
            "event": capture["trace"]["events"][0], "candidate": cmd[-1],
            "baseline": closed, "proposed": closed, "proof_admitted": False,
            "snapshot_decoded": False, "whole_source_checked": False}
        return replay.MARKER + json.dumps(native).encode()
    monkeypatch.setattr(ps, "_run_bounded", transport)
    report = replay.collect_replay_pairs([{"id": "train", "split": "train", "source": SOURCE}],
        capture_fn=lambda _: capture,
        proposal_fn=lambda s, c: providers.propose_local_batch(RECORD, c, *inventory(), cap=1)["proposals"],
        replay_fn=partial(replay.replay_candidate, project_root=tmp_path, environment_sha256=ENV),
        compile_fn=lambda _: {"theorem_ok": False}, environment_sha256=ENV)
    assert not report["ok"] and not report["pairs"]
    assert report["attempts"][0]["replay"]["closing_reproduced"]
    assert "whole-source" in report["attempts"][0]["reason"]


@pytest.mark.parametrize("strategy", providers.LOCAL_STRATEGIES)
def test_local_cli_outputs_drafts_and_refuses_overwrite(tmp_path, monkeypatch, capsys, strategy):
    index, scope = inventory()
    files = {"corpus": RECORD, "capture": capture_fixture(),
        "premises": {"schema": "jevops-premise-index/v1", "environment_sha256": ENV,
                     "premises": [asdict(p) for p in index.entries.values()]},
        "scope": {"schema": "jevops-premise-scope/v1", **asdict(scope)}}
    argv = ["arena_providers", "--problem", RECORD["name"], "--output-dir", str(tmp_path / "out")]
    if strategy == "portfolio-v1":
        argv.extend(["--local-strategy", strategy, "--max-templates", "2"])
    for key, value in files.items():
        path = tmp_path / f"{key}.json"
        path.write_text(json.dumps(value) + "\n")
        argv.extend(["--" + key, str(path)])
    monkeypatch.setattr(sys, "argv", argv)
    assert providers.main() == 0
    assert json.loads(capsys.readouterr().out)["native_verifier_calls"] == 0
    saved = (tmp_path / "out/manifest.json").read_bytes()
    if strategy == "portfolio-v1":
        assert json.loads(saved)["request"]["max_templates"] == 2
        assert json.loads(saved)["request"]["strategy"] == strategy
    from jevops.arena_pareto import _draft, selection_plan
    draft = _draft(tmp_path / "out/local-premise-0.json", RECORD["name"])
    assert selection_plan(RECORD, [draft])["required_request_budget"] > 0
    with pytest.raises(SystemExit): providers.main()
    assert (tmp_path / "out/manifest.json").read_bytes() == saved
    # Local options cannot silently turn into a whole-proof/provider request.
    if strategy == "portfolio-v1":
        capture_option = argv.index("--capture")
        argv = argv[:capture_option] + argv[capture_option + 2:]
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit): providers.main()
        assert "requires --capture" in capsys.readouterr().err


@pytest.mark.no_seal(reason="fresh explicitly requested local Lean replay")
@pytest.mark.parametrize("premise,expected", [("True.intro", "VERIFIED"), ("False.elim", "REJECTED")])
def test_native_local_candidate_replay_and_whole_theorem(tmp_path, monkeypatch, premise, expected):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in; requires already installed Lean 4.26.0")
    from jevops import arena_lean as native
    from jevops.arena import VerificationRequest
    from jevops.lean import VersionPin
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), "v4.26.0")
    monkeypatch.setenv("PATH", str(lean.parent) + os.pathsep + os.environ.get("PATH", ""))
    pin = VersionPin("v4.26.0", "local-premise-control")
    record = {**RECORD, "name": "local_pair", "version_info": [{pin.lean_tag: pin.git_commit}]}
    verifier = native.NativeLeanVerifier({pin: native.ProjectBinding(pin, lean, tmp_path, "", project_backed=False)},
                                         max_processes=2, timeout=60)
    context = verifier.context(record)
    capture = ps.capture_source(SOURCE, project_root=tmp_path, environment_sha256=context.context_id)
    assert capture["ok"] and not capture["trace"]["elaboration_errors"]
    # The negative control lies about a real declaration's type. Inventory
    # metadata can retrieve it, but cannot make Lean accept it at this goal.
    index = PremiseIndex((Premise(premise, "True", "caller-claimed-core-control"),), environment_sha256=context.context_id)
    scope = PremiseScope(content_hash(record), context.context_id, (premise,))
    result = providers.propose_local_batch(record, capture, index, scope, cap=1)
    assert result["proposals"]
    local = replay.replay_candidate(SOURCE, capture, **result["proposals"][0], project_root=tmp_path,
                                    environment_sha256=context.context_id)
    assert local["closing_reproduced"] == (expected == "VERIFIED"), (
        local.get("reason"), local.get("native", {}).get("baseline"), local.get("native", {}).get("proposed"))
    for source, outcome in ((SOURCE, "VERIFIED"), (result["drafts"][0]["source"], expected)):
        receipt = verifier(VerificationRequest(context, source, pin))
        assert receipt.outcome.value == outcome, receipt
    assert not local["proof_admitted"] and not result["proof_verified"]
