#!/usr/bin/env python3
"""Characterize the frozen Lean Refactor Arena warm-up JSONL.

Does not score refactors. Writes warmup_summary.json, a LaTeX table, and an
import receipt. The SHA-256 of data/benchmark_data_warmup.jsonl must match the
frozen digest recorded in the receipt.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSONL = ROOT / "data" / "benchmark_data_warmup.jsonl"
SUMMARY = ROOT / "data" / "warmup_summary.json"
TABLE = ROOT / "manuscript" / "warmup_table.tex"
RECEIPT = ROOT / "evidence" / "import_receipt.json"
FROZEN_SHA256 = "6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804"
SOURCE_URL = (
    "https://delta-lab-ai-lean-refactor-arena.hf.space/gradio_api/file="
    "/tmp/gradio/3389f2fbc0397df3689218ee1bc68f1c47c0721bae28e0e7aaa5a5ea503b4e94/"
    "benchmark_data_warmup.jsonl"
)
ARENA_SPACE = "https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena"
WORKSHOP = "https://vericodegen.github.io/"
ARENA_SITE = "https://leanrefactor.github.io/"

DISPLAY_NAMES = {
    "CallElimCorrect.substOldPostSubset": "substOldPostSubset",
    "CallElimCorrect.extractedOldExprInVars": "extractedOldExprInVars",
    "Core.InitsUpdatesComm": "InitsUpdatesComm",
    "fundamental_theorem_of_variational_calculus'": "var. calculus FT",
    "Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema": "time-deriv E extrema",
    "FieldSpecification.WickAlgebra.\u03b9_timeOrderF_superCommuteF_eq_time": "iota time-order",
    "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress": "Fsub.Typing.progress",
    "Cslib.SKI.parallelReduction_diamond": "parallelReduction diamond",
    "Cslib.CCS.bisimilarity_congr_choice": "bisimilarity congr choice",
    "Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius": "fiberwise unique-dec.",
    "Binius.BinaryBasefold.fold_advances_evaluation_poly": "fold advances eval poly",
    "interleaved_affine_gaps_imply_tensor_gaps": "interleaved affine gaps",
    "putnam_1964_a4": "putnam_1964_a4",
    "putnam_1964_b2": "putnam_1964_b2",
    "putnam_1995_a3": "putnam_1995_a3",
}

SOURCE_LABEL = {
    "strata": "Strata",
    "physlib": "PhysLib",
    "cslib": "CSLib",
    "arklib": "ArkLib",
    "putnambench": "Putnam",
}


def tex_escape(value: str) -> str:
    return (
        value.replace("\\", "\\textbackslash{}")
        .replace("_", "\\_")
        .replace("%", "\\%")
        .replace("&", "\\&")
        .replace("#", "\\#")
    )


def lean_versions(record: dict) -> list[str]:
    versions = []
    for item in record.get("version_info") or []:
        if isinstance(item, dict) and item:
            versions.append(next(iter(item.keys())))
        elif isinstance(item, str):
            versions.append(item)
    return versions


def load_records() -> tuple[bytes, str, list[dict]]:
    raw = JSONL.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != FROZEN_SHA256:
        raise SystemExit(f"warmup JSONL hash mismatch: {digest} != {FROZEN_SHA256}")
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    return raw, digest, records


def problem_row(record: dict) -> dict:
    versions = lean_versions(record)
    return {
        "name": record["name"],
        "source": record["source"],
        "file_path": record.get("file_path") or "",
        "url": record.get("url") or "",
        "num_lines": record["num_lines"],
        "proof_length": record["proof_length"],
        "src_chars": len(record.get("src") or ""),
        "statement_chars": len(record.get("statement") or ""),
        "has_header": bool((record.get("header") or "").strip()),
        "start_line": record.get("start_line"),
        "end_line": record.get("end_line"),
        "n_toolchains": len(versions),
        "lean_versions": versions,
    }


def write_table(problems: list[dict]) -> None:
    lines = [
        r"\begin{tabular}{llrrl}",
        r"  \toprule",
        r"  Source & Theorem (short) & Lines & Tokens & Toolchains \\",
        r"  \midrule",
    ]
    for problem in problems:
        display = DISPLAY_NAMES.get(problem["name"], problem["name"].split(".")[-1])
        lines.append(
            "  {source} & \\texttt{{{name}}} & {lines} & {tokens} & {n} \\\\".format(
                source=SOURCE_LABEL.get(problem["source"], problem["source"]),
                name=tex_escape(display),
                lines=problem["num_lines"],
                tokens=problem["proof_length"],
                n=problem["n_toolchains"],
            )
        )
    lines.extend([r"  \bottomrule", r"\end{tabular}", ""])
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    TABLE.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    raw, digest, records = load_records()
    problems = [problem_row(record) for record in records]
    lengths = [p["proof_length"] for p in problems]
    lines = [p["num_lines"] for p in problems]
    src_chars = [p["src_chars"] for p in problems]
    summary = {
        "schema": "lean-refactor-arena-warmup-summary/v1",
        "source_url": SOURCE_URL,
        "arena_space": ARENA_SPACE,
        "arena_site": ARENA_SITE,
        "workshop": WORKSHOP,
        "sha256": digest,
        "bytes": len(raw),
        "n_problems": len(problems),
        "n_jsonl_fields": 12,
        "sources": dict(Counter(p["source"] for p in problems)),
        "proof_length_min": min(lengths),
        "proof_length_max": max(lengths),
        "proof_length_mean": round(statistics.mean(lengths), 1),
        "num_lines_min": min(lines),
        "num_lines_max": max(lines),
        "num_lines_mean": round(statistics.mean(lines), 1),
        "src_chars_min": min(src_chars),
        "src_chars_max": max(src_chars),
        "src_chars_mean": round(statistics.mean(src_chars), 1),
        "n_with_repo_url": sum(1 for p in problems if p["url"]),
        "n_putnam_without_path": sum(
            1 for p in problems if p["source"] == "putnambench" and not p["file_path"]
        ),
        "problems": problems,
        "arena_scores_claimed": False,
        "refactoring_run_executed": False,
        "official_track2_run_executed": False,
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_table(problems)
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        json.dumps(
            {
                "schema": "lean-refactor-arena-import/v1",
                "imported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source_url": SOURCE_URL,
                "arena_space": ARENA_SPACE,
                "workshop": WORKSHOP,
                "local_path": "papers/completion/lean_refactor_arena/data/benchmark_data_warmup.jsonl",
                "sha256": digest,
                "bytes": len(raw),
                "n_problems": len(problems),
                "gradio_tmp_url_ephemeral": True,
                "frozen_copy_authoritative": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"ok {len(problems)} problems sha256={digest}")


if __name__ == "__main__":
    main()
