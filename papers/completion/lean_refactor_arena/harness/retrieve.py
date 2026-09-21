#!/usr/bin/env python3
"""Premise retrieval from the other 14 warm-up JSONL proofs plus src lemmas.

Warm-up v1 retrieval is only:

- the other 14 public JSONL records (never the query itself);
- lemma names mentioned in the current ``src`` via regex on ``simp [`` /
  ``rw [`` / the identifier after ``exact`` / ``apply``.

Src lemmas are capped at 16. This is not a Lean parser, not lake-wide
ingest, and not a ``CorpusManifest`` of Mathlib. No embeddings, no Jev, no
invented scores. Loop v2 / PR-6 deferred path; not a scored Arena run.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
REPO_ROOT = HERE.parents[3]
WARMUP_JSONL = PAPER_ROOT / "data" / "benchmark_data_warmup.jsonl"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import splice as lra_splice  # noqa: E402

FROZEN_WARMUP_SHA256 = lra_splice.FROZEN_WARMUP_SHA256
WARMUP_N = lra_splice.WARMUP_N
NEIGHBOR_N = WARMUP_N - 1
SRC_LEMMA_CAP = 16
PROMPT_HEAD_CHARS = 400

FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "fcntl",
        "LeanstralProofProvider",
        "leanstral_proof_provider",
        "CorpusManifest",
        "TheoremEntry",
        "GoalFeatures",
        "PremiseSelectionWeights",
        "PremiseSelectionResult",
        "select_premises",
        "select_premises_for_theorem",
        "premise_selection",
        "ipfs_datasets",
        "ipfs_datasets_py",
    }
)
FORBIDDEN_CORPUS_ATTRS = frozenset(
    {
        "CorpusManifest",
        "TheoremEntry",
        "GoalFeatures",
        "select_premises",
        "select_premises_for_theorem",
        "register_source",
        "ingest",
    }
)

# Character-class ident; not a Lean parser. Allows Unicode (ι) and dotted names.
_IDENT = re.compile(
    r"(?:[^\W\d])(?:[\w'])*(?:\.(?:[^\W\d])(?:[\w'])*)*",
    re.UNICODE,
)
_SIMP_RW_OPEN = re.compile(
    r"\b(?P<tactic>simp(?:_all|_rw)?(?:\s+only)?|rw!?|erw)\s*\[",
    re.UNICODE,
)
_EXACT_APPLY_OPEN = re.compile(
    r"\b(?P<tactic>exact'?|apply'?)\b\s*",
    re.UNICODE,
)
# Binders / tactic modifiers, not theorem names. Compared case-insensitively.
_STOPWORDS = frozenset(
    {
        "forall",
        "exists",
        "fun",
        "let",
        "in",
        "if",
        "then",
        "else",
        "do",
        "match",
        "with",
        "end",
        "where",
        "open",
        "import",
        "using",
        "from",
        "as",
        "return",
        "case",
        "of",
        "by",
        "have",
        "show",
        "this",
        "sorry",
        "admit",
        "at",
        "only",
        "all",
        "try",
        "first",
        "focus",
        "repeat",
        "skip",
        "next",
        "intro",
        "intros",
        "cases",
        "constructor",
        "refine",
        "apply",
        "exact",
        "simp",
        "rw",
        "erw",
        "simp_all",
        "simp_rw",
        "true",
        "false",
        "and",
        "or",
        "not",
        "some",
        "none",
        "generalizing",
        "hiding",
        "renaming",
        "calc",
        "suffices",
        "obtain",
        "rcases",
        "rintro",
        "all_goals",
        "any_goals",
    }
)


class RetrieveError(RuntimeError):
    """Fail-closed warm-up retrieval error."""


class UnknownProblem(RetrieveError):
    """The requested JSONL name is not in the frozen warm-up set."""


from jevops.lean import NeighborProof
from jevops.lean import Retrieval
from jevops.tactics import SrcLemma


def sha256_bytes(data: bytes) -> str:
    from jevops.outer import digest_hex

    return digest_hex(data)


def sha256_file(path: Path) -> str:
    from jevops.outer import digest_file

    return digest_file(path)


def load_warmup_records(path: Optional[Path] = None) -> tuple[bytes, str, list[dict[str, Any]]]:
    """Load the frozen warm-up JSONL through the LRA-011 splice bind."""

    return lra_splice.load_warmup_records(path)


def _tactic_family(opener: str) -> str:
    from jevops.outer import token_family

    return token_family(
        opener,
        prefixes=("simp", "exact", "apply"),
        aliases={"rw": "rw", "erw": "rw"},
    )


def _bracket_inner(text: str, open_end: int) -> str:
    """Take the substring of a ``[…]`` list by character depth. Not a Lean parser."""

    from jevops.mask import bracket_inner

    return bracket_inner(text, open_end)


def _keep_ident(name: str) -> bool:
    from jevops.pick import keep_token

    return keep_token(name, stopwords=_STOPWORDS, min_len=2)


def extract_src_lemmas(src: str, *, cap: int = SRC_LEMMA_CAP) -> tuple[tuple[SrcLemma, ...], int]:
    """Regex-extract lemma idents from ``simp [`` / ``rw [`` / ``exact`` / ``apply``.

    Does not parse Lean. Unique names, first-occurrence order, then cap.
    """

    from jevops.tactics import extract_src_lemmas as _fn

    return _fn(src, cap=cap, error_cls=RetrieveError)


def jsonl_neighbors(
    records: Sequence[Mapping[str, Any]],
    query_name: str,
) -> tuple[NeighborProof, ...]:
    """Return the other 14 warm-up proofs in JSONL order. Never the query."""

    from jevops.lean import jsonl_neighbors as _fn

    return _fn(
        records,
        query_name,
        expected_n=WARMUP_N,
        neighbor_n=NEIGHBOR_N,
        error_cls=RetrieveError,
        unknown_cls=UnknownProblem,
        head_chars=PROMPT_HEAD_CHARS,
    )


def lemma_id_digest(query: str, neighbor_names: Sequence[str], lemma_names: Sequence[str]) -> str:
    """Content digest of retrieved lemma ids. Not a score."""

    from jevops.lean import lemma_id_digest as _fn

    return _fn(query, neighbor_names, lemma_names, cap=SRC_LEMMA_CAP, neighbor_n=NEIGHBOR_N)


def retrieve_record(record: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> Retrieval:
    from jevops.lean import retrieve_record as _fn

    return _fn(
        record,
        records,
        expected_n=WARMUP_N,
        neighbor_n=NEIGHBOR_N,
        lemma_cap=SRC_LEMMA_CAP,
        error_cls=RetrieveError,
        unknown_cls=UnknownProblem,
        head_chars=PROMPT_HEAD_CHARS,
    )


def retrieve_by_name(
    name: str,
    records: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    path: Optional[Path] = None,
) -> Retrieval:
    from jevops.outer import lookup_named

    if records is None:
        _, _, records = load_warmup_records(path)
    record = lookup_named(records, name)
    if record is None:
        raise UnknownProblem(f"unknown warm-up problem: {name}")
    return retrieve_record(record, records)


def prompt_neighbors(retrieval: Retrieval, *, k: int = 4) -> list[dict[str, str]]:
    """TypeSafe neighbor slice from the design: name / statement[:400] / proof_head."""

    from jevops.lean import prompt_neighbors as _fn

    return _fn(retrieval, k=k)


def retrieval_view(retrieval: Retrieval, *, src_chars: int = PROMPT_HEAD_CHARS) -> dict[str, Any]:
    """JSON view with truncated proofs. Full ``src`` stays on the dataclass."""

    from jevops.lean import retrieval_view as _fn

    return _fn(retrieval, src_chars=src_chars, lemma_cap=SRC_LEMMA_CAP)


def _imported_names(source: str) -> set[str]:
    from jevops.repair import imported_names

    return imported_names(source)


def _attr_names(source: str) -> set[str]:
    from jevops.repair import attr_names

    return attr_names(source)


def _call_func_names(source: str) -> set[str]:
    from jevops.repair import call_func_names

    return call_func_names(source)


def _numeric_score_assignments(source: str) -> list[str]:
    """Flag invented numeric scores. ``arena_score = None`` is allowed."""

    from jevops.repair import score_assignments

    return score_assignments(source, ("score", "relevance_score", "arena_score", "official_score"))


def _synthetic_cap_fixture() -> dict[str, Any]:
    names = [f"Lemma_{index:02d}" for index in range(20)]
    src = "theorem T : True := by\n  simp [" + ", ".join(names) + "]\n  exact Lemma_00\n  apply ExtraIdent"
    lemmas, uncapped = extract_src_lemmas(src, cap=SRC_LEMMA_CAP)
    lemma_names = [item.name for item in lemmas]
    return {
        "uncapped": uncapped,
        "returned": len(lemmas),
        "names": lemma_names,
        "first": lemma_names[0] if lemma_names else "",
        "last": lemma_names[-1] if lemma_names else "",
        "includes_extra_apply": "ExtraIdent" in lemma_names,
        "tactics": sorted({item.tactic for item in lemmas}),
        "capped_at_16": len(lemmas) == SRC_LEMMA_CAP and lemma_names == names[:SRC_LEMMA_CAP],
        "uncapped_has_all_twenty_plus_extra": uncapped == 21,
    }


def _record_report(record: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    from jevops.lean import pack_retrieval_report

    retrieval = retrieve_record(record, records)
    return pack_retrieval_report(
        retrieval,
        records=records,
        lemma_cap=SRC_LEMMA_CAP,
        prompt_neighbors=prompt_neighbors(retrieval),
        asdict_fn=asdict,
    )


def self_check(path: Optional[Path] = None) -> dict[str, Any]:
    """Retrieve 14 JSONL neighbors + src lemmas for all 15 records. No compile."""

    from jevops.outer import read_text

    source = read_text(__file__)
    jsonl = Path(path) if path is not None else WARMUP_JSONL
    before = sha256_file(jsonl)
    raw, digest, records = load_warmup_records(jsonl)
    per_record = [_record_report(record, records) for record in records]
    after = sha256_file(jsonl)
    imported = _imported_names(source)
    forbidden_imports = sorted(name for name in imported if name in FORBIDDEN_IMPORT_NAMES)
    corpus_attrs = sorted(name for name in _attr_names(source) if name in FORBIDDEN_CORPUS_ATTRS)
    call_names = _call_func_names(source)
    score_issues = _numeric_score_assignments(source)
    uses_lock_ex = any(
        isinstance(node, ast.Attribute) and node.attr == "LOCK_EX" for node in ast.walk(ast.parse(source))
    )
    uses_subprocess = "subprocess" in imported
    cap_fixture = _synthetic_cap_fixture()

    all_names = [str(record.get("name") or "") for record in records]
    neighbor_cover = all(item["neighbors_are_the_other_fourteen"] and item["self_excluded"] for item in per_record)
    full_src = all(item["full_src_retrieved"] and item["prefix_bind_neighbors"] for item in per_record)
    lemmas_ok = all(item["lemmas_mentioned_in_src"] and item["src_lemma_cap_held"] for item in per_record)
    has_simp = any(item["has_simp"] for item in per_record)
    has_rw = any(item["has_rw"] for item in per_record)
    has_exact = any(item["has_exact"] for item in per_record)
    no_scores = all(
        item["arena_score"] is None and item["score"] is None and item["relevance_score"] is None
        for item in per_record
    )
    no_manifest = all(item["corpus_manifest_ingest"] is False and item["mathlib_ingest"] is False for item in per_record)
    n_neighbors_ok = all(item["n_neighbors"] == NEIGHBOR_N for item in per_record)
    unknown_closed = False
    try:
        retrieve_by_name("not-a-warmup-problem", records)
    except UnknownProblem:
        unknown_closed = True

    report = {
        "ok": True,
        "n_records": len(records),
        "n_neighbors_per_query": NEIGHBOR_N,
        "src_lemma_cap": SRC_LEMMA_CAP,
        "frozen_warmup_sha256": FROZEN_WARMUP_SHA256,
        "warmup_jsonl_sha256": digest,
        "jsonl_bytes": len(raw),
        "jsonl_unchanged": before == after == FROZEN_WARMUP_SHA256,
        "names": all_names,
        "neighbor_cover_all": neighbor_cover,
        "n_neighbors_all_14": n_neighbors_ok,
        "full_neighbor_proofs_retrieved": full_src,
        "src_lemmas_from_simp_rw_exact_apply": lemmas_ok,
        "has_simp_lemma": has_simp,
        "has_rw_lemma": has_rw,
        "has_exact_lemma": has_exact,
        "cap_fixture": cap_fixture,
        "unknown_name_fail_closed": unknown_closed,
        "imported_names": sorted(imported),
        "forbidden_imports": forbidden_imports,
        "corpus_manifest_attrs": corpus_attrs,
        "called_select_premises": "select_premises" in call_names or "select_premises_for_theorem" in call_names,
        "uses_fcntl": "fcntl" in imported,
        "uses_lock_ex": uses_lock_ex,
        "uses_subprocess": uses_subprocess,
        "numeric_score_assignments": score_issues,
        "no_invented_scores": no_scores and not score_issues,
        "no_corpus_manifest_ingest": no_manifest and not forbidden_imports and not corpus_attrs,
        "records": per_record,
        "compiled": False,
        "lake": False,
        "llama_server_started": False,
        "arena_score": None,
        "score": None,
        "warmup_path": str(jsonl.relative_to(REPO_ROOT)),
        "protocol": "LRA/v1",
        "loop": "v2-deferred-retrieve-only",
    }
    report["ok"] = bool(
        report["n_records"] == WARMUP_N
        and report["jsonl_unchanged"]
        and neighbor_cover
        and n_neighbors_ok
        and full_src
        and lemmas_ok
        and has_simp
        and has_rw
        and has_exact
        and cap_fixture["capped_at_16"]
        and unknown_closed
        and not forbidden_imports
        and not corpus_attrs
        and not report["called_select_premises"]
        and not report["uses_fcntl"]
        and not uses_lock_ex
        and not uses_subprocess
        and no_scores
        and not score_issues
        and no_manifest
        and report["compiled"] is False
        and report["lake"] is False
        and report["arena_score"] is None
        and report["score"] is None
    )
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true", help="retrieve all 15 records; no compile")
    parser.add_argument("--retrieve", action="store_true", help="retrieve one warm-up problem by --name")
    parser.add_argument("--name", default="", help="JSONL problem name")
    parser.add_argument("--jsonl", type=Path, default=None, help="warmup JSONL path (default: frozen file)")
    parser.add_argument(
        "--src-chars",
        type=int,
        default=PROMPT_HEAD_CHARS,
        help="truncate neighbor statement/src in JSON output (full src is still retrieved)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.retrieve:
        if not args.name:
            parser.error("--retrieve requires --name")
        try:
            retrieval = retrieve_by_name(args.name, path=args.jsonl)
        except RetrieveError as exc:
            from jevops.outer import failed_check, print_json

            print_json(failed_check(exc, score=None, corpus_manifest_ingest=False))
            return 1
        from jevops.outer import print_json

        print_json(retrieval_view(retrieval, src_chars=args.src_chars))
        return 0
    if args.self_check or argv is None or argv == []:
        from jevops.outer import print_ok

        return print_ok(self_check(args.jsonl))
    parser.error("choose --self-check or --retrieve")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
