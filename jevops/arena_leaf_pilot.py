"""Frozen leaf-replacement ablation against a supplied Arena incumbent.

Plan-only by default. Execution needs a read-only source snapshot, prepared
projects, capped storage and a full process reservation. No builds or models.
Strict-dual is the default; aggregate-local trade-offs require explicit opt-in.
"""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

from .arena import content_hash, reference_tokens
from .arena_compositions import PREFIX_DROP_RULES, draft_batch
from .arena_lean import CORPUS, NativeLeanVerifier, project_binding
from .arena_pareto import selection_plan, run_selection, summary
from .arena_prepare import exclusive, validate_volume
from .arena_snapshot import verify_snapshot
from .arena_trial import Candidate, ORDERS, _pins
from .seals import Fingerprinter

ROOT = Path(__file__).resolve().parents[1]
PATHS = (("intro_simp_grind_first",), ("intro_simp_grind_all",))
PROFILES = {
    "intro-simp-grind": PATHS,
    "subset-append": (("subset_trans_append_left",), ("subset_trans_append_right",),
                      ("subset_trans_append_left", "subset_trans_append_right")),
    "subset-append-nested": (
        ("subset_trans_append_left",),
        ("subset_trans_append_right",),
        ("subset_trans_append_left", "subset_trans_append_right"),
        ("subset_trans_append_left", "subset_trans_append_left"),
        ("subset_trans_append_left", "subset_trans_append_left", "subset_trans_append_right"),
    ),
    "subset-append-shared-target": (
        ("subset_pair_target_left",),
        ("subset_pair_target_right",),
        ("subset_pair_target_right", "subset_trans_append_left", "subset_trans_append_right"),
    ),
    "subset-append-simp": (
        ("subset_pair_simp_first",), ("subset_pair_simp_all",),
        ("subset_pair_simp_split_first",), ("subset_pair_simp_split_all",),
    ),
    "subset-triple-reconstruct": (
        ("subset_triple_simp",), ("subset_triple_grind",), ("subset_triple_simp_grind",),
    ),
    "subset-triple-normalize": (
        ("subset_triple_simp_normalized",), ("subset_triple_simp_normalized_compact",),
    ),
    "subset-triple-term": (("subset_triple_term",), ("subset_triple_term_leaves",)),
    "simp-prefix-scope": (("simp_prefix_goal",), ("simp_prefix_introduced_goal",)),
    "simp-prefix-append-tree": (
        ("simp_prefix_no_append_assoc",),
        ("simp_prefix_no_append_assoc", "subset_triple_left_nested"),
    ),
    "simp-prefix-single-deletions": tuple((rule,) for rule in PREFIX_DROP_RULES),
    # One predeclared positional edit, without screening unrelated deletions.
    # On the confirmed 168-token Strata seed this completes the getVars pair.
    "simp-prefix-drop-second": (("simp_prefix_drop_1",),),
}
OBJECTIVES = ("strict-dual-v1", "aggregate-local-v1")


def _selection_incumbent(record, incumbent):
    """Separate the comparison role from a reusable draft's original label.

    Exported winners use the same composition-N namespace as new proposals.
    Preserve the input nomination in the pilot plan, but never let its label
    collide with new arms or the reserved control. No source or trust changes.
    """
    if incumbent.source == record["src"]:
        return None
    return Candidate("incumbent", incumbent.source, incumbent.provenance)


