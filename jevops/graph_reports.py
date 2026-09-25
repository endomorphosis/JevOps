"""Generate graph experiment artifacts directly on disk, without printing them.

Input receipts are hash-checked observations, not new proof authority. Rendering
does not run Lean, train models, or promote checkpoints. Only a short status and
the output filenames are printed; model weights, proof trees and receipts stay
in the filesystem.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def generate_reports(input_dir, output_prefix, *, overwrite=False):
    """Validate before writing; refuse existing outputs unless explicitly asked."""
    input_dir, output_prefix = Path(input_dir), Path(output_prefix)
    fit = json.loads((input_dir / "training.json").read_text(encoding="utf-8"))
    result = json.loads((input_dir / "evaluation.json").read_text(encoding="utf-8"))
    from .graph_composition import SCHEMA as COMPOSITION
    from .graph_refinement import EVAL_SCHEMA as REFINEMENT
    if result.get("schema") == COMPOSITION:
        from .graph_composition import measurement_record, render_summary
    elif result.get("schema") == REFINEMENT:
        from .graph_curriculum import measurement_record
        from .graph_refinement import render_summary
    else:
        raise ValueError("unsupported graph report schema")
    summary = render_summary(fit, result)
    record = measurement_record(fit, result)
    measurement_path = output_prefix.with_name(output_prefix.name + "_control.json")
    summary_path = output_prefix.with_name(output_prefix.name + "_summary.md")
    artifacts = [(measurement_path, json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"),
                 (summary_path, summary)]
    for path, _ in artifacts:
        if path.is_symlink() or path.is_dir():
            raise ValueError("report output must be a regular file, not a symlink or directory")
        if path.exists() and not overwrite:
            raise FileExistsError(f"report exists: {path}; use a new prefix or --overwrite")
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    for path, contents in artifacts:
        with path.open("w" if overwrite else "x", encoding="utf-8") as stream:
            stream.write(contents)
    return {"measurement": str(measurement_path), "summary": str(summary_path),
            "evaluation_ok": result["ok"], "selected": result["selected"], "checkpoint_promoted": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True, help="directory containing training.json and evaluation.json")
    parser.add_argument("--output-prefix", type=Path, required=True, help="prefix for _control.json and _summary.md")
    parser.add_argument("--overwrite", action="store_true", help="replace only the two named generated artifacts")
    args = parser.parse_args(argv)
    try:
        status = generate_reports(args.input_dir, args.output_prefix, overwrite=args.overwrite)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"report generation failed: {exc}\n")
    print(json.dumps(status, sort_keys=True))
    # Success means rendering succeeded, not that evaluation passed its gates.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
