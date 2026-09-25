"""Verified multi-rule graph curriculum; no evaluation-driven rule mining.

This expands the available edit grammar, not the Lean kernel or proof authority.
Source/teacher pairs are proposals until fit_training admits both endpoints.
The original two-choice experiments and checkpoints remain unchanged.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import textwrap

from .rewrite_policy import body_of, choices, mine_template, validate_templates
from .structural_policy import digest

CURRICULUM = "jevops-multirule-graph-curriculum/v1"


def _seed(seed):
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("invalid curriculum seed")


def _row(seed, split, family, builder):
    nonce = random.Random(f"{seed}:{split}:{family}").randrange(10**8)
    names = {word: f"{word}_{nonce}"
             for word in ("p", "q", "r", "h", "f", "g", "n", "m", "a", "b", "c", "z", "flag")}
    header, before, after = builder(names)
    name = f"multi_{split}_{family}_{names['n'].split('_')[-1]}"
    prefix = f"theorem {name} {header} := by\n"
    render = lambda body: prefix + textwrap.indent(body, "  ") + "\n"
    return {"id": name, "split": split, "family": family, "source": render(before), "target": render(after)}


def _alias(s):
    return f"have {s['a']} := {s['h']}\nhave {s['b']} := {s['a']}\nhave {s['c']} := {s['b']}\nexact {s['c']}"


def training_rows(seed=20260924):
    """Five training proposals, four templates, including a competing-choice pair.

    Non-reflexive equality gets a real shorter copy target rather than an identity
    label. No inspected transfer or holdout rows are imported or relabeled.
    """
    _seed(seed)
    specs = [
        ("alias_hypothesis", lambda s: (f"({s['p']} : Prop) ({s['h']} : {s['p']}) : {s['p']}",
                                         _alias(s), f"exact {s['h']}")),
        ("alias_reflexive", lambda s: (f"({s['n']} : Nat) ({s['h']} : {s['n']} = {s['n']}) : {s['n']} = {s['n']}",
                                        _alias(s), "rfl")),
        ("alias_nonreflexive", lambda s: (f"({s['n']} {s['m']} : Nat) ({s['h']} : {s['n']} = {s['m']}) : {s['n']} = {s['m']}",
                                           _alias(s), f"exact {s['h']}")),
        ("application", lambda s: (f"({s['p']} {s['q']} : Prop) ({s['f']} : {s['p']} → {s['q']}) ({s['h']} : {s['p']}) : {s['q']}",
                                    f"apply {s['f']}\nexact {s['h']}", f"exact {s['f']} {s['h']}")),
        ("eta", lambda s: (f"({s['p']} {s['q']} : Prop) ({s['f']} : {s['p']} → {s['q']}) : {s['p']} → {s['q']}",
                            f"intro {s['h']}\nexact {s['f']} {s['h']}", f"exact {s['f']}")),
    ]
    return [_row(seed, "train", family, build) for family, build in specs]


def transfer_rows(seed=20260925):
    """New enclosing layouts for the training motifs, not new mathematics.

    Call only after freezing checkpoints. Targets are evaluation references, not
    new rules, solver output, globally minimal proofs or training supervision.
    """
    _seed(seed)
    specs = [
        ("validation", "introduced_chain", lambda s: (f"({s['p']} {s['q']} : Prop) : {s['p']} → {s['q']} → {s['p']}",
            f"intro {s['h']}\nintro {s['g']}\n" + _alias(s), f"intro {s['h']}\nintro {s['g']}\nexact {s['h']}")),
        ("validation", "nested_application", lambda s: (
            f"({s['p']} {s['q']} {s['r']} : Prop) ({s['f']} : {s['p']} → {s['q']}) ({s['g']} : {s['q']} → {s['r']}) ({s['h']} : {s['p']}) : {s['r']}",
            f"apply {s['g']}\napply {s['f']}\nexact {s['h']}", f"apply {s['g']}\nexact {s['f']} {s['h']}")),
        ("canary", "branch_chain", lambda s: (
            f"({s['p']} : Prop) ({s['h']} : {s['p']}) ({s['flag']} : Bool) : {s['p']}",
            f"cases {s['flag']}\ncase false =>\n" + textwrap.indent(_alias(s), "  ") + f"\ncase true => exact {s['h']}",
            f"cases {s['flag']}\ncase false =>\n  exact {s['h']}\ncase true => exact {s['h']}")),
        ("canary", "prefixed_eta", lambda s: (
            f"({s['p']} {s['q']} : Prop) ({s['f']} : {s['p']} → {s['q']}) : Bool → {s['p']} → {s['q']}",
            f"intro {s['flag']}\nintro {s['h']}\nexact {s['f']} {s['h']}", f"intro {s['flag']}\nexact {s['f']}")),
        ("holdout", "beta_equality", lambda s: (
            f"({s['n']} : Nat) ({s['h']} : ((fun {s['z']} : Nat => {s['z']}) {s['n']}) = {s['n']}) : ((fun {s['z']} : Nat => {s['z']}) {s['n']}) = {s['n']}",
            _alias(s), "rfl")),
        ("holdout", "order_hypothesis", lambda s: (
            f"({s['n']} {s['m']} : Nat) ({s['h']} : {s['n']} < {s['m']}) : {s['n']} < {s['m']}",
            _alias(s), f"exact {s['h']}")),
        ("holdout", "negation_application", lambda s: (
            f"({s['p']} : Prop) ({s['f']} : ¬ {s['p']}) ({s['h']} : {s['p']}) : False",
            f"apply {s['f']}\nexact {s['h']}", f"exact {s['f']} {s['h']}")),
    ]
    return [_row(seed, split, family, build) for split, family, build in specs]


def grammar_diagnostics(fit):
    """Explain which verified training pairs minted each template.

    Does not compile candidates, change labels, or inspect any evaluation rows.
    Pair admission and callback authenticity remain the fitter's responsibility.
    """
    from .graph_refinement import FIT_SCHEMA
    if (not isinstance(fit, dict) or fit.get("schema") != FIT_SCHEMA or fit.get("ok") is not True
            or fit.get("freeze_sha256") != digest({k: v for k, v in fit.items() if k != "freeze_sha256"})):
        raise ValueError("invalid frozen curriculum fit")
    if any(row.get("split") != "train" for row in fit["training_rows"]):
        raise ValueError("grammar diagnostics require training-only rows")
    templates = validate_templates(fit["checkpoints"][fit["selected"]]["templates"])
    if any(state["templates"] != templates for state in fit["checkpoints"].values()):
        raise ValueError("comparison arms use different grammars")
    origins = {rule["id"]: [] for rule in templates}
    for pair in fit["training_pairs"]["pairs"]:
        if pair.get("split") != "train" or pair.get("teacher_admitted") is not True:
            raise ValueError("unadmitted grammar provenance")
        rule = mine_template(pair["text"], body_of(pair["target_text"])[1])
        if rule is None or rule["id"] not in origins:
            raise ValueError("missing training rule provenance")
        origins[rule["id"]].append(pair["id"])
    if any(not ids for ids in origins.values()):
        raise ValueError("rule without verified training origin")
    rows = []
    for row in fit["training_rows"]:
        candidates = choices(row["source"], templates)
        label = [i for i, c in enumerate(candidates) if c["body"] == body_of(row["target"])[1]]
        if len(label) != 1:
            raise ValueError("teacher outside frozen grammar")
        rows.append({"id": row["id"], "family": row["family"], "choice_count": len(candidates),
                     "target_choice": label[0], "identity_target": label[0] == 0,
                     "rule_ids": [c["rule_id"] for c in candidates]})
    return {"schema": CURRICULUM, "template_count": len(templates), "templates_sha256": digest(templates),
            "training_origins": origins, "rows": rows, "teacher_optimality_proven": False,
            "frozen_grammar_shared_across_arms": True}


def measurement_record(fit, evaluation):
    """Compact, deterministic receipt projection, not a new verification pass."""
    from .graph_refinement import render_summary
    render_summary(fit, evaluation)  # Check receipt hashes and matching freeze.
    grammar = grammar_diagnostics(fit)
    training = {}
    for arm, stats in fit["statistics"].items():
        training[arm] = {k: stats[k] for k in ("config", "updates", "examples_seen")}
        for stage in ("before", "after"):
            training[arm][stage] = {k: stats[stage][k] for k in (
                "correct_count", "cross_entropy", "expected_cosine_loss")}
        if "encoder_changed" in stats:
            training[arm]["encoder_changed"] = stats["encoder_changed"]
    observations = []
    for row in evaluation["results"]:
        if row["arm"] != fit["selected"]:
            continue
        observation = {k: row[k] for k in (
            "id", "family", "split", "source_tokens", "prediction_tokens", "verified_saved_tokens")}
        observation.update({"choice": row["prediction"]["choice"],
                            "teacher_choice": row["loss"]["label"] if row["loss"] else None,
                            "check": row["check"], "teacher_check": row["teacher_check"]})
        observations.append(observation)
    result = {"schema": CURRICULUM + "/measurement", "ok": evaluation["ok"],
              "evidence_kind": "saved_callback_observations_not_fresh_verification",
              "freeze_sha256": fit["freeze_sha256"], "evaluation_sha256": evaluation["receipt_sha256"],
              "toolchain": fit["checkpoints"][fit["selected"]]["toolchain"],
              "torch_version": fit["torch_version"], "seed": fit["seed"], "epochs": fit["epochs"],
              "selected": fit["selected"], "grammar": grammar, "training_statistics": training,
              "compile_calls": {"training": len(fit["compile_attempts"]),
                                "evaluation": len(evaluation["compile_attempts"])},
              "summary": evaluation["summary"], "by_split": evaluation["by_split"],
              "gates": evaluation["gates"], "split_gates": evaluation["split_gates"],
              "selected_observations": observations, "models_unchanged": evaluation["models_unchanged"],
              "scope": evaluation["scope"], "semantic_family_decontamination": False,
              "checkpoint_promoted": False, "official_score": None}
    result["measurement_sha256"] = digest(result)
    return result


def main(argv=None):
    # Optional graph extra stays out of ordinary package import paths.
    import torch
    from .graph_refinement import evaluate_frozen, fit_training, render_summary
    from .router_tuning import _lean_compiler
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--environment-sha256", required=True)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--training-seed", type=int, default=20260924)
    parser.add_argument("--transfer-seed", type=int, default=20260925)
    parser.add_argument("--frozen-fit", type=Path,
                        help="reuse trusted training.json without updates; ignores epochs/seed/training-seed")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("choose a new output directory")
    torch.set_num_threads(1)
    compiler = _lean_compiler(project_root=args.project_root.resolve(), use_lake=args.lake, timeout=45,
                              kernel_only=True, export_dags=True, environment_sha256=args.environment_sha256)
    if args.frozen_fit:
        fit = json.loads(args.frozen_fit.read_text())
        grammar_diagnostics(fit)
        if fit["environment_sha256"] != args.environment_sha256:
            parser.error("frozen training environment mismatch")
    else:
        fit = fit_training(compiler, rows=training_rows(args.training_seed), environment_sha256=args.environment_sha256,
                           epochs=args.epochs, seed=args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir / "training.json").open("x") as stream:
        json.dump(fit, stream, sort_keys=True, indent=2, allow_nan=False)
    if not fit["ok"]:
        print(json.dumps({"ok": False, "reason": fit["reason"], "output_dir": str(args.output_dir)}))
        return 1
    diagnostics = grammar_diagnostics(fit)
    with (args.output_dir / "grammar.json").open("x") as stream:
        json.dump(diagnostics, stream, sort_keys=True, indent=2, allow_nan=False)
    # Selection/checkpoints/grammar are saved before generating evaluation cases.
    try:
        evaluation = evaluate_frozen(fit, transfer_rows(args.transfer_seed), compiler)
    except ValueError as exc:
        # Invalid manifests/protocol failures are not zero-length successes.
        failure = {"schema": CURRICULUM, "ok": False, "stage": "evaluation_protocol",
                   "reason": str(exc), "freeze_sha256": fit["freeze_sha256"],
                   "transfer_seed": args.transfer_seed, "checkpoint_promoted": False, "official_score": None}
        with (args.output_dir / "failure.json").open("x") as stream:
            json.dump(failure, stream, sort_keys=True, indent=2, allow_nan=False)
        print(json.dumps(failure))
        return 1
    with (args.output_dir / "evaluation.json").open("x") as stream:
        json.dump(evaluation, stream, sort_keys=True, indent=2, allow_nan=False)
    with (args.output_dir / "summary.md").open("x") as stream:
        stream.write(render_summary(fit, evaluation))
    with (args.output_dir / "measurement.json").open("x") as stream:
        json.dump(measurement_record(fit, evaluation), stream, sort_keys=True, indent=2, allow_nan=False)
    print(json.dumps({"ok": evaluation["ok"], "selected": fit["selected"],
                      "template_count": diagnostics["template_count"], "output_dir": str(args.output_dir)}))
    return 0 if evaluation["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
