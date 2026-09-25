"""Training-only finite-grammar audits and native-rejection auxiliary loss.

An elaborator rejection concerns this candidate, not the truth of its theorem.
Unknown/infrastructure failures are not negative labels. Compiler callbacks are
trusted; content hashes bind their observations, not their authenticity.
"""
from __future__ import annotations

import math
import re
import textwrap

import torch

from .graph_policy import candidate_loss
from .proof_tokens import proof_source_tokens
from .rewrite_policy import body_of, choices, validate_templates
from .solver_feedback import source_digest
from .structural_policy import digest
from .structural_training import _envelope

SCHEMA = "jevops-training-candidate-audit/v1"
BAD = {"elaborator_rejected", "cost_rejected"}
KNOWN = BAD | {"accepted", "identity"}


def render_choices(source, templates):
    prefix, _ = body_of(source)
    return [(row, source if i == 0 else prefix + "\n" + textwrap.indent(row["body"], "  ") + "\n")
            for i, row in enumerate(choices(source, templates))]


def grammar_headroom(source, templates):
    """Syntactic bounds within this grammar only; no proof or global minimum."""
    rendered = render_choices(source, templates)
    lengths = [proof_source_tokens(s) for _, s in rendered]
    return {"choice_count": len(rendered), "competing_edits": max(0, len(rendered)-1),
            "source_tokens": lengths[0], "syntactic_minimum_tokens": min(lengths),
            "syntactic_saved_tokens_upper_bound": lengths[0] - min(lengths), "proof_checked": False}


def known_rfl_rejection(source, receipt):
    """Narrow, source/position-bound failure class; all other failures abstain.

    Diagnostic matching is deliberately conservative and compiler-version
    sensitive. It cannot certify a positive proof or mathematical unprovability.
    """
    try:
        declaration = _envelope(source, source)
    except (ValueError, TypeError):
        return False
    if (not isinstance(receipt, dict) or receipt.get("theorem_ok") is not False
            or receipt.get("source_sha256") != source_digest(source)
            or receipt.get("diagnostics_source_sha256") != source_digest(source)
            or receipt.get("compiled_source_sha256") != source_digest(source + f"\n#print axioms {declaration}\n")
            or receipt.get("reason") is not None):
        return False
    diagnostics = receipt.get("diagnostics")
    if not isinstance(diagnostics, list) or not 1 <= len(diagnostics) <= 256:
        return False
    errors = [d for d in diagnostics if isinstance(d, dict) and d.get("severity") == "error"]
    if len(errors) != 1:
        return False
    d = errors[0]
    message, pos, end = d.get("data"), d.get("pos"), d.get("endPos")
    if (not isinstance(message, str) or not message.startswith("Tactic `rfl` failed:")
            or re.search(r"heartbeat|recursion|timeout|memory|interrupted|unknown module", message, re.I)
            or not isinstance(pos, dict) or not isinstance(end, dict)
            or any(type(x.get(k)) is not int for x in (pos, end) for k in ("line", "column"))):
        return False
    lines = source.splitlines()
    return (1 <= pos["line"] <= len(lines) and end["line"] == pos["line"]
            and lines[pos["line"]-1].strip() == "rfl" and pos["column"] >= 0
            and lines[pos["line"]-1][pos["column"]:end["column"]] == "rfl"
            and end["column"] == pos["column"]+3)


