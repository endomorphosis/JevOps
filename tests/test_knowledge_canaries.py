"""Protected identities, once-only exposure, fixed accounting and opt-in native eval."""
from dataclasses import asdict
import copy
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")
from jevops.arena import content_hash
from jevops.knowledge_canaries import (CanaryLedger, PINS, alpha_group, assert_training_disjoint,
    bind_graph, make_manifest, run_canaries, summarize, validate_manifest)
from jevops.knowledge_trial import RENDERINGS, relation_trial_plan, run_relation_trial
from jevops.proof_ca import canonical_json

pytestmark = pytest.mark.no_seal(reason="fresh canary exposure ledger and immutable input checks")


def development_records():
    root = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/evidence/knowledge-relation-rendering-2026-09-24"
    return [json.loads((root / (name + ".json")).read_text())["report"]["measurement"]["record"]
            for name in ("and-comm", "or-chain", "iff-reverse")]


@pytest.fixture
def manifest():
    return make_manifest(development_records())


def test_frozen_cases_are_reproducible_alpha_distinct_and_protected(manifest):
    assert manifest == make_manifest(development_records())
    validate_manifest(json.loads(canonical_json(manifest)))
    assert len(manifest["cases"]) == len({r["group_sha256"] for r in manifest["cases"]}) == 6
    assert all(r["split"] == "canary" and not r["training_allowed"] for r in manifest["cases"])
    assert manifest["max_total_processes"] == 6 * (2 + 48) == 300
    assert not manifest["training_enabled"] and not manifest["promoted"]
    renamed = make_manifest(development_records(), seed=71)
    assert manifest["cases"][0]["record"]["src"] != renamed["cases"][0]["record"]["src"]
    assert [r["group_sha256"] for r in manifest["cases"]] == [r["group_sha256"] for r in renamed["cases"]]


@pytest.mark.parametrize("field", ["seed", "limits", "renderings", "primary_policy", "cases", "implementation_sha256"])
def test_manifest_mutations_fail_closed(manifest, field):
    changed = copy.deepcopy(manifest)
    if field == "seed": changed[field] += 1
    elif field == "limits": changed[field]["max_states"] += 1
    elif field == "renderings": changed[field].pop()
    elif field == "cases": changed[field][0]["record"]["src"] += "\n"
    else: changed[field] = "changed"
    with pytest.raises(ValueError, match="stale"):
        validate_manifest(changed)


def test_development_overlap_is_not_resampled_away(manifest):
    with pytest.raises(ValueError, match="overlap"):
        make_manifest([manifest["cases"][0]["record"]])


def test_alpha_groups_ignore_renaming_order_duplicate_hypotheses_and_arrow_binders():
    a = "theorem a (p q : Prop) (h : p) (k : q) : p ∧ q := by skip"
    b = "theorem b (y x : Prop) (second : y) (first : x) (again : x) : x ∧ y := by skip"
    c = "theorem c (x y : Prop) : x → y → (x ∧ y) := by skip"
    assert alpha_group(a) == alpha_group(b) == alpha_group(c)
    with pytest.raises(ValueError, match="four-atom"):
        alpha_group("theorem t (p q r s u : Prop) : p ∧ q ∧ r ∧ s ∧ u := by skip")


@pytest.mark.parametrize("bypass", ["unchanged", "rename_id", "rename_source", "body", "split"])
def test_protected_training_admission_rejects_relabeling(manifest, bypass):
    case = manifest["cases"][0]
    row = dict(id=case["id"], split="train", source=case["record"]["src"])
    if bypass != "unchanged": row["id"] = "alleged-new-training-row"
    if bypass == "rename_source": row["source"] = make_manifest(development_records(), seed=6)["cases"][0]["record"]["src"]
    if bypass == "body": row["source"] = case["record"]["statement"] + " := by skip"
    if bypass == "split": row["split"] = "canary"
    with pytest.raises(ValueError, match="protected"):
        assert_training_disjoint(manifest, [row])
    assert_training_disjoint(manifest, [dict(id="train-identity", split="train", source="theorem t (p : Prop) : p → p := by intro h; exact h")])


def test_duckdb_exposure_survives_close_partial_failure_and_new_seed(manifest, tmp_path):
    path = tmp_path / "exposure.duckdb"
    ledger = CanaryLedger(path)
    ledger.claim(manifest)
    ledger.finish(manifest, "INCOMPLETE")
    ledger.close()
    reopened = CanaryLedger(path)
    try:
        for m in (manifest, make_manifest(development_records(), seed=8)):
            with pytest.raises(ValueError, match="previously exposed"):
                reopened.claim(m)
        assert reopened.db.execute("SELECT count(*) FROM exposed").fetchone()[0] == 6
        assert reopened.db.execute("SELECT status FROM runs").fetchall() == [("INCOMPLETE",)]
        with pytest.raises(ValueError): reopened.finish(manifest, "COMPLETE")
    finally:
        reopened.close()


