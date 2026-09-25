"""Real Lean anti-reward-hacking controls, never a new compression benchmark."""
import copy
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
from jevops.arena import content_hash, source_hash
from jevops.arena_lean import NativeLeanVerifier, ProjectBinding, pinned_lean
from jevops.arena_prepare import validate_volume
from jevops.arena_trial import Candidate, ORDERS, _pins
from jevops.knowledge_selection import compact_selection_plan, run_compact_selection, render_summary
from jevops.seals import Fingerprinter

pytestmark = [pytest.mark.no_seal(reason="fresh native rejection of forged compact-term nomination"),
    pytest.mark.skipif(os.environ.get("JEVOPS_KNOWLEDGE_SELECTION_NATIVE_TESTS") != "1",
                      reason="explicit native opt-in and capped retained storage required")]


def test_native_ties_abstention_and_forged_historical_success(tmp_path):
    config = json.loads(Path(os.environ["JEVOPS_ARENA_PREPARATION"]).read_text())
    volume = validate_volume(config)
    assert tmp_path.resolve().is_relative_to(volume.resolve())
    def storage_check():
        validate_volume(config)
        info = os.statvfs(volume)
        assert info.f_bavail * info.f_frsize > 100_000_000, "stop at reserve; retain all caches"
    storage_check()
    output = Path(os.environ["JEVOPS_KNOWLEDGE_SELECTION_RECEIPTS"])
    output.mkdir()
    def save(name, value):
        with (output / name).open("x") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
    repo = Path(__file__).resolve().parents[1]
    prior = repo / "papers/completion/lean_refactor_arena/evidence/knowledge-term-materialization-2026-09-24"
    cases = ("explicit-proposition", "two-hypotheses", "two-step-local-chain")
    inputs = {case: prior / (case + "-materialization.json") for case in cases}
    save("design.json", dict(cases=cases,
        inputs={case: dict(path=str(path), sha256=source_hash(path.read_text())) for case, path in inputs.items()},
        synthetic_exposed_controls=True, blind_benchmark=False, repetitions=2, confirmation_repetitions=3,
        selection_objective="strict-dual-v1", heartbeat_noise_floor_raw=0,
        adversarial_case="explicit-proposition: deliberately forged one-token False nomination and rehashed success receipt",
        expected_tie_processes=0, screening_ceiling=16, confirmation_reserve=24, total_process_ceiling=40,
        fresh_retrieval=False, training_enabled=False, promoted=False, official_score=None))
    elan = Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan")))
    reader, summaries, total, phases = Fingerprinter(), [], 0, []
    first = None
    for case, path in inputs.items():
        storage_check()
        report = json.loads(path.read_text())
        record = report["plan"]["record"]
        pins = _pins(record)
        assert tuple(p.lean_tag for p in pins) == ("v4.26.0", "v4.29.1")
        bindings = {p: ProjectBinding(p, pinned_lean(elan, p.lean_tag), tmp_path, "", project_backed=False) for p in pins}
        context = NativeLeanVerifier(bindings, max_processes=0, fingerprinter=reader).context(record)
        def forbidden_factory(*_):
            pytest.fail("a non-shortening or absent term must not spend native process budget")
        incumbents = [(case, None)]
        if report["candidate"]:
            incumbents.append((case + "-longer-incumbent",
                Candidate("current", report["plan"]["seed"], "explicit synthetic longer incumbent control")))
        for label, incumbent in incumbents:
            plan = compact_selection_plan(report, record=record, context=context, incumbent=incumbent)
            save(label + "-plan.json", plan)
            result = run_compact_selection(plan, report, record=record, incumbent=incumbent,
                verifier_factory=forbidden_factory, max_calls=0)
            save(label + "-selection.json", result)
            expected = "NO_CANDIDATE" if not report["candidate"] else (
                "NOT_SHORTER_THAN_REFERENCE" if incumbent else "NOT_SHORTER_THAN_INCUMBENT")
            assert result["status"] == expected
            assert result["recommended"] is None and not result["retained_incumbent_verified"]
            assert result["native_processes"] == 0
            summaries.append(f"## {label}\n\n" + render_summary(result).replace("# Compact-term selection\n", "", 1))
        if first is None:
            first = report, record, bindings, context
    report, record, bindings, context = first
    forged = copy.deepcopy(report)
    forged["candidate"] = record["statement"] + " := False\n"
    # Deliberate adversarial input. The old success flag and proof receipts are
    # kept misleading, and the hash is recomputed: hashes are not attestations.
    assert forged["proof_verified"] and forged["status"] == "CHECKED_DRAFT"
    forged["report_sha256"] = content_hash({k: v for k, v in forged.items() if k != "report_sha256"})
    save("adversarial-input.json", dict(deliberately_forged=True, proof_authority=False, nomination=forged))
    plan = compact_selection_plan(forged, record=record, context=context)
    save("adversarial-plan.json", plan)
    def factory(phase, limit):
        storage_check()
        phases.append(phase)
        return ({(p, order): NativeLeanVerifier({p: b}, max_processes=limit,
                    branch_order=order, fingerprinter=reader) for p, b in bindings.items() for order in ORDERS}, {})
    result = run_compact_selection(plan, forged, record=record, verifier_factory=factory,
        max_calls=plan["required_request_budget"], progress=True)
    save("adversarial-selection.json", result)
    summaries.append("## Deliberately forged success receipt\n\n" + render_summary(result).replace("# Compact-term selection\n", "", 1))
    total += result["native_processes"]
    save("accounting.json", dict(total_processes=total, reserved_ceiling=40, phases=phases,
        max_bytes=config["max_bytes"], all_caches_retained=True, training_enabled=False, official_score=None))
    with (output / "summary.md").open("x") as stream:
        stream.write("# Compact-term admission regression controls\n\n"
            "Exposed synthetic tasks; no fresh retrieval or compression benchmark. "
            "The forged-input case tests rejection, not discovery.\n\n" + "\n".join(summaries))
    assert total == 16 and phases == ["screen"]
    assert result["recommended"] is None and result["retained_incumbent_verified"]
    assert result["status"] == "NO_IMPROVEMENT"
    samples = result["selection"]["screen"]["samples"]
    assert len(samples) == 16 and not result["selection"]["screen"]["receipt_cache_enabled"]
    assert all(s["status"] == ("VERIFIED" if s["label"] == "control" else "REJECTED") for s in samples)
    storage_check()
