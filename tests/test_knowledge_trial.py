"""Uncached ablation controls, plus an explicit installed-Lean pilot."""
from dataclasses import asdict, replace
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")
from jevops import arena_lean as native
from jevops.arena import content_hash
from jevops.arena_trial import ORDERS
from jevops.knowledge_relations import EvidenceRelation, PropositionNode, RelationLimits
from jevops.knowledge_trial import RENDERINGS, _render_proposal, relation_trial_plan, render_summary, run_relation_trial
from jevops.lean import VersionPin
from jevops.logic_ir import parse_formula
from jevops.premise_search import PremiseIndex
from jevops.skillcenter_corpus import EvidenceCorpus
from tests.test_knowledge_relations import binding, graph_for, setup, STATEMENT, SOURCE
from tests.test_skillcenter_corpus import ingest

pytestmark = pytest.mark.no_seal(reason="fresh graph ablation, DuckDB and compiler accounting")


@pytest.fixture
def experiment(setup, tmp_path, monkeypatch):
    monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("fixture-deps"))
    bindings = {p: native.ProjectBinding(p, tmp_path / "lean", tmp_path, "", project_backed=False)
                for p in setup.context.versions}
    guard = native.NativeLeanVerifier(bindings, max_processes=0)
    ctx = guard.context(setup.record)
    index = PremiseIndex(tuple(setup.index.entries.values()), environment_sha256=ctx.context_id,
                         signatures=tuple(setup.index.signatures.values()))
    scope = replace(setup.scope, environment_sha256=ctx.context_id)
    graph = graph_for(setup.record, index, setup.corpus, setup.cid)
    inputs = dict(record=setup.record, index=index, scope=scope, corpus=setup.corpus, discovery_context=ctx)
    calls, behavior = [], {}

    def runner(b, payload, **kwargs):
        calls.append(payload)
        arm = ("control" if payload["candidate"] == payload["reference"] else
               "mapped" if "have _g" in payload["candidate"] else "local")
        raw = {"control": 9000, "mapped": 3000, "local": 5000}[arm]
        report = dict(outcome=behavior.get(arm, "VERIFIED"), type_preserved=True, target_absent_before=True,
            axioms=[], reference_axioms=[], raw_heartbeats=raw, heartbeats=raw // 1000,
            reference_raw_heartbeats=9000, reference_heartbeats=9, diagnostics=[])
        return dict(schema="jevops-native-arena/v1", request_id=payload["request_id"], target=payload["target"],
            measurement=native.METHOD, lean_version=b.pin.lean_tag.removeprefix("v"), lean_githash="b" * 40,
            branch_order="candidate-first" if payload["candidate_first"] else "reference-first", report=report), 0

    monkeypatch.setattr(native, "run_native", runner)
    def verifiers(**kwargs):
        return {(p, order): native.NativeLeanVerifier({p: b}, max_processes=12, branch_order=order, **kwargs)
                for p, b in bindings.items() for order in ORDERS}
    return SimpleNamespace(inputs=inputs, graph=graph, calls=calls, behavior=behavior, verifiers=verifiers,
                           cid=setup.cid)


def run(s, **kwargs):
    plan = relation_trial_plan(s.graph, **s.inputs)
    return run_relation_trial(plan, s.graph, **s.inputs, verifiers=s.verifiers(),
                              evidence_mode="offline_fixture", max_calls=kwargs.pop("max_calls", 24), **kwargs)


def test_plan_is_frozen_reproducible_matched_ceiling_not_matched_actual_work(experiment):
    s = experiment
    plan = relation_trial_plan(s.graph, **s.inputs)
    assert plan == relation_trial_plan(s.graph, **s.inputs) and not s.calls
    assert plan["measurement_plan"]["planned_requests"] == 24
    assert plan["budget_contract"]["search_ceilings_matched"]
    assert not plan["budget_contract"]["actual_work_matched"]
    assert not plan["graph_structure_isolated"]
    assert all(p["status"] == "PROPOSED" for p in plan["policies"].values())
    assert all(a["source"].startswith(STATEMENT + " :=") for a in plan["measurement_plan"]["arms"])


