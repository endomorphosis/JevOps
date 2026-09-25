"""Read-only expression metrics from the exact compiled .olean artifact."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import subprocess
from typing import Any

INSPECTOR = Path(__file__).with_name("lean") / "ExprMetrics.lean"
MARKER = "JEVOPS_EXPR_METRICS:"


def inspect_olean(*, directory: Path, declaration: str, source: str, project_root: Path,
                  use_lake: bool = False, timeout: float = 30, node_budget: int = 50_000) -> dict[str, Any]:
    """Diagnostics only: a missing metric must never turn into an accepted proof."""
    from .proof_trust import _NAME
    if type(node_budget) is not int or not 1 <= node_budget <= 100_000 or not _NAME.fullmatch(declaration):
        raise ValueError("invalid expression metric request")
    cmd = (["lake", "env", "lean"] if use_lake else ["lean"]) + ["--run", str(INSPECTOR),
           str(directory), "Main", declaration, str(node_budget)]
    binding = {"source_sha256": hashlib.sha256(source.encode()).hexdigest()}
    try:
        binding["inspector_sha256"] = hashlib.sha256(INSPECTOR.read_bytes()).hexdigest()
        files = [directory / ("Main.olean" + suffix) for suffix in ("", ".private", ".server")]
        artifacts = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
        if "Main.olean" not in artifacts:
            raise ValueError("missing compiled theorem artifact")
        binding["artifact_files_sha256"] = artifacts
        binding["artifact_sha256"] = hashlib.sha256(json.dumps(artifacts, sort_keys=True).encode()).hexdigest()
        run = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, timeout=timeout, check=False)
        lines = [s[len(MARKER):] for s in run.stdout.splitlines() if s.startswith(MARKER)]
        if run.returncode or len(lines) != 1 or len(run.stdout) > 1_048_576:
            return {"ok": False, "reason": "inspector_failed", "stdout_tail": run.stdout[-500:],
                    "stderr_tail": run.stderr[-500:], **binding}
        report = json.loads(lines[0])
        if artifacts != {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}:
            raise ValueError("compiled artifacts changed during inspection")
        if report.get("schema") != "jevops-expr-metrics/v1" or report.get("declaration") != declaration:
            raise ValueError("expression metric identity mismatch")
        for key in ("proof", "type"):
            nodes = report[key]["unique_structural_nodes"]
            if report[key]["closed"] is not True or type(nodes) is not int or not 1 <= nodes <= node_budget:
                raise ValueError("invalid expression metric")
        return {"ok": True, **report, **binding, "node_budget": node_budget}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "reason": type(exc).__name__, **binding}


def compare_proofs(source, prediction, compile_fn):
    """Keep validity, source size and expression size as separate decisions."""
    from .proof_tokens import proof_source_tokens, TOKENIZER_ID
    from .rewrite_policy import body_of
    from .solver_feedback import _accepted, source_digest
    prefix, _ = body_of(source)
    if not prefix or body_of(prediction)[0] != prefix or re.search(r"\?|(?<![\w'])_(?![\w'])", prefix):
        raise ValueError("proof metric comparison changed theorem envelope")
    receipts = {"source": compile_fn(source), "prediction": compile_fn(prediction)}
    measured = True
    for key, text in (("source", source), ("prediction", prediction)):
        receipt = receipts[key]
        metric = receipt.get("proof_metrics") or {}
        measured = measured and (_accepted(receipt) and metric.get("ok") is True
                    and metric.get("source_sha256") == source_digest(text)
                    and sorted(metric.get("axioms", [])) == sorted(receipt["kernel_audit"].get("axioms", [])))
    source_tokens, prediction_tokens = proof_source_tokens(source), proof_source_tokens(prediction)
    nonregressing = None
    if measured:
        a, b = (receipts[k]["proof_metrics"]["proof"] for k in ("source", "prediction"))
        if a["tree_nodes"] is not None and b["tree_nodes"] is not None:
            nonregressing = b["unique_structural_nodes"] <= a["unique_structural_nodes"] and b["tree_nodes"] <= a["tree_nodes"]
    return {"ok": bool(measured), "tokenizer_id": TOKENIZER_ID, "source": source, "prediction": prediction,
            "source_tokens": source_tokens, "prediction_tokens": prediction_tokens, "receipts": receipts,
            "expression_nonregression": nonregressing,
            "source_and_expression_improvement": bool(measured and nonregressing and prediction_tokens < source_tokens),
            "independent_kernel_verifier_used": False, "global_minimum": False}