def audit_candidates(rows, templates, checker, *, max_choices=8):
    """Compile every bounded training choice before it may affect gradients.

    All rows must be training rows; reject evaluation data before source/target
    access. The caller must first admit positive teachers and mine the grammar
    from them. Only complete audits support the rejection penalty.
    """
    if (not isinstance(rows, list) or not 1 <= len(rows) <= 16
            or any(not isinstance(r, dict) or r.get("split") != "train" for r in rows)):
        raise ValueError("candidate audits require training rows only")
    if type(max_choices) is not int or not 1 <= max_choices <= 16:
        raise ValueError("invalid candidate budget")
    templates = validate_templates(templates)
    output = []
    for row in rows:
        source = row["source"]
        state = checker.state(source)
        rendered = render_choices(source, templates)
        if len(rendered) > max_choices:
            raise ValueError("candidate budget exceeded; no partial negative labels")
        labels = [i for i, (choice, _) in enumerate(rendered) if choice["body"] == body_of(row["target"])[1]]
        if len(labels) != 1:
            raise ValueError("teacher outside frozen grammar")
        entries = []
        for index, (_, candidate) in enumerate(rendered):
            check, reason, status = None, None, "unknown"
            try:
                check = checker.edge(source, candidate)
                if check["verified"] and check["expression_nonregression"] and (index == 0 or check["strict_shortening"]):
                    status = "identity" if index == 0 else "accepted"
                elif check["verified"]:
                    status = "cost_rejected"
                else:
                    reason = "type_or_axiom_mismatch"
            except (ValueError, TypeError, KeyError) as exc:
                reason = str(exc)[:240]
                receipt = checker.compiler.cache.get(candidate)
                if known_rfl_rejection(candidate, receipt):
                    status = "elaborator_rejected"
            entries.append({"index": index, "source_sha256": source_digest(candidate),
                "tokens": proof_source_tokens(candidate), "status": status, "check": check,
                "reason": reason, "receipt_sha256": digest(checker.compiler.cache.get(candidate))})
        label = labels[0]
        usable = [e["tokens"] for e in entries if e["status"] in {"identity", "accepted"}]
        complete = (bool(usable) and all(e["status"] in KNOWN for e in entries)
                    and entries[label]["status"] == "accepted" and entries[label]["tokens"] == min(usable))
        audit = {"schema": SCHEMA, "id": row["id"], "split": "train", "complete": complete,
                 "source_sha256": source_digest(source), "target_sha256": source_digest(row["target"]),
                 "environment_sha256": checker.environment, "toolchain": list(checker.toolchain),
                 "dag_sha256": state["report"]["dag_sha256"], "grammar_sha256": digest(templates),
                 "label": label, "entries": entries, "headroom": grammar_headroom(source, templates),
                 "proof_admitted": False, "teacher_optimality": "within_audited_finite_grammar_only"}
        audit["audit_sha256"] = digest(audit)
        output.append(audit)
    return {"schema": SCHEMA + "/collection", "ok": all(a["complete"] for a in output), "rows": output,
            "evaluation_accessed": False, "model_trained": False}


def audited_loss(model, source, target, context, audit, *, split, rejection_weight=.25):
    """CE + .35 cosine + bounded probability mass on natively rejected choices.

    No differentiation through Lean and no learned semantic-equivalence claim.
    Audit masks are detached constants; the positive teacher remains mandatory.
    This low-level API trusts the caller's fresh audit provenance.
    """
    if split != "train":
        raise ValueError("audited updates require training split")
    if (type(rejection_weight) not in (int, float) or not math.isfinite(rejection_weight)
            or not 0 <= rejection_weight <= 1):
        raise ValueError("invalid rejection penalty weight")
    if (not isinstance(audit, dict) or audit.get("schema") != SCHEMA or audit.get("split") != "train"
            or audit.get("complete") is not True or audit.get("proof_admitted") is not False
            or audit.get("audit_sha256") != digest({k: v for k, v in audit.items() if k != "audit_sha256"})
            or audit.get("source_sha256") != source_digest(source) or audit.get("target_sha256") != source_digest(target)
            or audit.get("environment_sha256") != model.environment or audit.get("toolchain") != list(model.toolchain)
            or audit.get("dag_sha256") != context.dag_sha256 or audit.get("grammar_sha256") != digest(model.templates)):
        raise ValueError("stale, mismatched or incomplete candidate audit")
    _envelope(source, target)
    rendered = render_choices(source, model.templates)
    entries = audit["entries"]
    if (not isinstance(entries, list) or len(entries) != len(rendered)
            or any(not isinstance(e, dict) or e.get("index") != i or type(e.get("index")) is not int
                   or e.get("status") not in KNOWN or e.get("source_sha256") != source_digest(s)
                   or type(e.get("tokens")) is not int or e.get("tokens") != proof_source_tokens(s)
                   for i, (e, (_, s)) in enumerate(zip(entries, rendered)))):
        raise ValueError("candidate audit ordering or coverage mismatch")
    rows, logits = model.logits(source, context)
    loss = candidate_loss(logits, rows, body_of(target)[1])
    if type(audit["label"]) is not int or audit["label"] != loss["label"] or entries[loss["label"]]["status"] != "accepted":
        raise ValueError("audit label is not an admitted teacher")
    mask = logits.new_tensor([float(e["status"] in BAD) for e in entries])
    mass = (logits.softmax(0) * mask).sum()
    return {**loss, "supervised_total": loss["total"], "rejected_probability_mass": mass,
            "total": loss["total"] + rejection_weight * mass}
