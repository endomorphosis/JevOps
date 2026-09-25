"""Explicit bounded installed-Lean regression: no fresh canary or model calls."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import re

import pytest

pytest.importorskip("duckdb")
from jevops.arena import content_hash, source_hash
from jevops.arena_lean import NativeLeanVerifier, ProjectBinding, pinned_lean
from jevops.arena_premises import NativePremiseExporter, PremiseOrigin
from jevops.arena_prepare import validate_volume
from jevops.arena_providers import load_inventory
from jevops.arena_trial import ORDERS, _pins
from jevops.knowledge_index import KnowledgeIndex, build_index
from jevops.knowledge_lookup import (confirmation_plan, confirm_lookup, lookup_plan, render_summary, run_lookup)
from jevops.seals import Fingerprinter

pytestmark = [pytest.mark.no_seal(reason="fresh native library reuse comparison"),
    pytest.mark.skipif(os.environ.get("JEVOPS_KNOWLEDGE_LOOKUP_NATIVE_TESTS") != "1",
                      reason="explicit opt-in and capped storage required")]


def test_native_exposed_library_reuse_regression(tmp_path):
    config = json.loads(Path(os.environ["JEVOPS_ARENA_PREPARATION"]).read_text())
    volume = validate_volume(config)
    assert tmp_path.resolve().is_relative_to(volume.resolve())
    def storage_check():
        validate_volume(config)
        info = os.statvfs(volume)
        assert info.f_bavail * info.f_frsize > 100_000_000, "storage safety reserve; retain all caches"
    storage_check()
    output = Path(os.environ["JEVOPS_KNOWLEDGE_LOOKUP_RECEIPTS"])
    output.mkdir()  # never overwrite another run
    def save(name, value):
        with (output / name).open("x") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)

    # Exposed historical task, deliberately NOT a new protected canary. The
    # record is accessed only after pool selection; neither old solution nor
    # old metrics enter selection. File choice is not a blind corpus sample.
    elan = Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan")))
    anchor = pinned_lean(elan, "v4.26.0").parent.parent / "src/lean/Init/PropLemmas.lean"
    source = anchor.read_text()
    names = re.findall(r"(?m)^theorem\s+([^\s({\[:]+)", source)[:64]
    assert len(names) == len(set(names)) == 64
    save("pool-design.json", dict(schema="jevops-fixed-source-name-pool/v1", anchor=str(anchor),
        source_sha256=source_hash(source), source_bytes=len(source.encode()),
        rule="first 64 line-start unannotated theorem names in source order; lexical nomination, not AST extraction",
        names=names, supplied_solution_mapping=False, corpus_choice_blind=False,
        preregistered_before_this_run=True, top_k=8, max_candidates=64,
        max_inventory_processes=2, max_discovery_processes=144, max_confirmation_processes=24,
        training_enabled=False, watcher_changed=False, official_score=None))

    repo = Path(__file__).resolve().parents[1]
    prior = repo / "papers/completion/lean_refactor_arena/evidence/knowledge-relation-canaries-2026-09-24/and-or-distrib.json"
    record = json.loads(prior.read_text())["report"]["measurement"]["record"]
    pins = _pins(record)
    assert tuple(p.lean_tag for p in pins) == ("v4.26.0", "v4.29.1")
    save("task.json", dict(record=record, origin=str(prior), prior_receipt_sha256=source_hash(prior.read_text()),
        exposed_regression=True, blind_benchmark=False, canary_exposure_ledger_changed=False))
    bindings = {p: ProjectBinding(p, pinned_lean(elan, p.lean_tag), tmp_path, "", project_backed=False) for p in pins}
    reader = Fingerprinter()  # dependency-byte hashes only; NEVER proof receipts
    guard = NativeLeanVerifier(bindings, max_processes=0, fingerprinter=reader)
    context = guard.context(record)
    export = NativePremiseExporter(guard, max_processes=2, include_signatures=True).export(record,
        tuple(PremiseOrigin(name, "Lean.Init.PropLemmas.fixed-first64", "library") for name in names))
    save("inventory.json", export)
    assert export["status"] == "INVENTORY_ONLY", export["status"]
    inventory, scope = load_inventory(json.loads(json.dumps(export["inventory"])), json.loads(json.dumps(export["scope"])))
    artifact = build_index(tmp_path / "frozen-library.duckdb", inventory.entries.values(),
        signatures=inventory.signatures.values(), environment_sha256=scope.environment_sha256,
        source_sha256=content_hash(export["inventory"]))
    save("index-artifact.json", asdict(artifact))
    storage_check()
    with KnowledgeIndex(Path(artifact.path), expected_sha256=artifact.file_sha256) as index:
        plan = lookup_plan(record=record, index=index, scope=scope, context=context, top_k=8, max_candidates=64)
        save("lookup-plan.json", plan)
        guard = NativeLeanVerifier(bindings, max_processes=plan["max_calls"], fingerprinter=reader)
        discovery = run_lookup(plan, index=index, scope=scope, guard=guard, max_calls=plan["max_calls"], progress=True)
        save("discovery.json", discovery)
    storage_check()
    plan = confirmation_plan(discovery)
    save("confirmation-plan.json", plan)
    verifiers = {(p, order): NativeLeanVerifier({p: b}, max_processes=6, branch_order=order, fingerprinter=reader)
                 for p, b in bindings.items() for order in ORDERS}
    report = confirm_lookup(plan, discovery, verifiers=verifiers, max_calls=plan["planned_requests"], progress=True)
    save("confirmation.json", report)
    accounting = dict(inventory_processes=export["attempted_processes"], discovery_processes=discovery["native_processes"],
        confirmation_processes=report["measurement"]["native_processes"], total_ceiling=170,
        max_bytes=config["max_bytes"], all_caches_retained=True, training_enabled=False, official_score=None)
    accounting["total_processes"] = sum(accounting[k] for k in ("inventory_processes", "discovery_processes", "confirmation_processes"))
    save("accounting.json", accounting)
    with (output / "summary.md").open("x") as stream:
        stream.write(render_summary(discovery, report))
    storage_check()
    assert accounting["total_processes"] <= accounting["total_ceiling"]
    assert report["measurement"]["native_processes"] == 24
    assert all(s["status"] == "VERIFIED" for s in report["measurement"]["samples"] if s["label"] == "control")
    assert not discovery["receipt_cache_hits"] and not report["measurement"]["receipt_cache_enabled"]
    # A negative retrieval result is legitimate. Never require/tune for a win.
    if report["comparison"]["identical_sources"]:
        assert report["comparison"]["observed_pareto_improvement"] in (False, None)
    assert not report["training_enabled"] and report["official_score"] is None
