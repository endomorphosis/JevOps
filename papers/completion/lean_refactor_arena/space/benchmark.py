"""Benchmark of theorems with reference proof lengths.

Loaded at import time from `benchmark_data_warmup.jsonl` (sitting next to
this module). The current file is the *warm-up development subset*; the full
benchmark will be released on Nov 1, 2026.

Each JSONL row has:
  - name:          unique theorem id (matches user JSONL `name`)
  - source:        which corpus the row comes from
                   (strata | physlib | cslib | arklib | putnambench)
  - statement:     theorem statement WITHOUT the `:=` and proof body. Used to
                   verify submissions don't change what is being proved.
  - src:           original full theorem (statement + proof body)
  - proof_length:  token count of the reference proof (denominator for
                   reduction %)
  - num_lines:     line count of the reference proof
  - header:        imports + options for standalone rows (PutnamBench);
                   "" for project-resident rows, which compile in place
                   inside their repository
  - file_path:     path of the source file inside its repository
                   ("" for PutnamBench)
  - url:           repository URL ("" for PutnamBench)
  - start_line / end_line: location of the declaration in file_path
                   (absent for PutnamBench)
  - version_info:  list of {version: commit_hash} pairs — the toolchains this
                   row is evaluated against. For project rows the hashes are
                   commits of the source repository; for PutnamBench rows the
                   versions are Mathlib release tags (v4.25.0 / v4.26.0 /
                   v4.27.0) and the hashes are mathlib4 commits.

Reference heartbeat counts (where already measured) live in
`benchmark_heartbeats.jsonl`; rows without an entry simply don't contribute a
heartbeat denominator yet.

To change the benchmark, edit `benchmark_data_warmup.jsonl` and rebuild the
image.
"""

from __future__ import annotations

import json
from pathlib import Path


_DATA_PATH = Path(__file__).resolve().parent / "benchmark_data_warmup.jsonl"
_HEARTBEATS_PATH = Path(__file__).resolve().parent / "benchmark_heartbeats.jsonl"

# Display names + repo links for each corpus in the benchmark.
SOURCES: dict[str, dict[str, str]] = {
    "strata": {
        "label": "Strata",
        "url": "https://github.com/strata-org/Strata",
        "blurb": "AWS's mechanized program-verification framework.",
    },
    "physlib": {
        "label": "PhysLib",
        "url": "https://github.com/leanprover-community/physlib",
        "blurb": "Formalized physics in Lean, on top of Mathlib.",
    },
    "cslib": {
        "label": "CSLib",
        "url": "https://github.com/leanprover/cslib",
        "blurb": "The Lean community's computer-science library.",
    },
    "arklib": {
        "label": "ArkLib",
        "url": "https://github.com/Verified-zkEVM/ArkLib",
        "blurb": "Formally verified cryptographic arguments for zkVMs.",
    },
    "putnambench": {
        "label": "PutnamBench",
        "url": "https://github.com/trishullab/PutnamBench",
        "blurb": "Formalized Putnam competition mathematics.",
    },
}


def _load_heartbeats() -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    if not _HEARTBEATS_PATH.exists():
        return out
    with _HEARTBEATS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            name = entry.get("name")
            if not name:
                continue
            hb = entry.get("heartbeat")
            out[name] = int(hb) if isinstance(hb, (int, float)) else None
    return out


def _load() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not _DATA_PATH.exists():
        return out
    heartbeats = _load_heartbeats()
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            name = entry.get("name")
            if not name:
                continue
            out[name] = {
                "source": entry.get("source", ""),
                "original_proof_length": int(entry.get("proof_length", 0)),
                "original_heartbeats": heartbeats.get(name),
                "num_lines": int(entry.get("num_lines", 0)),
                "header": entry.get("header", ""),
                "statement": entry.get("statement", ""),
                "src": entry.get("src", ""),
                "file_path": entry.get("file_path", ""),
                "url": entry.get("url", ""),
                "start_line": entry.get("start_line"),
                "end_line": entry.get("end_line"),
                "version_info": entry.get("version_info", []),
            }
    return out


BENCHMARK: dict[str, dict] = _load()


def benchmark_names() -> list[str]:
    return list(BENCHMARK.keys())


def original_length(name: str) -> int | None:
    entry = BENCHMARK.get(name)
    return entry["original_proof_length"] if entry else None


def original_heartbeats(name: str) -> int | None:
    entry = BENCHMARK.get(name)
    return entry.get("original_heartbeats") if entry else None


def benchmark_signature(name: str) -> str | None:
    """The statement a submission must reproduce (no `:=`, no proof body)."""
    entry = BENCHMARK.get(name)
    return entry["statement"] if entry else None


def benchmark_header(name: str) -> str | None:
    entry = BENCHMARK.get(name)
    return entry["header"] if entry else None


def benchmark_src(name: str) -> str | None:
    entry = BENCHMARK.get(name)
    return entry["src"] if entry else None


def benchmark_source(name: str) -> str | None:
    """Corpus key (strata | physlib | cslib | arklib | putnambench)."""
    entry = BENCHMARK.get(name)
    return entry.get("source") if entry else None


def benchmark_versions(name: str) -> list[str]:
    """Lean toolchain versions this row is evaluated against."""
    entry = BENCHMARK.get(name)
    if not entry:
        return []
    return [v for pair in entry.get("version_info", []) for v in pair.keys()]


def benchmark_file_link(name: str) -> str | None:
    """Best-effort GitHub link to the declaration, or None."""
    entry = BENCHMARK.get(name)
    if not entry or not entry.get("url") or not entry.get("file_path"):
        return None
    link = f"{entry['url']}/blob/main/{entry['file_path']}"
    if entry.get("start_line"):
        link += f"#L{entry['start_line']}"
        if entry.get("end_line"):
            link += f"-L{entry['end_line']}"
    return link