def make_plan(record, incumbent, *, profile="intro-simp-grind", selection_objective="strict-dual-v1"):
    if type(incumbent) is not Candidate:
        raise ValueError("explicit typed current incumbent required")
    if type(profile) is not str or profile not in PROFILES:
        raise ValueError("allowlisted fixed profile required")
    if type(selection_objective) is not str or selection_objective not in OBJECTIVES:
        raise ValueError("explicit allowlisted selection objective required")
    paths = PROFILES[profile]
    drafts = draft_batch(record, paths, cap=len(paths), seed=incumbent)
    candidates = [Candidate(d["label"], d["source"], d["provenance"]) for d in drafts["drafts"]]
    # Abstention stays a zero-call outcome, never an unchanged 'successful' arm.
    selection = selection_plan(record, candidates,
        incumbent=_selection_incumbent(record, incumbent), repetitions=2,
        confirmation_repetitions=3, selection_objective=selection_objective, heartbeat_noise_floor_raw=100) if candidates else None
    plan = dict(schema="jevops-arena-leaf-pilot/v4", profile=profile, selection_objective=selection_objective,
        record=dict(record), incumbent=asdict(incumbent),
        drafts=drafts, selection=selection, max_processes=selection["required_request_budget"] if selection else 0,
        task_split="exposed-arena-task-not-held-out", policy="fixed-profile-paths; no retries or adaptive expansion",
        training_enabled=False, promoted=False, official_score=None)
    return {**plan, "plan_sha256": content_hash(plan)}


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def run(plan, *, bindings, directory, max_processes, check_resources):
    incumbent = Candidate(**plan["incumbent"])
    if content_hash(make_plan(plan["record"], incumbent, profile=plan["profile"],
                             selection_objective=plan.get("selection_objective", "strict-dual-v1"))) != content_hash(plan):
        raise ValueError("mutated or stale frozen leaf plan")
    if type(max_processes) is not int or max_processes != plan["max_processes"]:
        raise ValueError("exact full process reservation required")
    if set(bindings) != set(_pins(plan["record"])):
        raise ValueError("every declared pin must be prepared")
    # Own the mutable plan before calling injected resource checks.
    plan = json.loads(json.dumps(plan))
    check_resources()
    directory.mkdir()
    save(directory / "plan.json", plan)
    if plan["selection"] is None:
        report = dict(status="NO_CANDIDATE", native_processes=0, recommended=None,
            retained_incumbent_verified=False, training_enabled=False, promoted=False, official_score=None)
        save(directory / "report.json", report)
        return report
    readers, verifiers = {}, {}
    def factory(phase, limit):
        check_resources()
        save(directory / (phase + "-reservation.json"), dict(phase=phase, processes=limit, retries=0))
        readers[phase] = Fingerprinter()
        verifiers[phase] = {(p, order): NativeLeanVerifier({p: b}, max_processes=limit,
            timeout=90, branch_order=order, fingerprinter=readers[phase]) for p, b in bindings.items() for order in ORDERS}
        return verifiers[phase], {}
    candidates = [Candidate(d["label"], d["source"], d["provenance"]) for d in plan["drafts"]["drafts"]]
    report = run_selection(plan["record"], candidates, factory,
        incumbent=_selection_incumbent(plan["record"], incumbent),
        max_calls=max_processes, repetitions=2, confirmation_repetitions=3,
        selection_objective=plan["selection_objective"], heartbeat_noise_floor_raw=100, progress=True)
    check_resources()
    report.update(task_split=plan["task_split"], leaf_plan_sha256=plan["plan_sha256"])
    save(directory / "report.json", report)
    with (directory / "summary.md").open("x") as stream:
        stream.write("# Frozen Arena leaf replacement experiment\n\n"
            "An exposed Arena incumbent, not a random canary or a training result.\n"
            f"Fixed profile: {plan['profile']}; no retries or post-result batch expansion.\n\n" + summary(report))
    save(directory / "accounting.json", dict(native_processes=report["native_processes"],
        reserved_ceiling=max_processes, phases=list(verifiers), all_caches_retained=True,
        proof_receipt_cache_enabled=False, model_calls=0, training_enabled=False, promoted=False, official_score=None))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem", required=True)
    parser.add_argument("--incumbent", type=Path, required=True)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="intro-simp-grind")
    parser.add_argument("--selection-objective", choices=OBJECTIVES, default="strict-dual-v1",
                        help="aggregate-local-v1 explicitly permits token/heartbeat trade-offs")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-processes", type=int, default=0)
    parser.add_argument("--snapshot-manifest-sha256")
    parser.add_argument("--preparation-root", type=Path)
    parser.add_argument("--projects", type=Path)
    parser.add_argument("--elan-home", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = [json.loads(line) for line in CORPUS.read_text().splitlines() if line.strip()]
    matches = [r for r in records if r["name"] == args.problem]
    if len(matches) != 1 or args.incumbent.stat().st_size > 1_048_576:
        parser.error("one corpus record and a bounded incumbent draft required")
    draft = json.loads(args.incumbent.read_text())
    if set(draft) != {"name", "label", "source", "provenance"} or draft["name"] != args.problem:
        parser.error("incumbent must be a matching four-field draft, not a success receipt")
    record, incumbent = matches[0], Candidate(draft["label"], draft["source"], draft["provenance"])
    plan = make_plan(record, incumbent, profile=args.profile, selection_objective=args.selection_objective)
    if not args.execute:
        print(json.dumps(dict(status="PLANNED", required_processes=plan["max_processes"],
            reference_tokens=reference_tokens(record["src"], record["statement"]),
            incumbent_tokens=reference_tokens(incumbent.source, record["statement"]),
            drafts=[dict(label=d["label"], tokens=reference_tokens(d["source"], record["statement"]))
                    for d in plan["drafts"]["drafts"]], plan_sha256=plan["plan_sha256"])))
        return 0
    if not all((args.snapshot_manifest_sha256, args.preparation_root, args.projects, args.elan_home, args.output)):
        parser.error("execution requires snapshot, preparation, projects, elan-home and new output")
    if args.max_processes != plan["max_processes"]:
        parser.error("reserve the exact frozen process ceiling before execution")
    config = json.loads((args.preparation_root / "preparation.json").read_text())
    with exclusive(args.preparation_root / "single-build.lock"):
        mount = validate_volume(config)
        if args.output.exists() or not args.output.resolve().is_relative_to(mount):
            raise ValueError("new output inside capped preparation volume required")
        if not Path(os.environ.get("TMPDIR", "/tmp")).resolve().is_relative_to(mount):
            raise ValueError("temporary storage must stay inside the capped volume")
        if any(not p.resolve().is_relative_to(ROOT / "inputs") for p in (args.incumbent, args.projects)):
            raise ValueError("incumbent and project mappings must belong to the snapshot")
        before = verify_snapshot(ROOT, args.snapshot_manifest_sha256)
        if any(getattr(m, "__file__", None) and not Path(m.__file__).resolve().is_relative_to(ROOT)
               for n, m in sys.modules.items() if n == "jevops" or n.startswith("jevops.")):
            raise ValueError("JevOps import escaped the snapshot")
        projects, bindings = json.loads(args.projects.read_text()), {}
        for pin in _pins(record):
            found = [p for p in projects if (p["repository"], p["lean_tag"], p["git_commit"]) ==
                     (record["url"], pin.lean_tag, pin.git_commit)]
            if len(found) != 1:
                raise ValueError("one prepared project for each required pin")
            bindings[pin] = project_binding(record, pin, found[0], args.elan_home)
        def resources():
            validate_volume(config)
            stat = os.statvfs(mount)
            if stat.f_bavail * stat.f_frsize < 100_000_000:
                raise ValueError("storage reserve reached; stop and retain all caches")
        report = run(plan, bindings=bindings, directory=args.output, max_processes=args.max_processes,
                     check_resources=resources)
        save(args.output / "source-binding.json", dict(before=before,
            after=verify_snapshot(ROOT, args.snapshot_manifest_sha256), max_bytes=config["max_bytes"]))
    print(json.dumps({k: report[k] for k in ("status", "native_processes", "official_score")}))
    return 2 if report["status"] == "INCOMPLETE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