def test_fresh_balanced_fixture_compares_policies_without_native_claims(experiment):
    report = run(experiment)
    assert report["status"] == "COMPLETE" and len(experiment.calls) == 24
    trial, comparison = report["measurement"], report["comparison"]
    assert trial["verifier_invocations"] == trial["requests_reserved"] == 24
    assert trial["native_processes"] == 0 and not trial["receipt_cache_enabled"]
    assert comparison["heartbeat_result"] == "LOWER_IN_BOTH_ORDERS"
    assert all(g["control_raw"] == [5000, 5000] and g["candidate_raw"] == [3000, 3000]
               for g in comparison["strata"])
    assert not comparison["proof_verified"] and not comparison["graph_proposal_verified"]
    assert comparison["checked_edges"] == [] and not report["training_enabled"]
    assert not report["promoted"] and report["official_score"] is None
    assert "Not the all-15 Arena" in render_summary({"fixture": report})


@pytest.mark.parametrize("damage", ["candidate", "limits", "graph", "scope", "evidence", "context"])
def test_stale_or_tampered_plans_fail_before_compilation(experiment, damage):
    s = experiment
    plan, inputs, graph = copy.deepcopy(relation_trial_plan(s.graph, **s.inputs)), dict(s.inputs), s.graph
    if damage == "candidate": plan["policies"]["local-only"]["candidate"] += "\n"
    elif damage == "limits": plan["limits"]["max_states"] -= 1
    elif damage == "graph": graph = replace(graph, bindings=())
    elif damage == "scope": inputs["scope"] = replace(inputs["scope"], excluded_names=("Bridge.forward",))
    elif damage == "evidence": inputs["excluded_cids"] = (s.cid,)
    else: inputs["discovery_context"] = replace(inputs["discovery_context"], verifier_version="changed")
    with pytest.raises(ValueError):
        run_relation_trial(plan, graph, **inputs, verifiers=s.verifiers(), max_calls=24, evidence_mode="offline_fixture")
    assert not s.calls


@pytest.mark.parametrize("damage", ["option", "dependency", "missing_pin", "branch_order"])
def test_measurement_must_project_all_pin_discovery_environment(experiment, damage):
    s = experiment
    verifiers = s.verifiers(timeout=61) if damage == "option" else s.verifiers()
    key = next(iter(verifiers))
    if damage == "dependency": verifiers[key].digests[key[0]] = "f" * 64
    elif damage == "missing_pin": del verifiers[key]
    elif damage == "branch_order": verifiers[key].branch_order = "candidate-first"
    with pytest.raises(ValueError):
        run_relation_trial(relation_trial_plan(s.graph, **s.inputs), s.graph, **s.inputs,
            verifiers=verifiers, max_calls=24, evidence_mode="offline_fixture")
    assert not s.calls


def test_partial_measurements_are_not_a_success(experiment):
    report = run(experiment, max_calls=23)
    assert report["status"] == "INCOMPLETE" and len(experiment.calls) == 23
    assert report["comparison"]["heartbeat_result"] == "INCOMPLETE"
    assert report["comparison"]["observed_pareto_improvement"] is None


@pytest.mark.parametrize("arm", ["control", "mapped", "local"])
def test_rejections_are_retained_and_never_reported_as_improvements(experiment, arm):
    experiment.behavior[arm] = "REJECTED"
    report = run(experiment)
    assert len(experiment.calls) == 24
    assert report["comparison"]["heartbeat_result"] == "INCOMPLETE"
    assert report["comparison"]["observed_pareto_improvement"] is None
    assert not report["comparison"]["proof_verified"]


def test_abstention_is_reference_fallback_not_a_graph_proposal(experiment):
    s = experiment
    s.graph = replace(s.graph, bindings=())
    report = run(s)
    assert report["plan"]["policies"]["mapped-relations"]["status"] == "NO_GRAPH_PLAN"
    assert report["comparison"]["abstained"] == ["mapped-relations"]
    assert not report["comparison"]["graph_proposal_verified"]
    arms = {a["label"]: a["source"] for a in report["measurement"]["arms"]}
    assert arms["control"] == arms["mapped-relations"] and len(s.calls) == 24


def test_same_low_search_budget_applies_to_both_arms(experiment):
    s = experiment
    plan = relation_trial_plan(s.graph, **s.inputs, limits=RelationLimits(max_states=1))
    assert all(p["status"] == "SEARCH_BUDGET" and p["candidate"] is None for p in plan["policies"].values())
    assert plan["measurement_plan"]["distinct_source_count"] == 1


