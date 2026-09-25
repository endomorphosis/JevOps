"""Bounded elaborator observations and conservative goal-dependency analysis.

This is neither an open-state decoder nor proof admission. The native exporter
and its source/imports are trusted executable code; fingerprints are not signatures.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import tempfile
import time
from typing import Any

from .expr_dag import _bytes, _metadata, _name, _nat, _string

EXPORTER = Path(__file__).with_name("lean") / "ProofState.lean"
MARKER = b"JEVOPS_PROOF_STATE:"
LEGACY_STATE_SCHEMA = "jevops-open-proof-state/v1"
STATE_SCHEMA = "jevops-open-proof-state/v2"
TRACE_SCHEMA = "jevops-proof-state-trace/v1"
MAX_BYTES = 16_777_216
MAX_SOURCE_BYTES = 1_048_576
MAX_NODES = 20_000
MAX_EVENTS = 256


def _fields(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError("invalid object fields")


def _array(value, limit):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("array budget or type")
    return value


def _id(value):
    _name(value)
    if not value:
        raise ValueError("anonymous variable identity")
    return _bytes(value).decode()


def _acyclic(edges):
    # Iterative DFS: hostile chains must not exhaust Python recursion.
    done, active = set(), set()
    for root in edges:
        stack = [(root, False)]
        while stack:
            key, leaving = stack.pop()
            if leaving:
                active.remove(key)
                done.add(key)
            elif key not in done:
                if key in active:
                    raise ValueError("cyclic assignment")
                active.add(key)
                stack.append((key, True))
                stack.extend((dep, False) for dep in edges[key] if dep in edges)


def analyze_state(state: dict[str, Any], *, node_budget: int = 4096) -> dict[str, Any]:
    """Validate a structural observation and group coupled active goals.

    Includes dependencies in all local types, transparent let values and local instances, plus
    transitive metavariable declarations/assignments and universe assignments.
    V2 represents opaque nondependent have values explicitly as null; like Lean,
    they are typed variables, never definitions or independent proof receipts.
    V1 retains its historical strict raw-value validation for compatibility.
    May over-group; components are scheduling hints, not permission to replay
    arbitrary tactics independently. No semantic equality or typecheck is done.
    """
    if type(node_budget) is not int or not 1 <= node_budget <= MAX_NODES:
        raise ValueError("invalid node budget")
    _fields(state, "schema goals expressions levels metavariables universe_metavariables depth level_assign_depth")
    if state["schema"] not in (STATE_SCHEMA, LEGACY_STATE_SCHEMA) or len(_bytes(state)) > MAX_BYTES:
        raise ValueError("state schema or byte budget")
    _nat(state["depth"])
    _nat(state["level_assign_depth"])
    exprs, levels = _array(state["expressions"], node_budget), _array(state["levels"], node_budget)
    if len(exprs) + len(levels) > node_budget:
        raise ValueError("graph node budget")
    mrows = _array(state["metavariables"], 256)
    urows = _array(state["universe_metavariables"], 256)
    mvars, uvars = {}, {}
    for rows, target in ((mrows, mvars), (urows, uvars)):
        for row in rows:
            if not isinstance(row, dict) or "id" not in row:
                raise ValueError("missing variable identity")
            key = _id(row["id"])
            if key in target:
                raise ValueError("duplicate variable declaration")
            target[key] = row
    goals = [_id(g) for g in _array(state["goals"], 64)]
    if len(set(goals)) != len(goals) or not set(goals) <= mvars.keys():
        raise ValueError("duplicate or undeclared goal")

    ldeps, lchildren, lheights, seen = [], [], [], set()
    for i, row in enumerate(levels):
        if not isinstance(row, list) or not row or not isinstance(row[0], str):
            raise ValueError("invalid universe row")
        tag, children, deps = row[0], [], set()
        if tag == "zero" and len(row) == 1:
            pass
        elif tag in {"param", "mvar"} and len(row) == 2:
            _name(row[1])
            if tag == "mvar":
                key = _id(row[1])
                if key not in uvars:
                    raise ValueError("undeclared universe metavariable")
                deps.add(key)
        elif (tag == "succ" and len(row) == 2) or (tag in {"max", "imax"} and len(row) == 3):
            children = [_nat(r, i) for r in row[1:]]
        else:
            raise ValueError("invalid universe constructor")
        for j in children:
            deps.update(ldeps[j])
        height = 1 + max((lheights[j] for j in children), default=0)
        key = _bytes(row)
        if height > 128 or key in seen:
            raise ValueError("universe depth or duplicate node")
        seen.add(key)
        ldeps.append(deps)
        lchildren.append(children)
        lheights.append(height)

    # Each expression carries syntactic fvar, mvar and level-mvar dependencies.
    fs, ms, us, needs, heights, children_table, level_table, seen = [], [], [], [], [], [], [], set()
    for i, row in enumerate(exprs):
        if not isinstance(row, list) or not row or not isinstance(row[0], str):
            raise ValueError("invalid expression row")
        tag, children, universes, f, m, u, need = row[0], [], [], set(), set(), set(), 0
        if tag == "bvar" and len(row) == 2:
            need = _nat(row[1], 65536) + 1
        elif tag in {"fvar", "mvar"} and len(row) == 2:
            key = _id(row[1])
            if tag == "fvar":
                f.add(key)
            elif key in mvars:
                m.add(key)
            else:
                raise ValueError("undeclared expression metavariable")
        elif tag == "sort" and len(row) == 2:
            universes = [_nat(row[1], len(levels))]
        elif tag == "const" and len(row) == 3:
            _name(row[1])
            universes = [_nat(j, len(levels)) for j in _array(row[2], 256)]
        elif tag == "app" and len(row) == 3:
            children = [_nat(j, i) for j in row[1:]]
        elif tag in {"lam", "forall"} and len(row) == 5:
            _name(row[1])
            if row[2] not in ("explicit", "implicit", "strictImplicit", "instance"):
                raise ValueError("invalid binder")
            children = [_nat(j, i) for j in row[3:]]
        elif tag == "let" and len(row) == 6 and type(row[2]) is bool:
            _name(row[1])
            children = [_nat(j, i) for j in row[3:]]
        elif tag == "nat" and len(row) == 2:
            _nat(row[1])
        elif tag == "string" and len(row) == 2:
            _string(row[1])
        elif tag == "mdata" and len(row) == 3:
            _metadata(row[1])
            children = [_nat(row[2], i)]
        elif tag == "proj" and len(row) == 4:
            _name(row[1])
            _nat(row[2])
            children = [_nat(row[3], i)]
        else:
            raise ValueError("invalid expression constructor")
        if children:
            need = (max(*(needs[j] for j in children[:-1]), max(0, needs[children[-1]] - 1))
                    if tag in {"lam", "forall", "let"} else max(needs[j] for j in children))
        for j in children:
            f.update(fs[j]); m.update(ms[j]); u.update(us[j])
        for j in universes:
            u.update(ldeps[j])
        height = 1 + max((heights[j] for j in children), default=0)
        key = _bytes(row)
        if height > 128 or key in seen or len(f) > 256:
            raise ValueError("expression depth, free-variable budget or duplicate node")
        seen.add(key)
        fs.append(f); ms.append(m); us.append(u); needs.append(need); heights.append(height)
        children_table.append(children); level_table.append(universes)

    eroots, lroots, medges, uedges, assignments = [], [], {}, {}, {}
    direct = {}
    for key, row in mvars.items():
        _fields(row, "id name type locals instances assignment kind depth index scope_args")
        _name(row["name"])
        if row["kind"] not in ("natural", "synthetic", "syntheticOpaque"):
            raise ValueError("invalid metavariable kind")
        for field in ("depth", "index", "scope_args"):
            _nat(row[field])
        allowed, roots, previous_index = set(), [], -1

        def root(ref):
            i = _nat(ref, len(exprs))
            if needs[i] or not fs[i] <= allowed:
                raise ValueError("unbound variable in local context")
            roots.append(i)
            return i

        for d in _array(row["locals"], 256):
            _fields(d, "id name index type value nondep binder kind")
            local_id = _id(d["id"])
            index = _nat(d["index"])
            if local_id in allowed or index <= previous_index:
                raise ValueError("duplicate or unordered local declaration")
            previous_index = index
            _name(d["name"])
            invalid_value = (d["nondep"] and (d["value"] is not None if state["schema"] == STATE_SCHEMA
                                               else d["value"] is None))
            if (type(d["nondep"]) is not bool or invalid_value
                    or d["binder"] not in ("explicit", "implicit", "strictImplicit", "instance")
                    or d["kind"] not in ("default", "implDetail", "auxDecl")):
                raise ValueError("invalid local declaration")
            root(d["type"])
            if d["value"] is not None:
                root(d["value"])
            allowed.add(local_id)
        for inst in _array(row["instances"], 256):
            if not isinstance(inst, list) or len(inst) != 2:
                raise ValueError("invalid local instance")
            _name(inst[0]); root(inst[1])
        root(row["type"])
        if row["assignment"] is not None:
            i = root(row["assignment"])
            assignments[key] = ms[i]
        medges[key] = set().union(*(ms[i] for i in roots))
        direct[key] = {("u", u) for i in roots for u in us[i]}
        if row["assignment"] is None:
            direct[key].add(("m", key))
        eroots.extend(roots)
    _acyclic(assignments)
    for key, row in uvars.items():
        _fields(row, "id depth assignment")
        _nat(row["depth"])
        if row["assignment"] is None:
            uedges[key] = set()
        else:
            i = _nat(row["assignment"], len(levels))
            lroots.append(i)
            uedges[key] = ldeps[i]
    _acyclic(uedges)

    def closure(roots, edges):
        reached, stack = set(), list(roots)
        while stack:
            key = stack.pop()
            if key not in reached:
                reached.add(key)
                stack.extend(edges[key])
        return reached

    if closure(goals, medges) != set(mvars):
        raise ValueError("unreachable metavariable declaration")
    reachable_exprs = closure(eroots, children_table)
    reachable_levels = closure(lroots + [u for i in reachable_exprs for u in level_table[i]], lchildren)
    if len(reachable_exprs) != len(exprs) or len(reachable_levels) != len(levels):
        raise ValueError("unreachable graph node")
    used_u = set().union(*(ldeps[i] for i in reachable_levels))
    if used_u != set(uvars):
        raise ValueError("unreachable universe declaration")

    # Context graphs may be cyclic even when assignments are acyclic. Compute
    # reachability instead of recursively expanding terms or assuming a DAG.
    deps = {}
    for goal in goals:
        tokens = set().union(*(direct[m] for m in closure([goal], medges)))
        unresolved = {t for t in tokens if t[0] == "m"}
        for _, u in (t for t in tokens if t[0] == "u"):
            unresolved.update(("u", v) for v in closure([u], uedges) if uvars[v]["assignment"] is None)
        deps[goal] = unresolved
    active = [g for g in goals if mvars[g]["assignment"] is None]
    components, owners = [], {}
    parents = list(range(len(active)))

    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for i, g in enumerate(active):
        for dep in deps[g]:
            if dep in owners:
                parents[find(i)] = find(owners[dep])
            else:
                owners[dep] = i
    groups = {}
    for i, g in enumerate(active):
        groups.setdefault(find(i), []).append(mvars[g]["id"])
    components.extend(groups.values())
    return {"components": components, "active_goals": len(active),
            "assigned_goals": len(goals) - len(active),
            "dependencies": [{"goal": mvars[g]["id"],
                              "unresolved": [[kind, json.loads(key)] for kind, key in sorted(deps[g])]}
                             for g in active],
            "expression_nodes": len(exprs), "level_nodes": len(levels),
            "state_sha256": hashlib.sha256(_bytes(state)).hexdigest(),
            "conservative": True, "kernel_typechecked": False, "proof_admitted": False,
            "replayable": False}


def _run_bounded(cmd, *, source: bytes, cwd: Path, timeout: float) -> bytes:
    """Bound wall time and combined pipe output, killing our process group on failure."""
    # A temporary input file avoids a blocked stdin write while the child fills
    # stdout. Only this private temporary file is removed on exit.
    with tempfile.TemporaryFile() as stdin:
        stdin.write(source); stdin.seek(0)
        with subprocess.Popen(cmd, cwd=cwd, stdin=stdin, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, start_new_session=True) as process:
            output, total = bytearray(), 0
            deadline = time.monotonic() + timeout
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    selector.register(process.stderr, selectors.EVENT_READ)
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("proof-state capture timeout")
                        for key, _ in selector.select(min(remaining, 0.1)):
                            chunk = os.read(key.fileobj.fileno(), 65536)
                            if not chunk:
                                selector.unregister(key.fileobj)
                            else:
                                total += len(chunk)
                                if total > MAX_BYTES:
                                    raise ValueError("capture output byte budget")
                                if key.fileobj is process.stdout:
                                    output.extend(chunk)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("proof-state capture timeout")
                if process.wait(timeout=remaining):
                    raise ValueError("native proof-state capture failed")
                return bytes(output)
            finally:
                # Also reap descendants holding pipes open or spawned by macros.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()


def validate_trace(trace, *, source: str, environment: str, node_budget: int = 4096,
                   event_budget: int = 64) -> list[dict[str, Any]]:
    if (not isinstance(source, str) or not isinstance(environment, str)
            or type(node_budget) is not int or not 1 <= node_budget <= MAX_NODES):
        raise ValueError("invalid trace validation request")
    _fields(trace, "schema environment lean_version lean_githash elaboration_errors events proof_admitted replayable")
    if (trace["schema"] != TRACE_SCHEMA or trace["environment"] != environment
            or not re.fullmatch(r"[0-9a-f]{64}", environment)
            or trace["proof_admitted"] is not False or trace["replayable"] is not False
            or type(trace["elaboration_errors"]) is not bool
            or not _string(trace["lean_version"]) or not _string(trace["lean_githash"])):
        raise ValueError("trace identity or trust flags")
    if type(event_budget) is not int or not 1 <= event_budget <= MAX_EVENTS:
        raise ValueError("invalid event budget")
    raw = source.encode()
    if len(raw) > MAX_SOURCE_BYTES or len(_bytes(trace)) > MAX_BYTES:
        raise ValueError("trace or source byte budget")
    analyses = []
    for i, event in enumerate(_array(trace["events"], event_budget)):
        if not isinstance(event, dict):
            raise ValueError("invalid event")
        captured = event.get("status") == "captured"
        _fields(event, "id parent declaration namespace syntax_kind start end status " +
                ("before after" if captured else "reason"))
        if _nat(event["id"]) != i or event["status"] not in ("captured", "unsupported"):
            raise ValueError("event order or status")
        if event["parent"] is not None:
            _nat(event["parent"], i)
        for field in ("declaration", "namespace", "syntax_kind"):
            _name(event[field])
        if (event["start"] is None) != (event["end"] is None):
            raise ValueError("incomplete source span")
        if event["start"] is not None:
            start, end = _nat(event["start"], len(raw) + 1), _nat(event["end"], len(raw) + 1)
            if start > end:
                raise ValueError("reversed source span")
            raw[:start].decode(); raw[start:end].decode()
        if captured:
            analyses.append({"id": event["id"], "status": "captured",
                             "before": analyze_state(event["before"], node_budget=node_budget),
                             "after": analyze_state(event["after"], node_budget=node_budget)})
        else:
            if not _string(event["reason"]):
                raise ValueError("missing unsupported reason")
            analyses.append({"id": event["id"], "status": "unsupported", "reason": event["reason"]})
    return analyses


def capture_source(source: str, *, project_root: Path, environment_sha256: str,
                   use_lake: bool = False, node_budget: int = 4096,
                   event_budget: int = 64, timeout: float = 40) -> dict[str, Any]:
    """Elaborate trusted source and retain exact before/after snapshot provenance.

    Source may fail elaboration: captured states remain diagnostics, never
    successful teachers. All errors/unsupported events are explicit. The supplied
    dependency fingerprint is caller-owned, not an authenticated closure manifest.
    """
    if (not isinstance(source, str) or len(source.encode()) > MAX_SOURCE_BYTES
            or not isinstance(environment_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", environment_sha256)
            or type(node_budget) is not int or not 1 <= node_budget <= MAX_NODES
            or type(event_budget) is not int or not 1 <= event_budget <= MAX_EVENTS
            or isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or not 0 < timeout <= 300):
        raise ValueError("invalid proof-state capture request")
    binding = {"source_sha256": hashlib.sha256(source.encode()).hexdigest(),
               "dependency_environment_sha256": environment_sha256,
               "exporter_sha256": hashlib.sha256(EXPORTER.read_bytes()).hexdigest(),
               "node_budget": node_budget, "event_budget": event_budget}
    environment = hashlib.sha256(_bytes(binding)).hexdigest()
    base = {**binding, "environment": environment, "proof_admitted": False,
            "kernel_typechecked": False, "dependency_closure_verified": False, "replayable": False}
    cmd = (["lake", "env", "lean"] if use_lake else ["lean"]) + [
        "--run", str(EXPORTER), environment, str(node_budget), str(event_budget)]
    try:
        output = _run_bounded(cmd, source=source.encode(), cwd=Path(project_root), timeout=timeout)
        if hashlib.sha256(EXPORTER.read_bytes()).hexdigest() != binding["exporter_sha256"]:
            raise ValueError("exporter changed during capture")
        lines = [line[len(MARKER):] for line in output.splitlines() if line.startswith(MARKER)]
        if len(lines) != 1:
            raise ValueError("missing or ambiguous capture receipt")

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate JSON field")
                result[key] = value
            return result

        def invalid_number(_):
            raise ValueError("all protocol numbers must be decimal strings")

        trace = json.loads(lines[0], object_pairs_hook=pairs, parse_int=invalid_number,
                           parse_float=invalid_number, parse_constant=invalid_number)
        analyses = validate_trace(trace, source=source, environment=environment,
                                  node_budget=node_budget, event_budget=event_budget)
        return {**base, "ok": True, "trace": trace, "analyses": analyses,
                "trace_sha256": hashlib.sha256(_bytes(trace)).hexdigest(),
                "captured_events": sum(a["status"] == "captured" for a in analyses),
                "unsupported_events": sum(a["status"] == "unsupported" for a in analyses)}
    except (OSError, TimeoutError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError, RecursionError) as exc:
        return {**base, "ok": False, "reason": type(exc).__name__ + ": " + str(exc)[:200]}


def collect_training_observations(rows, *, capture_fn, max_train_rows: int = 16,
                                  max_bytes: int = 33_554_432) -> dict[str, Any]:
    """Collect diagnostics from training rows only, using a trusted capture callback.

    Nontraining sources/targets are never read. Membership is caller-owned; this
    does not establish family decontamination. Nested InfoTree events are not
    flattened into purportedly independent executable transitions or CE labels.
    """
    if (type(max_train_rows) is not int or not 1 <= max_train_rows <= 64
            or type(max_bytes) is not int or not 1 <= max_bytes <= 67_108_864):
        raise ValueError("invalid observation collection budget")
    rows = _array(rows, 256)
    ids, training = set(), 0
    for row in rows:
        identity = row["id"]
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("invalid or duplicate row identity")
        ids.add(identity)
        if row["split"] not in ("train", "validation", "canary", "holdout"):
            raise ValueError("unknown split")
        training += row["split"] == "train"
    if training > max_train_rows:
        raise ValueError("training row budget")
    decisions, observations, total = [], [], 0
    for row in rows:
        if row["split"] != "train":
            decisions.append({"id": row["id"], "status": "excluded_split"})
            continue
        source = row["source"]
        if not isinstance(source, str) or len(source.encode()) > MAX_SOURCE_BYTES:
            raise ValueError("invalid training source")
        report = capture_fn(source)
        if not isinstance(report, dict) or report.get("ok") is not True:
            decisions.append({"id": row["id"], "status": "capture_failed"})
            continue
        if (report.get("source_sha256") != hashlib.sha256(source.encode()).hexdigest()
                or any(report.get(k) is not False for k in ("proof_admitted", "kernel_typechecked", "replayable"))):
            raise ValueError("foreign source or invalid capture trust flags")
        binding = {k: report[k] for k in ("source_sha256", "dependency_environment_sha256",
                                         "exporter_sha256", "node_budget", "event_budget")}
        if (report["environment"] != hashlib.sha256(_bytes(binding)).hexdigest()
                or report["trace_sha256"] != hashlib.sha256(_bytes(report["trace"])).hexdigest()):
            raise ValueError("capture binding mismatch")
        analyses = validate_trace(report["trace"], source=source, environment=report["environment"],
                                  node_budget=report["node_budget"], event_budget=report["event_budget"])
        # Recompute dependency diagnostics; saved analysis/count claims are not authority.
        report = {**report, "analyses": analyses,
                  "captured_events": sum(a["status"] == "captured" for a in analyses),
                  "unsupported_events": sum(a["status"] == "unsupported" for a in analyses)}
        observation = {"id": row["id"], "split": "train", "source": source, "capture": report,
                       "teacher_admitted": False}
        total += len(_bytes(observation))
        if total > max_bytes:
            raise ValueError("retained observation byte budget")
        observations.append(observation)
        decisions.append({"id": row["id"], "status": "observed",
                          "elaboration_errors": report["trace"]["elaboration_errors"],
                          "unsupported_events": report["unsupported_events"]})
    return {"schema": "jevops-proof-state-observations/v1", "observations": observations,
            "decisions": decisions, "capture_calls": training, "retained_bytes": total,
            "observation_only": True, "model_trained": False, "proof_admitted": False,
            "family_decontamination_verified": False}


def write_capture_report(report: dict[str, Any], output_dir: Path) -> None:
    """Code-generated small summary plus bounded raw JSON; never overwrite a run."""
    if (type(report.get("ok")) is not bool or any(report.get(k) is not False
            for k in ("proof_admitted", "kernel_typechecked", "replayable"))):
        raise ValueError("invalid observation report trust flags")
    raw = _bytes(report)
    if len(raw) > 2 * MAX_BYTES:
        raise ValueError("report byte budget")
    lines = ["# Proof-state capture", "", f"Capture succeeded: {report.get('ok') is True}",
             f"Source SHA-256: {report.get('source_sha256', 'unavailable')}"]
    if report.get("ok"):
        lines += [f"Elaboration errors: {report['trace']['elaboration_errors']}",
                  f"Captured events: {report['captured_events']}",
                  f"Unsupported events: {report['unsupported_events']}",
                  "", "| Event | Before goals / groups | After goals / groups |", "| --- | --- | --- |"]
        for a in report["analyses"]:
            if a["status"] == "captured":
                b, c = a["before"], a["after"]
                # Only show branch points; the raw file contains all observations.
                if max(b["active_goals"], c["active_goals"]) > 1:
                    lines.append(f"| {a['id']} | {b['active_goals']} / {len(b['components'])} | "
                                 f"{c['active_goals']} / {len(c['components'])} |")
    else:
        lines.append("Capture failed; inspect the bounded reason in capture.json.")
    lines += ["", "Observation only. No proof admission, replay guarantee, model training, or arena score."]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "capture.json").write_bytes(raw + b"\n")
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--environment-sha256", required=True)
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--node-budget", type=int, default=4096)
    parser.add_argument("--event-budget", type=int, default=64)
    parser.add_argument("--timeout", type=float, default=40)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("output directory already exists")
    with args.source.open("rb") as stream:
        raw = stream.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        parser.error("source byte budget")
    report = capture_source(raw.decode("utf-8"), project_root=args.project_root,
                            environment_sha256=args.environment_sha256, use_lake=args.lake,
                            node_budget=args.node_budget, event_budget=args.event_budget, timeout=args.timeout)
    write_capture_report(report, args.output_dir)
    print(args.output_dir / "summary.md")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
