"""Freshly checked, training-only source/target DAG pairs for rewrite learning.

The compiler callback and split manifest are trusted infrastructure, not model
output. Saved receipts cannot authorize new pairs. This is a bridge for the
existing sparse edit learner and future graph models, not a trained graph model.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Mapping, Sequence

from . import autoencoder as ae
from .expr_dag import CODEC, _bytes, root_summaries
from .proof_tokens import TOKENIZER_ID, proof_source_tokens
from .proof_trust import STANDARD_AXIOMS, top_level_declarations
from .rewrite_policy import body_of, supported
from .solver_feedback import source_digest

SCHEMA = "jevops-structural-training-pairs/v1"
SPLITS = {"train", "validation", "canary", "holdout"}


def _sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _envelope(source: str, target: str) -> str:
    prefix, body = body_of(source)
    target_prefix, target_body = body_of(target)
    if not prefix or prefix != target_prefix or not supported(body) or not supported(target_body):
        raise ValueError("changed_or_unsupported_envelope")
    if re.search(r"\?|(?<![\w'])_(?![\w'])|--|/-|-/|[\"`#$\x00]", prefix):
        raise ValueError("ambiguous_theorem_envelope")
    declarations = top_level_declarations(source)
    if len(declarations) != 1 or top_level_declarations(target) != declarations:
        raise ValueError("single_theorem_required")
    start = re.search(r"(?m)^[ \t]*(?:theorem|lemma)\s", prefix)
    if start is None:
        raise ValueError("unsupported_theorem_header")
    # The lexical IR marker must be the theorem body, not `:= by` inside a
    # binder default. Abstain on delimiter ambiguity instead of editing a header.
    stack = []
    for char in prefix[start.start():]:
        if char in "([{":
            stack.append(char)
        elif char in ")]}":
            if not stack or stack.pop() != {")": "(", "]": "[", "}": "{"}[char]:
                raise ValueError("ambiguous_theorem_envelope")
    if stack or ":=" in prefix[start.start():].rsplit(":=", 1)[0]:
        raise ValueError("ambiguous_theorem_envelope")
    # No uncounted helper definitions, axioms, attributes or option changes.
    for line in prefix[:start.start()].splitlines():
        if line.strip() and not re.fullmatch(r"[ \t]*(?:import|universe)\s+[\w'. ]+", line):
            raise ValueError("unsupported_theorem_prelude")
    if re.search(r"\b(?:axiom|def|instance|attribute|set_option|unsafe|elab|macro|syntax)\b", prefix[start.start():]):
        raise ValueError("unsupported_theorem_header")
    return declarations[0]


def _checked_export(receipt: Mapping[str, Any], source: str, declaration: str,
                    environment: str, codec_sha: str, node_budget: int) -> tuple[dict, dict]:
    if not isinstance(receipt, Mapping) or receipt.get("theorem_ok") is not True:
        raise ValueError("unverified_compilation")
    compiled = source + f"\n#print axioms {declaration}\n"
    if (receipt.get("source_sha256") != source_digest(source)
            or receipt.get("compiled_source_sha256") != source_digest(compiled)):
        raise ValueError("source_binding_mismatch")
    audit = receipt.get("kernel_audit")
    if (not isinstance(audit, Mapping) or audit.get("accepted") is not True
            or audit.get("schema") != "jevops-axiom-audit/v1"
            or audit.get("declarations") != [declaration]
            or audit.get("allowed_axioms") != sorted(STANDARD_AXIOMS)
            or any(audit.get(k) != [] for k in ("missing_reports", "conflicting_reports", "unexpected_axioms"))):
        raise ValueError("invalid_axiom_audit")
    axioms = audit.get("axioms")
    if not isinstance(axioms, list) or any(not isinstance(a, str) or a not in STANDARD_AXIOMS for a in axioms):
        raise ValueError("forbidden_axioms")
    report = receipt.get("expression_dag")
    if (not isinstance(report, Mapping) or report.get("ok") is not True
            or report.get("schema") != "jevops-lean-expr-export/v1"
            or report.get("declaration") != declaration
            or report.get("kernel_typechecked") is not True
            or report.get("exact_roundtrip") is not True
            or report.get("proof_admitted") is not False
            or report.get("dependency_closure_verified") is not False
            or report.get("dependency_environment_sha256") != environment
            or report.get("codec_sha256") != codec_sha
            or not isinstance(report.get("axioms"), list)
            or sorted(report["axioms"]) != sorted(axioms)
            or not isinstance(report.get("level_parameters"), list)):
        raise ValueError("unverified_or_mismatched_export")
    artifacts = report.get("artifact_files_sha256")
    if (not isinstance(artifacts, dict) or "Main.olean" not in artifacts
            or not set(artifacts) <= {"Main.olean", "Main.olean.private", "Main.olean.server"}
            or not all(_sha(value) for value in artifacts.values())):
        raise ValueError("invalid_artifact_binding")
    binding = {k: report[k] for k in ("dependency_environment_sha256", "dependency_closure_verified",
                                     "proof_admitted", "artifact_files_sha256", "codec_sha256")}
    wire = report.get("dag")
    if not isinstance(wire, dict) or len(wire.get("roots", [])) != 2:
        raise ValueError("proof_and_type_roots_required")
    expected_environment = hashlib.sha256(_bytes(binding)).hexdigest()
    summaries = root_summaries(wire, environment=expected_environment, node_budget=node_budget)
    dag_sha = hashlib.sha256(_bytes(wire)).hexdigest()
    if report.get("dag_sha256") != dag_sha:
        raise ValueError("DAG_digest_mismatch")
    return ({"dag_sha256": dag_sha, "proof": summaries[0], "type": summaries[1],
             "export": {k: v for k, v in report.items() if k not in {"dag", "storage"}}}, wire)


def collect_structural_pairs(rows: Sequence[Mapping[str, Any]], targets: Mapping[str, str], *,
                             compile_fn: Callable[[str], Mapping[str, Any]], environment_sha256: str,
                             max_pairs: int = 32, node_budget: int = 50_000,
                             byte_budget: int = 67_108_864) -> dict[str, Any]:
    """Recompile strict training improvements and return ready-to-coerce examples.

    Non-training targets are never accessed or compiled. Identity controls are
    reported separately, not relabeled compression. Caller owns split provenance
    and the dependency fingerprint; hashes are bindings, not authentication.
    Rejected pairs never enter ``pairs``/``graphs``. ``ok`` requires complete
    admission of all nonidentity training proposals and at least one pair.
    """
    if (not _sha(environment_sha256) or type(max_pairs) is not int or not 1 <= max_pairs <= 64
            or type(node_budget) is not int or not 1 <= node_budget <= 100_000
            or type(byte_budget) is not int or not 1 <= byte_budget <= 67_108_864):
        raise ValueError("invalid structural collection budget/environment")
    if not 1 <= len(rows) <= 128 or not isinstance(targets, Mapping):
        raise ValueError("invalid structural manifest")
    ids, sources = set(), set()
    for row in rows:
        if (not isinstance(row, Mapping) or not isinstance(row.get("id"), str) or not row["id"]
                or len(row["id"]) > 256 or row.get("split") not in SPLITS
                or not isinstance(row.get("source"), str) or len(row["source"].encode()) > 65_536):
            raise ValueError("invalid structural manifest row")
        source_id = source_digest(" ".join(row["source"].split()))
        if row["id"] in ids or source_id in sources:
            raise ValueError("duplicate/leaking structural manifest")
        ids.add(row["id"])
        sources.add(source_id)
    if not set(targets) <= ids:
        raise ValueError("target outside manifest")
    count = sum(row["split"] == "train" for row in rows)
    if not 1 <= count <= max_pairs:
        raise ValueError("training pair count budget")
    # No caching of saved receipts: each pair is checked in this call.
    codec_sha = hashlib.sha256(CODEC.read_bytes()).hexdigest()
    pairs, decisions, graphs, calls, used_bytes = [], [], {}, 0, 0
    for row in rows:
        decision = {"id": row["id"], "split": row["split"], "status": "excluded_split"}
        decisions.append(decision)
        if row["split"] != "train":
            continue
        source = row["source"]
        try:
            target = targets.get(row["id"])
            if not isinstance(target, str) or len(target.encode()) > 65_536:
                raise ValueError("missing_or_oversized_target")
            decision.update(source_sha256=source_digest(source), target_sha256=source_digest(target))
            declaration = _envelope(source, target)
            if source == target:
                decision["status"] = "identity_control_not_compression"
                continue
            a, b = proof_source_tokens(source), proof_source_tokens(target)
            if not b < a:
                raise ValueError("not_strictly_source_shorter")
            target_ir = ae.encode_lean_ir(target)
            if body_of(ae.decode_lean_ir(target_ir))[1] != body_of(target)[1]:
                raise ValueError("target_tactic_IR_roundtrip_mismatch")
            exports, wires = [], []
            for text in (source, target):
                calls += 1
                receipt = compile_fn(text)
                report, wire = _checked_export(receipt, text, declaration, environment_sha256, codec_sha, node_budget)
                exports.append(report)
                wires.append(wire)
            before, after = exports
            decision.update(source_tokens=a, target_tokens=b,
                            source_proof=before["proof"], target_proof=after["proof"])
            if any(wires[0][key] != wires[1][key] for key in ("lean_version", "lean_githash")):
                raise ValueError("toolchain_mismatch")
            if (before["type"]["structure_sha256"] != after["type"]["structure_sha256"]
                    or before["export"]["level_parameters"] != after["export"]["level_parameters"]):
                raise ValueError("elaborated_type_mismatch")
            if not set(after["export"]["axioms"]) <= set(before["export"]["axioms"]):
                raise ValueError("axiom_dependency_growth")
            if any(after["proof"][key] > before["proof"][key]
                   for key in ("unique_expression_nodes", "expanded_expression_nodes")):
                raise ValueError("proof_expression_growth")
            additions = {r["dag_sha256"]: w for r, w in zip(exports, wires) if r["dag_sha256"] not in graphs}
            size = sum(len(_bytes(w)) for w in additions.values())
            if used_bytes + size > byte_budget:
                raise ValueError("dataset_byte_budget")
            pair = {"id": row["id"], "parent_id": row["id"], "split": "train", "text": source,
                    "target_text": target, "target_ir": target_ir,
                    "source_sha256": source_digest(source), "target_sha256": source_digest(target),
                    "source_tokens": a, "target_tokens": b, "source": before, "target": after,
                    "expression_nonregression": True, "teacher_admitted": True}
            pair["pair_sha256"] = hashlib.sha256(_bytes(pair)).hexdigest()
            pairs.append(pair)
            graphs.update(additions)
            used_bytes += size
            decision.update(status="accepted", pair_sha256=pair["pair_sha256"])
        except Exception as exc:
            # A timeout, malformed callback or exhausted budget is an abstention,
            # never an identity/compression label. Interrupts still propagate.
            decision.update(status="rejected", reason=str(exc)[:240], error_type=type(exc).__name__)
    return {"schema": SCHEMA, "ok": bool(pairs) and not any(d["status"] == "rejected" for d in decisions),
            "pairs": pairs, "graphs": graphs, "decisions": decisions, "compile_calls": calls,
            "accepted_count": len(pairs), "train_proposal_count": count, "graph_bytes": used_bytes,
            "tokenizer_id": TOKENIZER_ID, "dependency_environment_sha256": environment_sha256,
            "admission_policy": "strict_source_tokens_nongrowing_expression_nodes_no_new_axioms",
            "dependency_closure_verified": False, "semantic_family_decontamination": False,
            "manifest_sha256": hashlib.sha256(_bytes(list(rows))).hexdigest(),
            "graph_model_trained": False, "checkpoint_promoted": False, "official_score": None}
