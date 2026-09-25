"""Portable, bounded storage for Lean's structural expression DAG codec.

Validation here checks the wire format and binding structure, not theorem truth.
Only the Lean companion constructs native Expr values and performs kernel checks.
No source shortening, automatic training, or proof admission is performed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping
import zlib

SCHEMA = "jevops-lean-expr-dag/v1"
METADATA_POLICY = "ordered-scalars-v1-reject-syntax"
CODEC = Path(__file__).with_name("lean") / "ExprDAG.lean"
MARKER = "JEVOPS_EXPR_DAG:"
MAX_BYTES, MAX_NODES, MAX_DEPTH = 16_777_216, 100_000, 256
FIELDS = {"schema", "environment", "lean_version", "lean_githash", "metadata_policy",
          "levels", "expressions", "roots"}


def _bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("invalid JSON payload") from exc


def _string(value: Any) -> str:
    if not isinstance(value, str) or len(value.encode()) > 1_048_576:
        raise ValueError("invalid or oversized string")
    return value


def _nat(value: Any, bound: int | None = None) -> int:
    if not isinstance(value, str) or len(value) > 4096 or not re.fullmatch(r"0|[1-9][0-9]*", value):
        raise ValueError("canonical decimal natural string expected")
    n = int(value)
    if bound is not None and n >= bound:
        raise ValueError("forward or out-of-range reference/index")
    return n


def _name(value: Any) -> None:
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError("invalid name/depth")
    for part in value:
        if not isinstance(part, list) or len(part) != 2:
            raise ValueError("invalid name component")
        if part[0] == "s":
            _string(part[1])
        elif part[0] == "n":
            _nat(part[1])
        else:
            raise ValueError("invalid name tag")


def _metadata(entries: Any) -> None:
    if not isinstance(entries, list) or len(entries) > 256:
        raise ValueError("metadata entry budget")
    for entry in entries:
        if not isinstance(entry, list) or len(entry) != 2:
            raise ValueError("invalid metadata entry")
        _name(entry[0])
        data = entry[1]
        if not isinstance(data, list) or len(data) != 2:
            raise ValueError("invalid metadata value")
        tag, value = data
        if tag == "string":
            _string(value)
        elif tag == "name":
            _name(value)
        elif tag == "nat":
            _nat(value)
        elif tag == "int":
            if (not isinstance(value, str) or len(value) > 4096
                    or not re.fullmatch(r"0|-?[1-9][0-9]*", value)):
                raise ValueError("invalid metadata integer")
        elif tag == "bool" and type(value) is bool:
            pass
        else:
            raise ValueError("unsupported metadata; syntax values are not discarded")


def validate_dag(wire: Mapping[str, Any], *, environment: str, node_budget: int = 50_000,
                 toolchain: tuple[str, str] | None = None) -> dict[str, Any]:
    """Check topological order, payloads, depth, scope and full node reachability.

    This does not typecheck applications/constants or authenticate the supplied
    environment identity. Decimal strings avoid cross-language numeric rounding.
    """
    if type(node_budget) is not int or not 1 <= node_budget <= MAX_NODES:
        raise ValueError("invalid node budget")
    if not isinstance(environment, str) or not re.fullmatch(r"[0-9a-f]{64}", environment):
        raise ValueError("environment must be a SHA-256 fingerprint")
    if not isinstance(wire, Mapping) or set(wire) != FIELDS:
        raise ValueError("invalid wire fields")
    if wire["schema"] != SCHEMA or wire["metadata_policy"] != METADATA_POLICY or wire["environment"] != environment:
        raise ValueError("schema, metadata policy or environment mismatch")
    if not _string(wire["lean_version"]) or not _string(wire["lean_githash"]):
        raise ValueError("missing toolchain identity")
    if toolchain is not None and (wire["lean_version"], wire["lean_githash"]) != toolchain:
        raise ValueError("toolchain mismatch")
    payload = _bytes(wire)
    if len(payload) > MAX_BYTES:
        raise ValueError("wire byte budget")
    levels, exprs, roots = wire["levels"], wire["expressions"], wire["roots"]
    if any(not isinstance(rows, list) for rows in (levels, exprs, roots)) or not 1 <= len(roots) <= 64:
        raise ValueError("invalid tables or root budget")
    if len(levels) + len(exprs) > node_budget:
        raise ValueError("node budget")
    level_refs, level_heights, seen = [], [], set()
    for i, row in enumerate(levels):
        if not isinstance(row, list) or not row or not isinstance(row[0], str):
            raise ValueError("invalid level row")
        tag, children = row[0], []
        if tag == "zero" and len(row) == 1:
            pass
        elif tag == "param" and len(row) == 2:
            _name(row[1])
        elif (tag == "succ" and len(row) == 2) or (tag in {"max", "imax"} and len(row) == 3):
            children = [_nat(ref, i) for ref in row[1:]]
        else:
            raise ValueError("invalid level constructor")
        key = _bytes(row)
        if key in seen:
            raise ValueError("duplicate level row")
        seen.add(key)
        height = 1 + max((level_heights[j] for j in children), default=0)
        if height > MAX_DEPTH:
            raise ValueError("level depth budget")
        level_refs.append(children)
        level_heights.append(height)

    expr_refs, expr_levels, heights, needs, sizes, seen = [], [], [], [], [], set()
    for i, row in enumerate(exprs):
        if not isinstance(row, list) or not row or not isinstance(row[0], str):
            raise ValueError("invalid expression row")
        tag, children, universes, need = row[0], [], [], 0
        if tag == "bvar" and len(row) == 2:
            need = _nat(row[1], 65536) + 1
        elif tag == "sort" and len(row) == 2:
            universes = [_nat(row[1], len(levels))]
        elif tag == "const" and len(row) == 3 and isinstance(row[2], list):
            _name(row[1])
            if len(row[2]) > 256:
                raise ValueError("constant universe arity budget")
            universes = [_nat(ref, len(levels)) for ref in row[2]]
        elif tag == "app" and len(row) == 3:
            children = [_nat(ref, i) for ref in row[1:]]
        elif tag in {"lam", "forall"} and len(row) == 5:
            _name(row[1])
            if row[2] not in ("explicit", "implicit", "strictImplicit", "instance"):
                raise ValueError("invalid binder annotation")
            children = [_nat(ref, i) for ref in row[3:]]
        elif tag == "let" and len(row) == 6 and type(row[2]) is bool:
            _name(row[1])
            children = [_nat(ref, i) for ref in row[3:]]
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
            if tag in {"lam", "forall", "let"}:
                need = max(*(needs[j] for j in children[:-1]), max(0, needs[children[-1]] - 1))
            else:
                need = max(needs[j] for j in children)
        key = _bytes(row)
        if key in seen:
            raise ValueError("duplicate expression row")
        seen.add(key)
        height = 1 + max((heights[j] for j in children), default=0)
        if height > MAX_DEPTH:
            raise ValueError("expression depth budget")
        needs.append(need)
        sizes.append(1 + sum(sizes[j] for j in children))
        heights.append(height)
        expr_refs.append(children)
        expr_levels.append(universes)

    root_ids = [_nat(ref, len(exprs)) for ref in roots]
    if any(needs[i] for i in root_ids):
        raise ValueError("loose bound variable at root")
    reachable, pending, used_levels = set(), list(root_ids), set()
    while pending:
        i = pending.pop()
        if i not in reachable:
            reachable.add(i)
            pending.extend(expr_refs[i])
            used_levels.update(expr_levels[i])
    pending = list(used_levels)
    while pending:
        for j in level_refs[pending.pop()]:
            if j not in used_levels:
                used_levels.add(j)
                pending.append(j)
    if len(reachable) != len(exprs) or len(used_levels) != len(levels):
        raise ValueError("unreachable DAG nodes")

    def postorder(initial, edges):
        visited, order = set(), []
        stack = [(i, False) for i in reversed(initial)]
        while stack:
            i, done = stack.pop()
            if i in visited:
                continue
            if done:
                visited.add(i)
                order.append(i)
            else:
                stack.append((i, True))
                stack.extend((j, False) for j in reversed(edges[i]))
        return order

    # Match the native encoder's root-ordered, first-use postorder. Reject
    # alternative numbering rather than promising byte-identical re-encoding.
    order = postorder(root_ids, expr_refs)
    if order != list(range(len(exprs))):
        raise ValueError("noncanonical expression numbering")
    universe_order = postorder([j for i in order for j in expr_levels[i]], level_refs)
    if universe_order != list(range(len(levels))):
        raise ValueError("noncanonical level numbering")
    return {"expression_nodes": len(exprs), "level_nodes": len(levels),
            "root_expanded_expression_nodes": [sizes[i] for i in root_ids],
            "root_expression_depth": [heights[i] for i in root_ids],
            "json_bytes": len(payload), "zlib_bytes": len(zlib.compress(payload)),
            "closed": True, "kernel_typechecked": False, "proof_admitted": False}


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def root_summaries(wire: Mapping[str, Any], *, environment: str,
                   node_budget: int = 50_000) -> list[dict[str, Any]]:
    """Per-root costs and numbering-independent structural fingerprints.

    Fingerprints include names/annotations/metadata, but not the environment.
    They are not semantic equivalence checks: compare environment/toolchain
    separately. Constant bodies are not unfolded and graph sharing is not
    cross-scope variable identity.
    """
    stats = validate_dag(wire, environment=environment, node_budget=node_budget)
    levels, expressions, edges = [], [], []
    for row in wire["levels"]:
        normalized = list(row)
        if row[0] in {"succ", "max", "imax"}:
            normalized[1:] = [levels[int(j)] for j in row[1:]]
        levels.append(hashlib.sha256(_bytes([SCHEMA, "level", normalized])).hexdigest())
    for row in wire["expressions"]:
        normalized = list(row)
        positions = {"app": (1, 2), "lam": (3, 4), "forall": (3, 4),
                     "let": (3, 4, 5), "mdata": (2,), "proj": (3,)}.get(row[0], ())
        children = [int(row[p]) for p in positions]
        for p, child in zip(positions, children):
            normalized[p] = expressions[child]
        if row[0] == "sort":
            normalized[1] = levels[int(row[1])]
        elif row[0] == "const":
            normalized[2] = [levels[int(j)] for j in row[2]]
        expressions.append(hashlib.sha256(_bytes([SCHEMA, "expression", normalized])).hexdigest())
        edges.append(children)
    summaries = []
    for ordinal, root in enumerate(wire["roots"]):
        seen, pending = set(), [int(root)]
        while pending:
            i = pending.pop()
            if i not in seen:
                seen.add(i)
                pending.extend(edges[i])
        summaries.append({"structure_sha256": expressions[int(root)],
                          "unique_expression_nodes": len(seen),
                          "expanded_expression_nodes": stats["root_expanded_expression_nodes"][ordinal],
                          "expression_depth": stats["root_expression_depth"][ordinal]})
    return summaries


def _no_numbers(_):
    raise ValueError("DAG integers must be canonical decimal strings")


def loads_dag(payload: bytes, *, environment: str, node_budget: int = 50_000,
              toolchain: tuple[str, str] | None = None) -> dict[str, Any]:
    if not isinstance(payload, bytes) or len(payload) > MAX_BYTES:
        raise ValueError("wire byte budget")
    try:
        wire = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_pairs,
                          parse_int=_no_numbers, parse_float=_no_numbers, parse_constant=_no_numbers)
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid DAG JSON") from exc
    validate_dag(wire, environment=environment, node_budget=node_budget, toolchain=toolchain)
    return wire


def pack_dag(wire: Mapping[str, Any], *, environment: str, node_budget: int = 50_000) -> bytes:
    validate_dag(wire, environment=environment, node_budget=node_budget)
    return zlib.compress(_bytes(wire))


def unpack_dag(payload: bytes, *, environment: str, node_budget: int = 50_000) -> dict[str, Any]:
    if not isinstance(payload, bytes) or len(payload) > MAX_BYTES:
        raise ValueError("compressed byte budget")
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(payload, MAX_BYTES + 1)
    except zlib.error as exc:
        raise ValueError("invalid compressed DAG") from exc
    if len(raw) > MAX_BYTES or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("truncated, trailing or oversized compressed DAG")
    return loads_dag(raw, environment=environment, node_budget=node_budget)


def export_olean(*, directory: Path, declaration: str, environment_sha256: str, project_root: Path,
                 use_lake: bool = False, node_budget: int = 50_000, timeout: float = 30) -> dict[str, Any]:
    """Export Main's theorem; bind actual artifacts plus a caller-owned context.

    The caller fingerprints the dependency environment. This function hashes the
    target artifacts and codec, but does not independently hash dependency closure.
    It neither compiles input source nor promotes a theorem/checkpoint.
    """
    from .proof_trust import _NAME
    if (type(node_budget) is not int or not 1 <= node_budget <= MAX_NODES
            or not _NAME.fullmatch(declaration) or not re.fullmatch(r"[0-9a-f]{64}", environment_sha256)):
        raise ValueError("invalid DAG export request")
    binding: dict[str, Any] = {"dependency_environment_sha256": environment_sha256,
                               "dependency_closure_verified": False, "proof_admitted": False}
    try:
        files = [directory / ("Main.olean" + suffix) for suffix in ("", ".private", ".server")]
        def snapshot():
            return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
        artifacts = snapshot()
        if "Main.olean" not in artifacts:
            raise ValueError("missing compiled theorem artifact")
        codec_hash = hashlib.sha256(CODEC.read_bytes()).hexdigest()
        binding.update(artifact_files_sha256=artifacts, codec_sha256=codec_hash)
        environment = hashlib.sha256(_bytes(binding)).hexdigest()
        cmd = (["lake", "env", "lean"] if use_lake else ["lean"]) + ["--run", str(CODEC), "export",
               str(directory.resolve()), "Main", declaration, environment, str(node_budget)]
        run = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, timeout=timeout, check=False)
        lines = [s[len(MARKER):] for s in run.stdout.splitlines() if s.startswith(MARKER)]
        if run.returncode or len(lines) != 1 or len(run.stdout.encode()) > MAX_BYTES + 65536:
            return {"ok": False, "reason": "codec_failed", "stderr_tail": run.stderr[-500:],
                    "stdout_tail": run.stdout[-500:], **binding}
        report = json.loads(lines[0])
        if artifacts != snapshot() or hashlib.sha256(CODEC.read_bytes()).hexdigest() != codec_hash:
            raise ValueError("artifacts or codec changed during export")
        if (report.get("schema") != "jevops-lean-expr-export/v1" or report.get("declaration") != declaration
                or report.get("exact_roundtrip") is not True or report.get("kernel_typechecked") is not True
                or report.get("proof_admitted") is not False):
            raise ValueError("invalid export identity or round trip")
        stats = validate_dag(report["dag"], environment=environment, node_budget=node_budget)
        return {**report, **binding, "ok": True, "storage": stats,
                "dag_sha256": hashlib.sha256(_bytes(report["dag"])).hexdigest()}
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "reason": type(exc).__name__, **binding}