def fixture_backend(case, manifest, output):
    policies = {label: dict(status="PROPOSED") for label in ("local-term", "mapped-relations", "inferred-term")}
    comparison = dict(graph_proposal_verified=True, observed_pareto_improvement=True,
                      reference_tokens=20, candidate_tokens=1, heartbeat_result="LOWER_IN_BOTH_ORDERS")
    # Deliberately overclaims graph success, but mode remains offline: never
    # count these synthetic numbers as real native paired wins.
    return dict(status="COMPLETE", setup_processes=2, report=dict(status="COMPLETE",
        measurement=dict(record=case["record"], evidence_mode="offline_fixture", planned_requests=48,
                         requests_reserved=48, verifier_invocations=48, native_processes=0),
        plan=dict(renderings=manifest["renderings"], limits=manifest["limits"], policies=policies),
        rendering_comparisons={"inferred-term": {"versus_compact_local": comparison}}))


def test_fixture_results_do_not_become_native_wins_and_no_case_disappears(manifest, tmp_path):
    ledger = CanaryLedger(tmp_path / "ledger.duckdb")
    calls = []
    def backend(case, plan, output):
        calls.append(case["id"])
        if len(calls) == 2: raise RuntimeError("fixture setup failure")
        return fixture_backend(case, plan, output)
    try:
        summary = run_canaries(manifest, evaluate_case=backend, ledger=ledger, output_dir=tmp_path / "results",
            resource_check=lambda: None, max_processes=300, evidence_mode="offline_fixture")
        assert len(calls) == summary["denominator"] == 6
        assert summary["status"] == "INCOMPLETE" and summary["cases"][1]["status"] == "ERROR"
        assert summary["measured_native_pairs"] == summary["strict_joint_improvements"] == 0
        assert summary["processes_reserved"] == 300
        assert (tmp_path / "results" / "summary.md").is_file()
    finally:
        ledger.close()


def test_low_storage_stops_without_reducing_denominator_or_freeing_ledger(manifest, tmp_path):
    ledger = CanaryLedger(tmp_path / "ledger.duckdb")
    checks = []
    def resources():
        checks.append(1)
        if len(checks) == 3: raise OSError("storage limit")
    try:
        result = run_canaries(manifest, evaluate_case=fixture_backend, ledger=ledger, output_dir=tmp_path / "results",
            resource_check=resources, max_processes=300, evidence_mode="offline_fixture")
        assert result["denominator"] == 6 and result["processes_reserved"] == 50
        assert [c["status"] for c in result["cases"]] == ["COMPLETE", "STOPPED", *["NOT_RUN"] * 4]
        with pytest.raises(ValueError, match="previously exposed"): ledger.claim(manifest)
    finally:
        ledger.close()


def test_full_budget_required_before_ledger_claim(manifest, tmp_path):
    ledger = CanaryLedger(tmp_path / "ledger.duckdb")
    try:
        with pytest.raises(ValueError, match="allowance"):
            run_canaries(manifest, evaluate_case=fixture_backend, ledger=ledger, output_dir=tmp_path / "out",
                          resource_check=lambda: None, max_processes=299)
        assert ledger.db.execute("SELECT count(*) FROM exposed").fetchone()[0] == 0
    finally:
        ledger.close()


@pytest.mark.parametrize("missing_gate", ["none", "status", "mode", "graph", "baseline"])
def test_summary_requires_complete_native_graph_and_generated_baseline(manifest, tmp_path, missing_gate):
    # Unit-test the summary contract with simulated backend fields. These are
    # not native observations and are never written as measurement receipts.
    case = manifest["cases"][0]
    result = fixture_backend(case, manifest, tmp_path)
    result["report"]["measurement"]["evidence_mode"] = "local_lean"
    if missing_gate == "status": result["status"] = "IMPLEMENTATION_CHANGED"
    if missing_gate == "mode": result["report"]["measurement"]["evidence_mode"] = "offline_fixture"
    if missing_gate == "graph":
        result["report"]["rendering_comparisons"]["inferred-term"]["versus_compact_local"]["graph_proposal_verified"] = False
    if missing_gate == "baseline": result["report"]["plan"]["policies"]["local-term"]["status"] = "ABSTAIN"
    summary = summarize(manifest, {case["id"]: result})
    assert summary["denominator"] == 6 and summary["status"] == "INCOMPLETE"
    assert summary["measured_native_pairs"] == summary["strict_joint_improvements"] == int(missing_gate == "none")
    assert [r["status"] for r in summary["cases"][1:]] == ["NOT_RUN"] * 5


def test_manifest_change_rejected_before_backend_or_exposure(manifest, tmp_path):
    changed = copy.deepcopy(manifest)
    changed["repetitions"] = 3
    ledger = CanaryLedger(tmp_path / "ledger.duckdb")
    try:
        with pytest.raises(ValueError, match="stale"):
            run_canaries(changed, evaluate_case=lambda *args: pytest.fail("backend must not run"),
                         ledger=ledger, output_dir=tmp_path / "out", resource_check=lambda: None, max_processes=300)
        assert ledger.db.execute("SELECT count(*) FROM exposed").fetchone()[0] == 0
        assert not (tmp_path / "out").exists()
    finally:
        ledger.close()