def test_rendering_arms_are_fixed_and_compact_local_is_mandatory(experiment):
    s = experiment
    for modes in (("inferred-term",), ("local-term", "arbitrary"), ("local-term", "local-term")):
        with pytest.raises(ValueError):
            relation_trial_plan(s.graph, **s.inputs, renderings=modes)
    plan = relation_trial_plan(s.graph, **s.inputs, renderings=RENDERINGS)
    assert plan["measurement_plan"]["planned_requests"] == 48 and not s.calls
    assert plan["budget_contract"]["verification_slots_per_arm"] == 8
    assert plan["rendering_contract"]["search_reused"]
    policies = plan["policies"]
    for mode in RENDERINGS:
        assert policies[mode]["status"] == "PROPOSED"
        assert policies[mode]["candidate"].startswith(STATEMENT + " := ")
        assert "have _g" not in policies[mode]["candidate"]
    # These fixture declarations have EXPLICIT proposition parameters: do not
    # erase those arguments merely because implicit library lemmas can infer.
    assert "@_root_.Bridge.forward (p) (q)" in policies["inferred-term"]["candidate"]
    assert " : " in policies["typed-inline"]["candidate"][len(STATEMENT):]
    assert policies["typed-inline"]["witness_proposal_sha256"] == policies["mapped-relations"]["proposal_sha256"]


@pytest.mark.parametrize("modes", [(), RENDERINGS])
def test_frozen_plans_survive_json_roundtrip_without_weakening_checks(experiment, modes):
    s = experiment
    plan = json.loads(json.dumps(relation_trial_plan(s.graph, **s.inputs, renderings=modes)))
    count = plan["measurement_plan"]["planned_requests"]
    report = run_relation_trial(plan, s.graph, **s.inputs, verifiers=s.verifiers(), max_calls=count, evidence_mode="offline_fixture")
    assert report["status"] == "COMPLETE" and len(s.calls) == count
    assert not report["training_enabled"] and report["official_score"] is None


def test_failed_mapping_witness_blocks_valid_inferred_drafts(experiment):
    s = experiment
    s.behavior["mapped"] = "REJECTED"  # only the original have-scaffold arm
    plan = relation_trial_plan(s.graph, **s.inputs, renderings=RENDERINGS)
    report = run_relation_trial(plan, s.graph, **s.inputs, verifiers=s.verifiers(), max_calls=48, evidence_mode="offline_fixture")
    assert len(s.calls) == 48 and report["status"] == "COMPLETE"
    assert next(o for o in report["measurement"]["observations"] if o["label"] == "inferred-term")["status"] == "MEASURED"
    for variant in report["rendering_comparisons"].values():
        for comparison in variant.values():
            assert not comparison["mapping_witness_passed"] and not comparison["graph_proposal_verified"]
            assert comparison["status"] == "INCOMPLETE" and comparison["observed_pareto_improvement"] is None


def test_rendering_abstention_never_claims_used_edges(experiment):
    s = experiment
    plan = relation_trial_plan(s.graph, **s.inputs, renderings=RENDERINGS)
    original = {**plan["policies"]["mapped-relations"], "term_ir": None}
    p = _render_proposal("typed-inline", original, s.graph, s.inputs["index"], s.inputs["record"], RelationLimits())
    assert p["status"] == "IR_UNAVAILABLE" and p["used_edges"] == [] and p["candidate"] is None


def test_compact_source_and_ir_tampering_rejects_before_compiler(experiment):
    s = experiment
    for arm, field in (("inferred-term", "candidate"), ("mapped-relations", "term_ir")):
        plan = relation_trial_plan(s.graph, **s.inputs, renderings=RENDERINGS)
        plan["policies"][arm][field] = None
        with pytest.raises(ValueError, match="stale"):
            run_relation_trial(plan, s.graph, **s.inputs, verifiers=s.verifiers(), max_calls=48, evidence_mode="offline_fixture")
    assert not s.calls


def test_rendering_fallback_is_not_a_generated_improvement(experiment, monkeypatch):
    from jevops import knowledge_trial as trial
    s = experiment
    original = trial.render_tree
    def blocked(tree, replacements):
        if replacements:
            raise ValueError("synthetic rendering boundary refusal")
        return original(tree, replacements)
    monkeypatch.setattr(trial, "render_tree", blocked)
    plan = relation_trial_plan(s.graph, **s.inputs, renderings=RENDERINGS)
    report = run_relation_trial(plan, s.graph, **s.inputs, verifiers=s.verifiers(), max_calls=48, evidence_mode="offline_fixture")
    for comparisons in report["rendering_comparisons"].values():
        for comparison in comparisons.values():
            assert comparison["observed_pareto_improvement"] is None and comparison["checked_edges"] == []
            assert not comparison["graph_proposal_verified"] and not comparison["mapping_correspondence_verified"]


