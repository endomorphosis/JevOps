"""Fresh term checks and order-balanced metrics from saved application seeds."""
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
from jevops.arena import source_hash
from jevops.arena_lean import NativeLeanVerifier, ProjectBinding, pinned_lean
from jevops.arena_prepare import validate_volume
from jevops.arena_trial import ORDERS, _pins
from jevops.knowledge_materialize import (materialization_plan, run_materialization,
    measurement_plan, measure_materialization, render_summary)
from jevops.seals import Fingerprinter

pytestmark = [pytest.mark.no_seal(reason="fresh native term extraction and metric confirmation"),
    pytest.mark.skipif(os.environ.get("JEVOPS_KNOWLEDGE_MATERIALIZE_NATIVE_TESTS") != "1",
                      reason="explicit native opt-in and capped retained storage required")]


def test_native_materialization_with_compact_references(tmp_path):
    config = json.loads(Path(os.environ["JEVOPS_ARENA_PREPARATION"]).read_text())
    volume = validate_volume(config)
    assert tmp_path.resolve().is_relative_to(volume.resolve())
    def storage_check():
        validate_volume(config)
        info = os.statvfs(volume)
        assert info.f_bavail * info.f_frsize > 100_000_000, "stop at reserve; retain all caches"
    storage_check()
    output = Path(os.environ["JEVOPS_KNOWLEDGE_MATERIALIZE_RECEIPTS"])
    output.mkdir()
    def save(name, value):
        with (output / name).open("x") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)

    repo = Path(__file__).resolve().parents[1]
    prior = repo / "papers/completion/lean_refactor_arena/evidence/knowledge-lemma-applications-2026-09-24"
    cases = ("explicit-proposition", "two-hypotheses", "two-step-local-chain")
    inputs = {case: prior / (case + "-discovery.json") for case in cases}
    save("design.json", dict(cases=cases, policy="bm25", repetitions=2,
        inputs={case: dict(path=str(path), sha256=source_hash(path.read_text())) for case, path in inputs.items()},
        fresh_retrieval=False, saved_discovery_is_only_nomination=True,
        max_seed_and_term_checks=8, max_capture_and_replay_processes=8,
        max_confirmation_processes=72, max_total_processes=88, prefix="",
        synthetic_controls=True, blind_benchmark=False, training_enabled=False, official_score=None))
    elan = Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan")))
    reader = Fingerprinter()
    totals = dict(whole_source_checks=0, capture_and_replay_processes=0, confirmation_processes=0)
    summaries = []
    for case, path in inputs.items():
        storage_check()
        print(f"\nTerm materialization: {case}", flush=True)
        discovery = json.loads(path.read_text())
        record = discovery["plan"]["record"]
        pins = _pins(record)
        assert tuple(p.lean_tag for p in pins) == ("v4.26.0", "v4.29.1")
        bindings = {p: ProjectBinding(p, pinned_lean(elan, p.lean_tag), tmp_path, "", project_backed=False) for p in pins}
        guard = NativeLeanVerifier(bindings, max_processes=0, fingerprinter=reader)
        plan = materialization_plan(discovery, context=guard.context(record), policy="bm25")
        save(case + "-plan.json", plan)
        guard = NativeLeanVerifier(bindings, max_processes=plan["max_calls"], fingerprinter=reader)
        result = run_materialization(plan, discovery, guard=guard, max_calls=plan["max_calls"],
            max_local_processes=plan["max_local_processes"], progress=True)
        save(case + "-materialization.json", result)
        storage_check()
        trial_plan = measurement_plan(result)
        save(case + "-measurement-plan.json", trial_plan)
        verifiers = {(p, order): NativeLeanVerifier({p: b}, max_processes=6, branch_order=order, fingerprinter=reader)
                     for p, b in bindings.items() for order in ORDERS}
        measured = measure_materialization(trial_plan, result, verifiers=verifiers,
            max_calls=trial_plan["planned_requests"], progress=True)
        save(case + "-measurement.json", measured)
        summary = render_summary(result, measured)
        with (output / (case + "-summary.md")).open("x") as stream:
            stream.write(summary)
        summaries.append(f"## {case}\n\n" + summary.replace("# Checked application-term materialization\n", "", 1))
        totals["whole_source_checks"] += result["whole_source_calls"]
        totals["capture_and_replay_processes"] += result["local_invocations"]
        totals["confirmation_processes"] += measured["measurement"]["native_processes"]
        assert measured["measurement"]["native_processes"] == 24
        assert all(s["status"] == "VERIFIED" for s in measured["measurement"]["samples"])
        assert not result["receipt_cache_hits"] and not measured["measurement"]["receipt_cache_enabled"]
        if case == "two-step-local-chain":
            assert result["status"] == "NOT_AN_APPLICATION" and result["native_processes"] == 0
            assert result["candidate"] is None and not measured["versus_reference"]["native_pair_verified"]
            assert measured["versus_reference"]["observed_pareto_improvement"] is None
        else:
            assert result["status"] == "CHECKED_DRAFT", result["status"]
            assert result["native_processes"] == 8 and result["proof_verified"]
            assert len(result["extractions"]) == 2
            assert measured["versus_application"]["candidate_tokens"] < measured["versus_application"]["reference_tokens"]
            # Do not require a heartbeat win, a new high score or equality to
            # the reference text. All actual measurements are retained.
            assert measured["versus_reference"]["native_pair_verified"]
        assert not result["training_enabled"] and measured["official_score"] is None
    total = sum(totals.values())
    save("accounting.json", dict(**totals, total_processes=total, total_ceiling=88,
        max_bytes=config["max_bytes"], all_caches_retained=True, training_enabled=False, official_score=None))
    with (output / "summary.md").open("x") as stream:
        stream.write("# Application-to-term controls\n\nSaved seeds, fresh native verification and measurement. "
            "Not fresh retrieval, a blind benchmark or an autoencoder result.\n\n" + "\n".join(summaries))
    storage_check()
    assert total <= 88