@pytest.mark.skipif(os.environ.get("JEVOPS_RELATION_CANARY_NATIVE_TESTS") != "1", reason="explicit 300-process canary opt-in")
def test_native_protected_relation_canaries(tmp_path):
    from jevops import arena_lean as native
    from jevops.arena_premises import NativePremiseExporter, PremiseOrigin
    from jevops.arena_prepare import validate_volume
    from jevops.arena_providers import load_inventory
    from jevops.arena_trial import ORDERS
    from jevops.knowledge_index import KnowledgeIndex, build_index
    from jevops.seals import Fingerprinter
    from jevops.skillcenter_corpus import EvidenceCorpus
    from tests.test_skillcenter_corpus import ingest

    config = json.loads(Path(os.environ["JEVOPS_ARENA_PREPARATION"]).read_text())
    volume = validate_volume(config)
    assert tmp_path.resolve().is_relative_to(volume.resolve())
    def resources():
        validate_volume(config)
        stat = os.statvfs(volume)
        if stat.f_bavail * stat.f_frsize < 100_000_000:
            raise OSError("stop at existing storage allowance; retain all caches")
    resources()
    manifest = make_manifest(development_records())
    artifact, evidence_rows = ingest(tmp_path)
    reader = Fingerprinter()
    elan = Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan")))
    bindings = {p: native.ProjectBinding(p, native.pinned_lean(elan, p.lean_tag), tmp_path, "", project_backed=False) for p in PINS}
    ledger_path = volume / "cache" / "protected-relation-canaries-v1.duckdb"
    ledger = CanaryLedger(ledger_path)
    output = Path(os.environ["JEVOPS_RELATION_CANARY_RECEIPTS"])
    try:
        with EvidenceCorpus(Path(artifact.path), expected_sha256=artifact.file_sha256) as corpus:
            def backend(case, frozen, directory):
                record = case["record"]
                guard = native.NativeLeanVerifier(bindings, max_processes=0, fingerprinter=reader)
                context = guard.context(record)
                names = sorted({e[3] for e in case["edges"]})
                export = NativePremiseExporter(guard, max_processes=2, include_signatures=True).export(record,
                    tuple(PremiseOrigin(n, "Lean.Init", "library") for n in names),
                    excluded_names=tuple(c["id"] for c in frozen["cases"]))
                # Preserve setup failures too; do not drop them from the suite.
                with (directory / (case["family"] + "-inventory.json")).open("x") as stream:
                    stream.write(canonical_json(export))
                if export["status"] != "INVENTORY_ONLY":
                    raise ValueError("native inventory unavailable: " + export.get("reason", ""))
                original, scope = load_inventory(json.loads(canonical_json(export["inventory"])), json.loads(canonical_json(export["scope"])))
                indexed = build_index(tmp_path / (case["family"] + ".duckdb"), original.entries.values(),
                    signatures=original.signatures.values(), environment_sha256=scope.environment_sha256,
                    source_sha256=content_hash(export["inventory"]))
                with KnowledgeIndex(Path(indexed.path), expected_sha256=indexed.file_sha256) as index:
                    nominated, retrieval = index.provider_index(" ".join(names), target=case["id"], scope=scope, top_k=8)
                    graph = bind_graph(case, nominated, corpus, evidence_rows[0]["entry_cid"])
                    inputs = dict(record=record, index=nominated, scope=scope, corpus=corpus, discovery_context=context)
                    plan = relation_trial_plan(graph, **inputs, renderings=RENDERINGS, repetitions=frozen["repetitions"])
                    with (directory / (case["family"] + "-plan.json")).open("x") as stream:
                        stream.write(canonical_json(plan))
                    verifiers = {(p, order): native.NativeLeanVerifier({p: b}, max_processes=12, branch_order=order,
                                 fingerprinter=reader) for p, b in bindings.items() for order in ORDERS}
                    report = run_relation_trial(plan, graph, **inputs, verifiers=verifiers, max_calls=48, progress=True)
                    return dict(report=report, setup_processes=export["attempted_processes"], corpus_artifact=asdict(artifact),
                                premise_artifact=asdict(indexed), retrieval=retrieval)
            summary = run_canaries(manifest, evaluate_case=backend, ledger=ledger, output_dir=output,
                                    resource_check=resources, max_processes=300)
        # Do not assert that the optimizer wins, or rescue rejected/abstaining
        # cases. The frozen one-shot observation is the result, including gaps.
        assert summary["denominator"] == 6
        assert summary["processes_reserved"] <= 300 and not summary["training_enabled"]
        assert ledger.db.execute("SELECT count(*) FROM exposed").fetchone()[0] >= 6
        assert (output / "summary.json").is_file()
    finally:
        ledger.close()