@pytest.mark.skipif(os.environ.get("JEVOPS_RELATION_TRIAL_NATIVE_TESTS") != "1",
                   reason="separate opt-in for the bounded native pilot")
def test_native_library_relation_pilot(tmp_path):
    """Three PREDECLARED core controls, not selected after seeing measurements.

    No custom helper prefix, downloads, builds, model calls or watcher changes.
    With --basetemp on the capped volume, corpus/index/scratch are all retained.
    """
    from jevops.arena_premises import NativePremiseExporter, PremiseOrigin
    from jevops.arena_prepare import validate_volume
    from jevops.arena_providers import load_inventory
    from jevops.knowledge_index import KnowledgeIndex, build_index
    from jevops.knowledge_relations import RelationGraph

    config = json.loads(Path(os.environ["JEVOPS_ARENA_PREPARATION"]).read_text())
    volume = validate_volume(config)
    assert tmp_path.resolve().is_relative_to(volume.resolve())
    assert os.statvfs(volume).f_bavail * os.statvfs(volume).f_frsize > 100_000_000
    output = Path(os.environ["JEVOPS_RELATION_TRIAL_RECEIPTS"])
    output.mkdir()  # never reuse/overwrite another run
    modes = RENDERINGS if os.environ.get("JEVOPS_RELATION_RENDERING_TESTS") == "1" else ()
    case_calls = (3 + len(modes)) * 8
    pins = tuple(VersionPin(tag, "core-library-control") for tag in ("v4.26.0", "v4.29.1"))
    elan = Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan")))
    bindings = {p: native.ProjectBinding(p, native.pinned_lean(elan, p.lean_tag), tmp_path, "", project_backed=False)
                for p in pins}
    # One fixed synthetic SkillCenter-format provenance corpus shared by all
    # cases. Its content is NOT evidence that these mappings are faithful.
    artifact, rows = ingest(tmp_path)
    cid = rows[0]["entry_cid"]
    definitions = [
        ("and-comm", STATEMENT, SOURCE,
         (("pq", "p ∧ q"), ("qp", "q ∧ p")),
         (("swap", "iff", "pq", "qp", "And.comm", ("p", "q")),)),
        ("or-chain", "theorem sample (p q r : Prop) : p → ((p ∨ q) ∨ r)", None,
         (("p", "p"), ("pq", "p ∨ q"), ("pqr", "(p ∨ q) ∨ r")),
         (("first", "implies", "p", "pq", "Or.inl", ("p", "q")),
          ("second", "implies", "pq", "pqr", "Or.inl", ("p ∨ q", "r")))),
        ("iff-reverse", "theorem sample (p q : Prop) (h : p ∧ q) : q ∧ p", None,
         (("pq", "p ∧ q"), ("qp", "q ∧ p")),
         (("swap", "iff", "qp", "pq", "And.comm", ("q", "p")),)),
    ]
    definitions[1] = (*definitions[1][:2], definitions[1][1] + " := by exact fun h => Or.inl (Or.inl h)\n", *definitions[1][3:])
    definitions[2] = (*definitions[2][:2], definitions[2][1] + " := by exact And.intro h.right h.left\n", *definitions[2][3:])
    reports, negatives = {}, {}
    with (output / "design.json").open("x") as stream:
        json.dump(dict(cases=definitions, pins=[p.to_dict() for p in pins], repetitions=2,
                       renderings=modes, max_export_processes=6,
                       max_measurement_processes=3 * case_calls + (20 if modes else 0), max_model_calls=0,
                       implicit_remapping_negative_control=bool(modes),
                       prefix="", provenance="synthetic evidence; actual Init declarations"), stream, ensure_ascii=False)
    with EvidenceCorpus(Path(artifact.path), expected_sha256=artifact.file_sha256) as corpus:
        for case, statement, source, nodes, edges in definitions:
            validate_volume(config)
            assert os.statvfs(volume).f_bavail * os.statvfs(volume).f_frsize > 100_000_000
            record = dict(name="sample", statement=statement, src=source,
                          version_info=[{p.lean_tag: p.git_commit} for p in pins])
            guard = native.NativeLeanVerifier(bindings, max_processes=0)
            context = guard.context(record)
            export = NativePremiseExporter(guard, max_processes=2, include_signatures=True).export(record,
                tuple(PremiseOrigin(name, "Lean.Init", "library") for name in sorted({edge[4] for edge in edges})))
            assert export["status"] == "INVENTORY_ONLY", export
            original, scope = load_inventory(json.loads(json.dumps(export["inventory"])), json.loads(json.dumps(export["scope"])))
            indexed = build_index(tmp_path / f"{case}.duckdb", original.entries.values(), signatures=original.signatures.values(),
                environment_sha256=scope.environment_sha256, source_sha256=content_hash(export["inventory"]))
            with KnowledgeIndex(Path(indexed.path), expected_sha256=indexed.file_sha256) as index:
                nominated, retrieval = index.provider_index(" ".join(original.entries), target="sample", scope=scope, top_k=8)
                graph = RelationGraph(content_hash(record), context.context_id, corpus.identity["snapshot_sha256"],
                    content_hash({"manual_control": case}),
                    tuple(PropositionNode(name, parse_formula(formula)) for name, formula in nodes),
                    tuple(EvidenceRelation(edge, kind, subject, obj, (cid,)) for edge, kind, subject, obj, _, _ in edges),
                    tuple(binding(edge, decl, nominated, args) for edge, _, _, _, decl, args in edges))
                inputs = dict(record=record, index=nominated, scope=scope, corpus=corpus, discovery_context=context)
                plan = relation_trial_plan(graph, **inputs, renderings=modes)
                with (output / f"{case}-plan.json").open("x") as stream:
                    json.dump(plan, stream, ensure_ascii=False, sort_keys=True)
                verifiers = {(p, order): native.NativeLeanVerifier({p: b}, max_processes=case_calls // 4, branch_order=order)
                             for p, b in bindings.items() for order in ORDERS}
                report = run_relation_trial(plan, graph, **inputs, verifiers=verifiers, max_calls=case_calls, progress=True)
                reports[case] = report
                with (output / f"{case}.json").open("x") as stream:
                    json.dump(dict(report=report, native_inventory=export, corpus_artifact=asdict(artifact),
                        premise_artifact=asdict(indexed), retrieval=retrieval), stream, ensure_ascii=False, sort_keys=True)
                assert report["status"] == "COMPLETE", report["measurement"]["samples"]
                assert report["comparison"]["proof_verified"] and report["comparison"]["graph_proposal_verified"]
                assert report["measurement"]["native_processes"] == case_calls
                assert not report["training_enabled"] and not report["source_fidelity_verified"]
                if modes:
                    for variants in report["rendering_comparisons"].values():
                        assert variants["versus_compact_local"]["graph_proposal_verified"]
                        assert variants["versus_compact_local"]["mapping_witness_verified"]
                if modes and case == "and-comm":
                    # Wrong explicit p/q instantiation, but inference can repair
                    # it. A valid shorter theorem must NOT launder that mapping.
                    bad = replace(graph, bindings=(replace(graph.bindings[0], arguments=tuple(reversed(graph.bindings[0].arguments))),))
                    negative_plan = relation_trial_plan(bad, **inputs, renderings=("local-term", "inferred-term"), repetitions=1)
                    with (output / "negative-implicit-remap-plan.json").open("x") as stream:
                        json.dump(negative_plan, stream, ensure_ascii=False, sort_keys=True)
                    negative_verifiers = {(p, order): native.NativeLeanVerifier({p: b}, max_processes=5, branch_order=order)
                                          for p, b in bindings.items() for order in ORDERS}
                    negative = run_relation_trial(negative_plan, bad, **inputs, verifiers=negative_verifiers, max_calls=20, progress=True)
                    negatives["implicit-remap"] = negative
                    with (output / "negative-implicit-remap.json").open("x") as stream:
                        json.dump(negative, stream, ensure_ascii=False, sort_keys=True)
                    assert all(s["status"] == "REJECTED" for s in negative["measurement"]["samples"] if s["label"] == "mapped-relations")
                    assert all(s["status"] == "VERIFIED" for s in negative["measurement"]["samples"] if s["label"] == "inferred-term")
                    gate = negative["rendering_comparisons"]["inferred-term"]["versus_compact_local"]
                    assert not gate["mapping_witness_verified"] and not gate["graph_proposal_verified"]
                    assert gate["status"] == "INCOMPLETE" and gate["observed_pareto_improvement"] is None
    with (output / "summary.md").open("x") as stream:
        stream.write(render_summary(reports, negatives))
