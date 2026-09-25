"""Generate bounded synthetic DuckDB ingestion/retrieval measurements.

Not an Arena benchmark, proof test, or evidence of whole-library scalability.
Artifacts are retained. No models, native Lean, network, or extensions are used.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import statistics
import time

from .arena import content_hash
from .duckdb_ingest import INGESTION_MODES, validate_ingestion_mode
from .knowledge_index import DATABASE_CONFIG, KnowledgeIndex, _file_hash, build_index
from .premise_search import Premise, PremiseScope, bounded_int

SCHEMA = "jevops-duckdb-synthetic-ingestion-probe/v1"
COMPARISON_SCHEMA = "jevops-duckdb-ingestion-comparison/v1"
MIN_FREE_BYTES = 640 * 1024 * 1024


def _name(i: int) -> str:
    return f"Probe.fact_{i:06d}"


def measure(directory: Path, *, records: int, queries: int = 16,
            ingestion_mode: str = "columnar") -> dict:
    validate_ingestion_mode(ingestion_mode)
    bounded_int(records, 1, 8192)
    bounded_int(queries, 1, 128)
    path = Path(directory) / f"premises-{records}.duckdb"
    environment = content_hash({"probe_schema": SCHEMA, "environment": "synthetic-no-Lean"})
    source = content_hash({"probe_schema": SCHEMA, "records": records})
    scope = PremiseScope(source, environment, tuple(_name(i) for i in range(records)))
    corpus = (Premise(_name(i), "List Nat → List Nat", "synthetic-probe",
                      dependencies=(_name(i - 1),) if i else ()) for i in range(records))
    start = time.perf_counter()
    artifact = build_index(path, corpus, environment_sha256=environment, source_sha256=source,
                           ingestion_mode=ingestion_mode)
    build_seconds = time.perf_counter() - start
    timings, failures, retrieval = [], [], []
    start = time.perf_counter()
    with KnowledgeIndex(path, expected_sha256=artifact.file_sha256) as index:
        open_seconds = time.perf_counter() - start
        for i in range(queries):
            name = _name((i * 997) % records)
            start = time.perf_counter()
            result = index.search(name, target="Probe.target", scope=scope, top_k=1)
            timings.append((time.perf_counter() - start) * 1000)
            retrieval.append(result)
            names = [hit["premise"]["name"] for hit in result["matches"]]
            if result["status"] != "RANKED" or names != [name]:
                failures.append({"query": name, "status": result["status"], "returned_names": names})
        broad = index.search("Nat", target="Probe.target", scope=scope, max_scan=min(records, 64))
        expected_broad = "SCAN_BUDGET" if records > 64 else "RANKED"
        if broad["status"] != expected_broad:
            failures.append({"query": "Nat", "status": broad["status"], "expected_status": expected_broad})
        identity = dict(index.identity)
    return {"schema": SCHEMA, "status": "PASS" if not failures else "FAIL",
            "synthetic": True, "proof_verified": False, "official_score": None,
            "ingestion_mode": ingestion_mode,
            "retrieval_sha256": content_hash({"exact": retrieval, "broad": broad}),
            "artifact": asdict(artifact), "identity": identity, "records": records,
            "build_seconds": build_seconds, "build_records_per_second": records / build_seconds,
            "open_and_hash_seconds": open_seconds, "bytes_per_record": artifact.size_bytes / records,
            "queries": queries, "query_ms_median": statistics.median(timings),
            "query_ms_max": max(timings), "query_ms": timings,
            "broad_query_status": broad["status"], "failures": failures}


def compare_ingestion(directory: Path, *, records: int, queries: int = 16, rounds: int = 3) -> dict:
    """Matched inputs, alternating order, retained artifacts and per-arm receipts.

    Not cold-process trials or a hard storage reservation. Check free space before
    each build (128 MiB headroom plus 512 MiB reserve); stop rather than evict.
    Errors and storage stops remain explicit, without a partial speedup claim.
    """
    bounded_int(records, 1, 8192)
    bounded_int(queries, 1, 128)
    bounded_int(rounds, 1, 5)
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    runs, failures = [], []
    status = "PASS"
    for round_index in range(rounds):
        order = ("executemany", "columnar") if round_index % 2 == 0 else ("columnar", "executemany")
        for mode in order:
            free_bytes = shutil.disk_usage(directory).free
            if free_bytes < MIN_FREE_BYTES:
                status = "STORAGE_STOP"
                failures.append({"round": round_index, "mode": mode, "status": status,
                                 "free_bytes": free_bytes, "required_free_bytes": MIN_FREE_BYTES})
                break
            run_dir = directory / f"round-{round_index}-{mode}"
            run_dir.mkdir()
            try:
                result = measure(run_dir, records=records, queries=queries, ingestion_mode=mode)
            except Exception as exc:
                result = {"status": "ERROR", "ingestion_mode": mode, "proof_verified": False,
                          "error_type": type(exc).__name__, "error": str(exc)}
            result["round"] = round_index
            _write_report(run_dir / "report.json", result)
            runs.append(result)
            if result["status"] != "PASS":
                failures.append({"round": round_index, "mode": mode, "status": result["status"]})
                status = "FAIL"
                break
        if status != "PASS":
            break
    complete = len(runs) == 2 * rounds and all(r["status"] == "PASS" for r in runs)
    parity = complete and len({(r["artifact"]["snapshot_sha256"], r["retrieval_sha256"])
                               for r in runs}) == 1
    if complete and not parity:
        status = "FAIL"
        failures.append({"status": "SEMANTIC_PARITY_FAILURE"})
    medians = {mode: statistics.median(r["build_seconds"] for r in runs if r["ingestion_mode"] == mode)
               for mode in INGESTION_MODES} if parity else None
    payload = {"schema": COMPARISON_SCHEMA, "status": status, "records": records,
               "rounds": rounds, "queries_per_run": queries, "runs": runs, "failures": failures,
               "complete": complete, "semantic_parity": parity,
               "build_seconds_median": medians,
               "columnar_build_speedup": medians["executemany"] / medians["columnar"] if medians else None,
               "database_config": DATABASE_CONFIG,
               "minimum_free_bytes_before_build": MIN_FREE_BYTES,
               "implementation_sha256": {name: _file_hash(Path(__file__).with_name(name)) for name in
                   ("knowledge_probe.py", "knowledge_index.py", "duckdb_ingest.py", "premise_search.py")},
               "proof_verified": False, "official_score": None,
               "limitation": "synthetic same-process trials; alternating order; no RSS/peak-disk, real-corpus or Lean score claim"}
    _write_report(directory / "report.json", payload)
    return payload


def _write_report(path: Path, payload: dict) -> None:
    with path.open("x") as stream:
        json.dump(payload, stream, indent=2, allow_nan=False)
        stream.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new directory; all artifacts retained")
    parser.add_argument("--records", type=int, nargs="+", default=[64, 512])
    parser.add_argument("--queries", type=int, default=16)
    parser.add_argument("--ingestion-mode", choices=INGESTION_MODES, default="columnar")
    parser.add_argument("--compare-ingestion", action="store_true")
    parser.add_argument("--rounds", type=int, default=3, help="comparison rounds, alternating mode order")
    args = parser.parse_args(argv)
    if len(args.records) > 8 or len(set(args.records)) != len(args.records):
        parser.error("one to eight distinct corpus sizes required")
    for count in args.records:
        bounded_int(count, 1, 8192)
    bounded_int(args.queries, 1, 128)
    bounded_int(args.rounds, 1, 5)
    args.output.mkdir(exist_ok=False)
    if args.compare_ingestion:
        reports = []
        for count in args.records:
            result = compare_ingestion(args.output / f"records-{count}", records=count,
                                       queries=args.queries, rounds=args.rounds)
            reports.append(result)
            if result["status"] != "PASS":
                break
        status = "PASS" if len(reports) == len(args.records) and all(r["status"] == "PASS" for r in reports) else reports[-1]["status"]
        _write_report(args.output / "report.json", {"schema": COMPARISON_SCHEMA, "status": status,
                      "requested_sizes": args.records, "results": reports, "proof_verified": False})
        for result in reports:
            print(f"{result['records']} records: {result['status']}; parity={result['semantic_parity']}; "
                  f"build speedup={result['columnar_build_speedup']}")
        return int(status != "PASS")
    reports = [measure(args.output, records=count, queries=args.queries, ingestion_mode=args.ingestion_mode)
               for count in args.records]
    payload = {"schema": SCHEMA, "results": reports,
               "status": "PASS" if all(r["status"] == "PASS" for r in reports) else "FAIL",
               "limitation": "synthetic corpus, single process, no proof or Arena score claim"}
    _write_report(args.output / "report.json", payload)
    for report in reports:
        print(f"{report['records']} records: {report['status']}; "
              f"build={report['build_seconds']:.3f}s; "
              f"size={report['artifact']['size_bytes']}B; "
              f"query median={report['query_ms_median']:.2f}ms; "
              f"broad={report['broad_query_status']}")
    return int(payload["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
