"""Bounded native one-lemma controls; hand-designed, NOT a blind benchmark."""
from dataclasses import asdict
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
from jevops.arena import content_hash
from jevops.arena_lean import NativeLeanVerifier, ProjectBinding, pinned_lean
from jevops.arena_premises import NativePremiseExporter, PremiseOrigin
from jevops.arena_prepare import validate_volume
from jevops.arena_providers import load_inventory
from jevops.arena_trial import ORDERS
from jevops.knowledge_index import KnowledgeIndex, build_index
from jevops.knowledge_lookup import (POLICIES, confirmation_plan, confirm_lookup, lookup_plan, render_summary, run_lookup)
from jevops.lean import VersionPin
from jevops.seals import Fingerprinter

pytestmark = [pytest.mark.no_seal(reason="fresh native explicit-application controls"),
    pytest.mark.skipif(os.environ.get("JEVOPS_KNOWLEDGE_APPLICATION_NATIVE_TESTS") != "1",
                      reason="explicit opt-in with capped storage required")]


def test_native_single_lemma_application_controls(tmp_path):
    config = json.loads(Path(os.environ["JEVOPS_ARENA_PREPARATION"]).read_text())
    volume = validate_volume(config)
    assert tmp_path.resolve().is_relative_to(volume.resolve())
    def storage_check():
        validate_volume(config)
        info = os.statvfs(volume)
        assert info.f_bavail * info.f_frsize > 100_000_000, "storage reserve reached; retain all caches"
    storage_check()
    output = Path(os.environ["JEVOPS_KNOWLEDGE_APPLICATION_RECEIPTS"])
    output.mkdir()  # no overwriting prior evidence
    def save(name, value):
        with (output / name).open("x") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)

    pins = tuple(VersionPin(tag, "core-application-control") for tag in ("v4.26.0", "v4.29.1"))
    # Shared hand-chosen pool tests application capability, not blind retrieval.
    # Already compact references deliberately avoid an inflated denominator.
    names = ("And.left", "Nat.le_trans", "and_not_self_iff")
    cases = (
        ("explicit-proposition", "theorem sample (p : Prop) : p ∧ ¬p ↔ False",
         "and_not_self_iff p", "and_not_self_iff"),
        ("two-hypotheses", "theorem sample (a b c : Nat) (hab : a ≤ b) (hbc : b ≤ c) : a ≤ c",
         "Nat.le_trans hab hbc", "Nat.le_trans"),
        ("two-step-local-chain", "theorem sample (p q r : Prop) (hp : p) (pq : p → q) (qr : q → r) : r",
         "qr (pq hp)", None),
    )
    design = dict(cases=cases, pool=names, pins=[p.to_dict() for p in pins],
        application_mode="bare-then-apply", top_k=3, max_candidates=3, repetitions=2,
        max_export_processes=6, max_discovery_processes=72, max_confirmation_processes=72,
        max_total_processes=150, synthetic_controls=True, blind_benchmark=False,
        task_matched_pool=True, prefix="", training_enabled=False, official_score=None)
    save("design.json", design)
    elan = Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan")))
    bindings = {p: ProjectBinding(p, pinned_lean(elan, p.lean_tag), tmp_path, "", project_backed=False) for p in pins}
    reader = Fingerprinter()  # dependency hashes only, not cached proof results
    totals = dict(inventory_processes=0, discovery_processes=0, confirmation_processes=0)
    summaries = []
    for case, statement, body, expected in cases:
        storage_check()
        print(f"\nApplication control: {case}", flush=True)
        record = dict(name="sample", statement=statement, src=statement + " := " + body + "\n",
                      version_info=[{p.lean_tag: p.git_commit} for p in pins])
        guard = NativeLeanVerifier(bindings, max_processes=0, fingerprinter=reader)
        context = guard.context(record)
        export = NativePremiseExporter(guard, max_processes=2, include_signatures=True).export(record,
            tuple(PremiseOrigin(name, "Lean.Init.application-controls", "library") for name in names))
        save(case + "-inventory.json", export)
        assert export["status"] == "INVENTORY_ONLY", export["status"]
        inventory, scope = load_inventory(json.loads(json.dumps(export["inventory"])), json.loads(json.dumps(export["scope"])))
        assert set(inventory.entries) == set(names)
        artifact = build_index(tmp_path / (case + ".duckdb"), inventory.entries.values(),
            signatures=inventory.signatures.values(), environment_sha256=scope.environment_sha256,
            source_sha256=content_hash(export["inventory"]))
        save(case + "-index.json", asdict(artifact))
        with KnowledgeIndex(Path(artifact.path), expected_sha256=artifact.file_sha256) as index:
            plan = lookup_plan(record=record, index=index, scope=scope, context=context,
                top_k=3, max_candidates=3, application_mode="bare-then-apply")
            save(case + "-lookup-plan.json", plan)
            guard = NativeLeanVerifier(bindings, max_processes=plan["max_calls"], fingerprinter=reader)
            discovery = run_lookup(plan, index=index, scope=scope, guard=guard, max_calls=plan["max_calls"], progress=True)
            save(case + "-discovery.json", discovery)
        storage_check()
        plan = confirmation_plan(discovery)
        save(case + "-confirmation-plan.json", plan)
        verifiers = {(p, order): NativeLeanVerifier({p: b}, max_processes=6, branch_order=order, fingerprinter=reader)
                     for p, b in bindings.items() for order in ORDERS}
        report = confirm_lookup(plan, discovery, verifiers=verifiers, max_calls=plan["planned_requests"], progress=True)
        save(case + "-confirmation.json", report)
        summary = render_summary(discovery, report)
        with (output / (case + "-summary.md")).open("x") as stream:
            stream.write(summary)
        summaries.append(f"## {case}\n\n" + summary.replace("# Goal-only library reuse regression\n", "", 1))
        totals["inventory_processes"] += export["attempted_processes"]
        totals["discovery_processes"] += discovery["native_processes"]
        totals["confirmation_processes"] += report["measurement"]["native_processes"]
        assert discovery["status"] == "COMPLETE"
        assert report["measurement"]["native_processes"] == 24
        assert all(s["status"] == "VERIFIED" for s in report["measurement"]["samples"])
        assert not discovery["receipt_cache_hits"] and not report["measurement"]["receipt_cache_enabled"]
        for label in POLICIES:
            row = discovery["policies"][label]
            assert not row["composition_claimed"] and not row["semantic_equivalence_decided"]
            # Every tested bare constant must actually fail on both pins.
            assert all(r["outcome"] == "REJECTED" for a in row["attempts"] if a["method"] == "bare"
                       for r in a["evaluation"]["receipts"])
            if expected is not None:
                assert row["status"] == "FOUND" and row["selected_name"] == expected
                assert row["selected_method"] == "apply-assumption" and row["proof_verified"]
            else:
                assert row["status"] == "NO_SUPPORTED_APPLICATION_IN_SEARCHED_SET" and row["candidate"] is None
        comparison = report["comparison"]
        assert comparison["native_pair_verified"] is (expected is not None)
        assert comparison["observed_pareto_improvement"] in (False, None)
        if expected is None:
            # Both policies fall back to the original two-step proof. Passing
            # fallback checks must not turn abstention into discovered success.
            assert comparison["status"] == "INCOMPLETE"
            assert all(a["source"] == record["src"] for a in report["measurement"]["arms"])
    total = sum(totals.values())
    save("accounting.json", dict(**totals, total_processes=total, total_ceiling=150,
        all_caches_retained=True, max_bytes=config["max_bytes"], training_enabled=False, official_score=None))
    with (output / "summary.md").open("x") as stream:
        stream.write("# One-lemma application controls\n\nHand-designed capability checks with compact references, "
                     "not a blind benchmark, autoencoder result or high-score claim.\n\n" + "\n".join(summaries))
    storage_check()
    assert total <= 150
