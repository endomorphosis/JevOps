"""Checked multi-step graph edit proposals with frozen, matched-budget controls.

Each policy still emits one lexical edit. The runner rechecks that raw edit and
refreshes its graph before the next decision. No alternate-candidate search,
teacher repair, evaluation updates, optimal-stop labels, or proof authority from
scores is introduced. Compiler callbacks remain trusted infrastructure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .composition_curriculum import path_states, training_rows, transfer_rows
from .expr_dag import CODEC
from .graph_curriculum import grammar_diagnostics
from .graph_policy import GraphEditPolicy, graph_context, metrics
from .graph_refinement import CompilerBudget, acceptance_gates, fit_training, shape_digest
from .proof_tokens import TOKENIZER_ID, proof_source_tokens
from .rewrite_policy import body_of
from .structural_policy import StructuralEditPolicy, digest, source_context
from .structural_training import _checked_export, _envelope, _sha

SCHEMA = "jevops-checked-graph-composition/v1"


class CheckedCompiler:
    """Bounded, per-run source cache; never treats persisted receipts as truth."""
    def __init__(self, compile_fn, *, environment_sha256, toolchain, max_compiles=128):
        if (not _sha(environment_sha256) or not isinstance(toolchain, tuple) or len(toolchain) != 2
                or any(not isinstance(v, str) or not v for v in toolchain)):
            raise ValueError("invalid composition environment/toolchain")
        self.environment, self.toolchain = environment_sha256, toolchain
        self.compiler = CompilerBudget(compile_fn, max_compiles)
        self.codec_sha = hashlib.sha256(CODEC.read_bytes()).hexdigest()
        self.states = {}

    def state(self, source):
        if not isinstance(source, str) or not 1 <= len(source.encode()) <= 65_536:
            raise ValueError("invalid composition source")
        if source not in self.states:
            declaration = _envelope(source, source)
            receipt = self.compiler(source)
            report, wire = _checked_export(receipt, source, declaration, self.environment, self.codec_sha, 4096)
            if (wire["lean_version"], wire["lean_githash"]) != self.toolchain:
                raise ValueError("composition toolchain mismatch")
            self.states[source] = {"receipt": receipt, "report": report, "wire": wire}
        return self.states[source]

    def context(self, model, source):
        if model.environment != self.environment or model.toolchain != self.toolchain:
            raise ValueError("composition model/environment mismatch")
        if not isinstance(model, (GraphEditPolicy, StructuralEditPolicy)):
            raise ValueError("unsupported composition policy")
        factory = graph_context if isinstance(model, GraphEditPolicy) else source_context
        return factory(source, self.state(source)["receipt"], environment_sha256=self.environment)

    def edge(self, source, target):
        _envelope(source, target)
        a, b = [self.state(s)["report"] for s in (source, target)]
        same = (a["type"] == b["type"] and a["export"]["level_parameters"] == b["export"]["level_parameters"]
                and set(b["export"]["axioms"]) <= set(a["export"]["axioms"]))
        nongrowing = same and all(b["proof"][k] <= a["proof"][k]
                                  for k in ("unique_expression_nodes", "expanded_expression_nodes"))
        return {"verified": same, "expression_nonregression": nongrowing,
                "strict_shortening": proof_source_tokens(target) < proof_source_tokens(source),
                "source_proof": a["proof"], "prediction_proof": b["proof"]}


def rollout(model, source, checker, *, max_edits=3):
    """Commit only checked edits; an invalid later proposal fails the whole score.

    The safe prefix is retained for inspection, never used to conceal a failed
    raw prediction. Stopping at identity or the edit budget does not certify a
    globally shortest proof. This API has no teacher/target argument.
    """
    if type(max_edits) is not int or not 1 <= max_edits <= 8:
        raise ValueError("invalid composition edit budget")
    checkpoint = digest(model.to_dict())
    checker.state(source)
    current, trace, ok, reason = source, [], True, "edit_limit"
    for step in range(max_edits):
        event = {"step": step, "source": current, "prediction": None, "committed": False}
        trace.append(event)
        try:
            context = checker.context(model, current)
            prediction = model.predict(current, context)
            event["prediction"] = prediction
            candidate, index = prediction["source"], prediction["choice"]
            if not isinstance(candidate, str) or len(candidate.encode()) > 65_536:
                raise ValueError("invalid composition candidate")
            _envelope(current, candidate)
            choices = model.rows(current, context)
            if (type(index) is not int or not 0 <= index < len(choices)
                    or body_of(candidate)[1] != choices[index]["body"]):
                raise ValueError("prediction outside frozen grammar")
            if index == 0:
                event["check"] = {"verified": True, "expression_nonregression": True, "strict_shortening": False}
                reason = "identity"
                break
            check = event["check"] = checker.edge(current, candidate)
            if not all(check[k] is True for k in ("verified", "expression_nonregression", "strict_shortening")):
                ok, reason = False, "rejected_raw_edit"
                break
            current = candidate
            event["committed"] = True
        except (ValueError, TypeError, KeyError) as exc:
            event["check"] = {"verified": False, "expression_nonregression": False,
                              "strict_shortening": False, "reason": str(exc)[:240]}
            ok, reason = False, "rejected_raw_edit"
            break
    if digest(model.to_dict()) != checkpoint:
        raise ValueError("composition changed frozen model")
    saved = proof_source_tokens(source) - proof_source_tokens(current)
    return {"ok": ok, "source": source, "final_source": current, "trace": trace, "stop_reason": reason,
            "source_tokens": proof_source_tokens(source), "final_tokens": proof_source_tokens(current),
            "safe_prefix_saved_tokens": saved, "verified_saved_tokens": saved if ok else 0,
            "valid": all(e["check"]["verified"] for e in trace),
            "cost_nonregression": all(e["check"]["expression_nonregression"] for e in trace),
            "committed_edits": sum(e["committed"] for e in trace), "max_edits": max_edits,
            "model_sha256": checkpoint, "model_unchanged": True, "teacher_used": False,
            "alternate_candidate_search": False, "minimality_proven": False}


def _teacher_losses(models, states, checker):
    """Teacher-forced adjacent CE/cosine, not a loss over a repaired rollout."""
    losses, checks = {name: [] for name in models}, []
    for source, target in zip(states, states[1:]):
        try:
            checked = checker.edge(source, target)
        except (ValueError, TypeError, KeyError) as exc:
            checked = {"verified": False, "expression_nonregression": False,
                       "strict_shortening": False, "reason": str(exc)[:240]}
        checks.append(checked)
        admitted = all(checked[k] is True for k in ("verified", "expression_nonregression", "strict_shortening"))
        for name, model in models.items():
            loss = None
            if admitted:
                try:
                    value = model.objective(source, target, checker.context(model, source))
                    if value is not None:
                        loss = metrics({k: v for k, v in value.items() if k != "gradient"})
                except (ValueError, TypeError, KeyError):
                    pass
            losses[name].append(loss)
    return losses, checks


def evaluate_composition(fit, rows, compile_fn, *, max_edits=3, max_compiles=128):
    grammar = grammar_diagnostics(fit)  # Frozen fit, admitted origins, shared bank.
    if type(max_edits) is not int or not 2 <= max_edits <= 8:
        raise ValueError("composition comparison requires 2..8 edits")
    if not isinstance(rows, list) or not 3 <= len(rows) <= 16:
        raise ValueError("invalid composition evaluation manifest")
    ids, sources, families = set(), set(), {}
    for row in rows:
        if (not isinstance(row, dict) or row.get("split") not in {"validation", "canary", "holdout"}
                or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in ids
                or not isinstance(row.get("source"), str) or row["source"] in sources
                or not isinstance(row.get("family"), str) or not row["family"]):
            raise ValueError("invalid composition evaluation row")
        if (row["family"] in fit["training_families"]
                or row["family"] in families and families[row["family"]] != row["split"]):
            raise ValueError("composition family overlap")
        ids.add(row["id"]); sources.add(row["source"]); families[row["family"]] = row["split"]
    if set(families.values()) != {"validation", "canary", "holdout"}:
        raise ValueError("all composition splits required")
    names = {"selected": fit["selected"], "fixed": "fixed_graph", "frozen": "frozen_multiscale"}
    models = {name: (StructuralEditPolicy if name == "fixed" else GraphEditPolicy).from_dict(fit["checkpoints"][arm])
              for name, arm in names.items()}
    checker = CheckedCompiler(compile_fn, environment_sha256=fit["environment_sha256"],
                              toolchain=models["selected"].toolchain, max_compiles=max_compiles)
    seen = {k: {s[k] for s in fit["training_shapes"]} for k in ("proof", "type")}
    # Source-only preflight for all rows; no labels/predictions consumed on overlap.
    for row in rows:
        shape = shape_digest(checker.state(row["source"])["wire"])
        if any(shape[k] in seen[k] for k in seen):
            raise ValueError("composition structural type/proof overlap")
        for k in seen:
            seen[k].add(shape[k])
    arms = {"selected_one": ("selected", 1), "selected_composed": ("selected", max_edits),
            "fixed_one": ("fixed", 1), "fixed_composed": ("fixed", max_edits),
            "frozen_composed": ("frozen", max_edits)}
    results = []
    for row in rows:
        runs = {arm: rollout(models[name], row["source"], checker, max_edits=budget)
                for arm, (name, budget) in arms.items()}
        # Every raw rollout for this row is committed BEFORE reading its labels.
        states = path_states(row)
        losses, checks = _teacher_losses(models, states, checker)
        results.append({"id": row["id"], "family": row["family"], "split": row["split"], "runs": runs,
                        "teacher_step_count": len(states)-1, "teacher_checks": checks, "losses": losses})
    unchanged = all(model.to_dict() == fit["checkpoints"][names[name]] for name, model in models.items())
    if not unchanged:
        raise ValueError("composition evaluation changed frozen model")

    def summarize(group, arm):
        name = arms[arm][0]
        complete = [r for r in group if all(loss is not None for loss in r["losses"][name])]
        out = {"sample_count": len(group), "loss_sample_count": len(complete),
               "valid_count": sum(r["runs"][arm]["valid"] for r in group),
               "nonregressing_count": sum(r["runs"][arm]["ok"] for r in group),
               "verified_saved_tokens": sum(r["runs"][arm]["verified_saved_tokens"] for r in group),
               "committed_edits": sum(r["runs"][arm]["committed_edits"] for r in group),
               "failed_rollouts": sum(not r["runs"][arm]["ok"] for r in group),
               "teacher_steps": sum(r["teacher_step_count"] for r in group),
               "labeled_teacher_steps": sum(loss is not None for r in group for loss in r["losses"][name])}
        for key in ("cross_entropy", "expected_cosine_loss"):
            out[key] = (sum(sum(l[key] for l in r["losses"][name])/r["teacher_step_count"] for r in complete)/len(complete)
                        if complete else None)
        return out
    summary = {arm: summarize(results, arm) for arm in arms}
    by_split = {split: {arm: summarize([r for r in results if r["split"] == split], arm) for arm in arms}
                for split in ("validation", "canary", "holdout")}
    gates = acceptance_gates(summary["selected_composed"], summary["fixed_composed"])
    split_gates = {split: acceptance_gates(stats["selected_composed"], stats["fixed_composed"])
                   for split, stats in by_split.items()}
    gates["all_splits_pass"] = all(all(g.values()) for g in split_gates.values())
    result = {"schema": SCHEMA, "ok": all(gates.values()), "freeze_sha256": fit["freeze_sha256"],
              "selected": fit["selected"], "grammar": grammar, "max_edits": max_edits, "rows": rows,
              "results": results, "summary": summary, "by_split": by_split, "gates": gates, "split_gates": split_gates,
              "models_unchanged": unchanged, "compile_attempts": checker.compiler.attempts,
              "loss_scope": "teacher_forced_adjacent_edits_mean_per_theorem_not_on_policy_sequence_loss",
              "scope": "new_layouts_shared_training_rewrite_motifs", "tokenizer_id": TOKENIZER_ID,
              "semantic_family_decontamination": False, "checkpoint_promoted": False, "official_score": None}
    result["receipt_sha256"] = digest(result)
    return result


def render_summary(fit, result):
    grammar_diagnostics(fit)
    if (result.get("schema") != SCHEMA or result.get("freeze_sha256") != fit["freeze_sha256"]
            or result.get("receipt_sha256") != digest({k: v for k, v in result.items() if k != "receipt_sha256"})):
        raise ValueError("mismatched composition receipts")
    lines = ["# Checked graph edit composition", "", "Generated from saved receipts; not fresh verification or an arena score.", "",
             f"Training-selected model: `{fit['selected']}`; {fit['epochs']} passes over {len(fit['training_rows'])} adjacent training pairs.",
             f"Grammar: {result['grammar']['template_count']} shared templates. Composition budget: {result['max_edits']} edits.", "",
             "| Arm | Raw valid / total | Failed paths | Verified saved tokens | Edit CE | Expected cosine loss |",
             "| --- | --- | --- | --- | --- | --- |"]
    fmt = lambda v: "unmeasured" if v is None else f"{v:.6g}"
    for arm in ("selected_one", "selected_composed", "fixed_one", "fixed_composed", "frozen_composed"):
        s = result["summary"][arm]
        lines.append(f"| {arm} | {s['valid_count']}/{s['sample_count']} | {s['failed_rollouts']} | {s['verified_saved_tokens']} | "
                     f"{fmt(s['cross_entropy'])} | {fmt(s['expected_cosine_loss'])} |")
    lines += ["", "| Split | Selected / fixed composed saved tokens | Selected / fixed CE | Selected / fixed cosine loss |",
              "| --- | --- | --- | --- |"]
    for split in ("validation", "canary", "holdout"):
        arms = result["by_split"][split]
        a, b = arms["selected_composed"], arms["fixed_composed"]
        lines.append(f"| {split} | {a['verified_saved_tokens']} / {b['verified_saved_tokens']} | "
                     f"{fmt(a['cross_entropy'])} / {fmt(b['cross_entropy'])} | "
                     f"{fmt(a['expected_cosine_loss'])} / {fmt(b['expected_cosine_loss'])} |")
    lines += ["", f"Gates: `{json.dumps(result['gates'], sort_keys=True)}`.",
              "CE/cosine use complete teacher-forced adjacent labels, averaged per theorem, not final-output reconstruction or on-policy sequence loss.",
              "One/composed arms reuse identical weights and loss measurements; only their rollout edit budgets differ.",
              "Invalid raw edits end the path, earn zero saved-token credit, and are not repaired using teachers or alternate candidates.",
              "Shared motifs, not semantic decontamination, global minimality, or evidence for checkpoint promotion.", ""]
    return "\n".join(lines)


def measurement_record(fit, result):
    """Small generated projection, bound to the full receipts, not proof authority."""
    render_summary(fit, result)
    statistics = {}
    for name, s in fit["statistics"].items():
        statistics[name] = {k: s[k] for k in ("config", "updates", "examples_seen")}
        for stage in ("before", "after"):
            statistics[name][stage] = {k: s[stage][k] for k in ("correct_count", "cross_entropy", "expected_cosine_loss")}
        if "encoder_changed" in s:
            statistics[name]["encoder_changed"] = s["encoder_changed"]
    observations = []
    for row in result["results"]:
        run = row["runs"]["selected_composed"]
        observations.append({**{k: row[k] for k in ("id", "family", "split", "teacher_step_count")},
                             **{k: run[k] for k in ("ok", "source_tokens", "final_tokens", "verified_saved_tokens",
                                                   "safe_prefix_saved_tokens", "committed_edits", "stop_reason")},
                             "selected_checks": [e["check"] for e in run["trace"]],
                             "teacher_checks": row["teacher_checks"]})
    record = {k: result[k] for k in ("ok", "selected", "grammar", "max_edits", "summary", "by_split", "gates",
                                    "split_gates", "models_unchanged", "loss_scope", "scope",
                                    "semantic_family_decontamination", "checkpoint_promoted", "official_score")}
    record.update(schema=SCHEMA + "/measurement", evidence_kind="saved_callback_observations_not_fresh_verification",
                  freeze_sha256=fit["freeze_sha256"], evaluation_sha256=result["receipt_sha256"],
                  epochs=fit["epochs"], seed=fit["seed"], training_statistics=statistics,
                  toolchain=fit["checkpoints"][fit["selected"]]["toolchain"], torch_version=fit["torch_version"],
                  compile_calls={"training": len(fit["compile_attempts"]), "evaluation": len(result["compile_attempts"])},
                  selected_observations=observations)
    record["measurement_sha256"] = digest(record)
    return record


def main(argv=None):
    import torch
    from .router_tuning import _lean_compiler
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--environment-sha256", required=True)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--training-seed", type=int, default=20260926)
    parser.add_argument("--transfer-seed", type=int, default=20260927)
    parser.add_argument("--max-edits", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("choose a new output directory")
    if not 2 <= args.max_edits <= 8:
        parser.error("composition comparison requires 2..8 edits")
    torch.set_num_threads(1)
    compiler = _lean_compiler(project_root=args.project_root.resolve(), use_lake=args.lake, timeout=45,
                              kernel_only=True, export_dags=True, environment_sha256=args.environment_sha256)
    fit = fit_training(compiler, rows=training_rows(args.training_seed), environment_sha256=args.environment_sha256,
                       epochs=args.epochs, seed=args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    def save(name, data):
        with (args.output_dir / name).open("x") as stream:
            json.dump(data, stream, sort_keys=True, indent=2, allow_nan=False)
    save("training.json", fit)
    if not fit["ok"]:
        print(json.dumps({"ok": False, "reason": fit["reason"], "output_dir": str(args.output_dir)}))
        return 1
    # No evaluation rows exist in this runner until the trained checkpoints freeze.
    try:
        result = evaluate_composition(fit, transfer_rows(args.transfer_seed), compiler, max_edits=args.max_edits)
    except ValueError as exc:
        failure = {"schema": SCHEMA, "ok": False, "stage": "evaluation_protocol", "reason": str(exc),
                   "freeze_sha256": fit["freeze_sha256"], "checkpoint_promoted": False, "official_score": None}
        save("failure.json", failure)
        print(json.dumps(failure))
        return 1
    save("evaluation.json", result)
    with (args.output_dir / "summary.md").open("x") as stream:
        stream.write(render_summary(fit, result))
    save("measurement.json", measurement_record(fit, result))
    print(json.dumps({"ok": result["ok"], "selected": fit["selected"], "output_dir": str(args.output_dir)}))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
