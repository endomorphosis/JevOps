#!/usr/bin/env python3
"""TypeSafe-gated closed repairs for malformed NCA program state.

Same pattern as Lean portable folds: diagnose residuals, apply closed
kernels, accept only if diagnostics drop. TypeSafe ranks which kernel;
the validator is the oracle (not Jev). Never docker0. Does not write Lean.


TypeSafe/JevOps kernel primitive. Implementations (Lean lake, LRA board, portable folds) live outside this package. Jev does not write Lean. Never docker0."""
from __future__ import annotations

import ast
import copy
import json
import math
import re
from typing import Any, Callable, Mapping, Optional, Sequence

from jevops.program import ALLOWED_OPS


def _blocked() -> frozenset[str]:
    from jevops import hooks

    ids = hooks.const("blocked_ids")
    if ids:
        return frozenset(str(x) for x in ids)
    bg = hooks.try_import("board_graph")
    return frozenset(getattr(bg, "BLOCKED", ()) or ())


def _root_goal() -> str:
    from jevops import hooks

    root = hooks.const("root_goal")
    if root:
        return str(root)
    bg = hooks.try_import("board_graph")
    return str(getattr(bg, "ROOT_GOAL", None) or "G000")

CELL_FIELDS = ("id", "kind", "energy", "wins", "losses", "help", "unsafe", "tokens", "tick")
CELL_KINDS = frozenset(
    {
        "skill",
        "residual",
        "family",
        "proof",
        "tool",
        "goal",
        "subgoal",
        "task",
        "codepath",
        "theorem",
        "cell",
    }
)
REPAIR_CRITERIA: dict[str, dict[str, str]] = {
    "clip_energy": {"what": "Clip cell energy into [0,1]; replace NaN/inf", "not_for": "A healthy grid"},
    "coerce_cells": {"what": "Drop non-dict cells; fill missing id/kind/wins", "not_for": "Already dict cells"},
    "fix_tape": {"what": "Coerce tape cells list and clamp head", "not_for": "A valid tape ring"},
    "fix_stack": {"what": "Drop frames without frame_id; clear dangling parent_id", "not_for": "A consistent forest"},
    "fix_program_ops": {"what": "Drop unknown work ops; strip docker0; require ptr on CALL", "not_for": "Closed ops already"},
    "reseed_board": {"what": "Restore goal/subgoal/task cells if the DAG is missing", "not_for": "Board already seeded"},
    "mark_blocked": {"what": "Force do_not_fork on Track-2 / submit cells", "not_for": "Already marked"},
    "alias_cells": {"what": "Merge port_foo with ptr://skill/port_foo", "not_for": "Already canonical ids"},
}
HEAL_FAMILIES: dict[str, tuple[str, ...]] = {
    "cells": ("coerce_cells", "clip_energy", "alias_cells", "mark_blocked"),
    "tape_stack": ("fix_tape", "fix_stack"),
    "program": ("fix_program_ops",),
    "board": ("reseed_board",),
}
FAMILY_CRITERIA: dict[str, dict[str, str]] = {
    "cells": {"what": "Grid shape, energy, aliases, blocked flags", "not_for": "Tape or program_state"},
    "tape_stack": {"what": "Neural tape ring or call-stack forest", "not_for": "Cell energy"},
    "program": {"what": "Closed work ops / docker0 in program_state", "not_for": "Board DAG"},
    "board": {"what": "Missing LRA goal/subgoal/task cells", "not_for": "A seeded board"},
}


def family_of(kernel: str) -> str:
    for fam, kids in HEAL_FAMILIES.items():
        if kernel in kids:
            return fam
    return "cells"


def _clip(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(number):
        return 0.5
    return max(0.0, min(1.0, number))


def diagnose(memory: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Residuals of corrupted NCA / tape / stack / program_state."""

    issues: list[dict[str, Any]] = []
    nca = memory.get("nca")
    if not isinstance(nca, dict):
        issues.append({"code": "nca_not_dict", "repair": "coerce_cells"})
        nca = {}
    grid = nca.get("grid")
    if grid is None:
        issues.append({"code": "missing_grid", "repair": "reseed_board"})
        grid = {}
    elif not isinstance(grid, dict):
        issues.append({"code": "grid_not_dict", "repair": "coerce_cells"})
        grid = {}
    for cid, cell in list(grid.items()):
        if not isinstance(cell, dict):
            issues.append({"code": "cell_not_dict", "id": str(cid), "repair": "coerce_cells"})
            continue
        energy = cell.get("energy")
        try:
            number = float(energy)
            if not math.isfinite(number) or number < 0 or number > 1:
                issues.append({"code": "energy_oob", "id": str(cid), "repair": "clip_energy"})
        except (TypeError, ValueError):
            issues.append({"code": "energy_oob", "id": str(cid), "repair": "clip_energy"})
        if not cell.get("kind"):
            issues.append({"code": "missing_kind", "id": str(cid), "repair": "coerce_cells"})
        ident = str(cid)
        if any(ident.endswith(b) or b in ident for b in _blocked()) and not cell.get("do_not_fork"):
            issues.append({"code": "blocked_unmarked", "id": ident, "repair": "mark_blocked"})
    try:
        from jevops.nca import canonical_cell_id

        canons = [canonical_cell_id(str(cid)) for cid in grid]
        if len(set(canons)) < len(canons):
            issues.append({"code": "alias_collision", "repair": "alias_cells"})
        elif any(not str(cid).startswith("ptr://") and str(cid).startswith("port_") for cid in grid):
            issues.append({"code": "alias_collision", "repair": "alias_cells"})
    except Exception:
        pass
    if not any(str(cid).startswith("ptr://goal/") for cid in grid):
        issues.append({"code": "missing_goal", "repair": "reseed_board"})
    tape = memory.get("tape") if isinstance(memory.get("tape"), dict) else {}
    cells = tape.get("cells")
    if cells is not None and not isinstance(cells, list):
        issues.append({"code": "tape_cells_not_list", "repair": "fix_tape"})
        cells = []
    if isinstance(cells, list):
        head = tape.get("head")
        if cells and (not isinstance(head, int) or head < 0 or head >= len(cells)):
            issues.append({"code": "tape_head_oob", "repair": "fix_tape"})
    stack = memory.get("_stack") if isinstance(memory.get("_stack"), dict) else {}
    forest = stack.get("forest") if isinstance(stack.get("forest"), dict) else {}
    for fid, frame in forest.items():
        if not isinstance(frame, dict) or not frame.get("frame_id"):
            issues.append({"code": "bad_frame", "id": str(fid), "repair": "fix_stack"})
            continue
        parent = str(frame.get("parent_id") or "")
        if parent and parent not in forest:
            issues.append({"code": "dangling_parent", "id": str(fid), "repair": "fix_stack"})
    program = (nca.get("program_state") if isinstance(nca, dict) else None) or {}
    for op in program.get("ops") or []:
        if not isinstance(op, dict) or str(op.get("op") or "") not in ALLOWED_OPS:
            issues.append({"code": "bad_work_op", "repair": "fix_program_ops"})
            break
        if str(op.get("op")) == "CALL" and not str(op.get("ptr") or "").startswith("ptr://"):
            issues.append({"code": "call_without_ptr", "repair": "fix_program_ops"})
            break
        if "172.17.0.1" in json_dumps_safe(op):
            issues.append({"code": "docker0_in_ops", "repair": "fix_program_ops"})
    return issues


def json_dumps_safe(value: Any) -> str:
    try:
        import json

        return json.dumps(value)
    except Exception:
        return str(value)


def repair_clip_energy(memory: dict[str, Any]) -> dict[str, Any]:
    grid = _ensure_grid(memory)
    for cell in grid.values():
        if isinstance(cell, dict):
            cell["energy"] = _clip(cell.get("energy"))
    return memory


def repair_coerce_cells(memory: dict[str, Any]) -> dict[str, Any]:
    nca = memory.get("nca")
    if not isinstance(nca, dict):
        memory["nca"] = {"grid": {}, "tick": 0}
        nca = memory["nca"]
    grid = nca.get("grid")
    if not isinstance(grid, dict):
        nca["grid"] = {}
        grid = nca["grid"]
    cleaned: dict[str, Any] = {}
    for cid, cell in list(grid.items()):
        if not isinstance(cell, dict):
            cell = {}
        ident = str(cid)
        kind = str(cell.get("kind") or ("goal" if "goal" in ident else "cell"))
        if kind not in CELL_KINDS:
            kind = "cell"
        row = {
            "id": str(cell.get("id") or ident),
            "kind": kind,
            "energy": _clip(cell.get("energy")),
            "wins": int(cell.get("wins") or 0),
            "losses": int(cell.get("losses") or 0),
            "help": float(cell.get("help") or 0.0) if _finite(cell.get("help")) else 0.0,
            "unsafe": float(cell.get("unsafe") or 0.0) if _finite(cell.get("unsafe")) else 0.0,
            "tokens": int(cell.get("tokens") or 0),
            "tick": int(cell.get("tick") or 0),
        }
        for key in ("do_not_fork", "blocked", "title", "status", "path", "visited"):
            if key in cell:
                row[key] = cell[key]
        cleaned[ident] = row
    nca["grid"] = cleaned
    return memory


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _ensure_grid(memory: dict[str, Any]) -> dict[str, Any]:
    nca = memory.setdefault("nca", {})
    if not isinstance(nca, dict):
        memory["nca"] = {"grid": {}}
        nca = memory["nca"]
    grid = nca.setdefault("grid", {})
    if not isinstance(grid, dict):
        nca["grid"] = {}
        grid = nca["grid"]
    return grid


def repair_fix_tape(memory: dict[str, Any]) -> dict[str, Any]:
    tape = memory.get("tape")
    if not isinstance(tape, dict):
        memory["tape"] = {"cells": [], "head": 0, "n": 0}
        return memory
    cells = tape.get("cells")
    if not isinstance(cells, list):
        cells = []
    cleaned = [cell for cell in cells if isinstance(cell, dict) and cell.get("kind")]
    tape["cells"] = cleaned[-64:]
    tape["n"] = len(tape["cells"])
    head = tape.get("head")
    if not isinstance(head, int) or head < 0 or (cleaned and head >= len(tape["cells"])):
        tape["head"] = max(0, len(tape["cells"]) - 1)
    memory["tape"] = tape
    return memory


def repair_fix_stack(memory: dict[str, Any]) -> dict[str, Any]:
    stack = memory.get("_stack")
    if not isinstance(stack, dict):
        memory["_stack"] = {"frames": [], "forest": {}, "depth": 0}
        return memory
    forest = stack.get("forest") if isinstance(stack.get("forest"), dict) else {}
    good = {
        str(fid): dict(frame)
        for fid, frame in forest.items()
        if isinstance(frame, dict) and frame.get("frame_id")
    }
    for frame in good.values():
        parent = str(frame.get("parent_id") or "")
        if parent and parent not in good:
            frame["parent_id"] = ""
        kids = [cid for cid in (frame.get("child_ids") or []) if cid in good]
        frame["child_ids"] = kids
    frames = [f for f in (stack.get("frames") or []) if isinstance(f, dict) and str(f.get("frame_id") or "") in good]
    stack["forest"] = good
    stack["frames"] = frames
    stack["depth"] = len(frames)
    memory["_stack"] = stack
    return memory


def repair_fix_program_ops(memory: dict[str, Any]) -> dict[str, Any]:
    nca = memory.setdefault("nca", {})
    if not isinstance(nca, dict):
        memory["nca"] = {"grid": {}, "program_state": {"ops": []}}
        return memory
    program = nca.get("program_state") if isinstance(nca.get("program_state"), dict) else {}
    ops: list[dict[str, Any]] = []
    for item in program.get("ops") or []:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op") or "").upper()
        if op not in ALLOWED_OPS:
            continue
        blob = json_dumps_safe(item)
        if "172.17.0.1" in blob:
            continue
        row = {"op": op}
        ptr = str(item.get("ptr") or "")
        if op == "CALL":
            if not ptr:
                continue
            if not ptr.startswith("ptr://"):
                from jevops.stack import coerce_ptr

                ptr = coerce_ptr(ptr)
            row["ptr"] = ptr
        if item.get("query"):
            from jevops.outer import head_chars

            row["query"] = head_chars(item.get("query"), 80)
        ops.append(row)
    program["ops"] = ops
    program["called_docker0"] = False
    nca["program_state"] = program
    return memory


def repair_reseed_board(memory: dict[str, Any]) -> dict[str, Any]:
    from jevops import hooks

    repair_coerce_cells(memory)
    seeder = hooks.resolve("seed_board", "board_graph", "seed_nca_from_board")
    if seeder:
        seeder(memory, force=True)
    return memory


def repair_alias_cells(memory: dict[str, Any]) -> dict[str, Any]:
    from jevops.nca import merge_alias_cells

    merge_alias_cells(memory)
    return memory


def repair_mark_blocked(memory: dict[str, Any]) -> dict[str, Any]:
    grid = _ensure_grid(memory)
    for cid, cell in grid.items():
        if not isinstance(cell, dict):
            continue
        ident = str(cid)
        if any(b in ident for b in _blocked()):
            cell["do_not_fork"] = True
            cell["blocked"] = True
            cell["energy"] = min(_clip(cell.get("energy")), 0.05)
    return memory


REPAIRS: tuple[tuple[str, Callable[[dict[str, Any]], dict[str, Any]]], ...] = (
    ("coerce_cells", repair_coerce_cells),
    ("clip_energy", repair_clip_energy),
    ("fix_tape", repair_fix_tape),
    ("fix_stack", repair_fix_stack),
    ("fix_program_ops", repair_fix_program_ops),
    ("reseed_board", repair_reseed_board),
    ("mark_blocked", repair_mark_blocked),
    ("alias_cells", repair_alias_cells),
)


def typesafe_pick_repair(issues: list[dict[str, Any]], *, ledger: Any = None) -> str:
    """TypeSafe Choice among residual kernels. Fail closed to first residual."""

    names: list[str] = []
    seen: set[str] = set()
    for issue in issues:
        name = str(issue.get("repair") or "")
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    banned = set()
    if isinstance(ledger, dict):
        banned = set(((ledger.get("nca") or {}).get("heal_blacklist")) or [])
    names = [name for name in names if name not in banned]
    if not names:
        return ""
    if len(names) == 1 or ledger is None:
        return names[0]
    try:
        from jevops.typesafe_inference import Choice, TypeSafeClient, typesafe_configured
        from jevops import hooks

        pin = hooks.resolve("pin_typesafe", "pca_mca_fanout", "pin_typesafe_path")
        load_key = hooks.resolve("load_keyfile", "pca_mca_fanout", "load_keyfile")
        if load_key:
            load_key()
        if pin:
            pin()
        if not typesafe_configured():
            return names[0]
        families = []
        for name in names:
            fam = family_of(name)
            if fam not in families:
                families.append(fam)
        from jevops.typesafe_inference import Noul
        from jevops import hooks as _hooks

        t1 = _hooks.try_import("track1_ledger")

        from jevops.outer import head_seq

        state = {"role": "nca_heal", "issues": [i.get("code") for i in head_seq(issues, 8)], "kernels": names, "families": families}
        questions = {
            "family": Choice(
                instructions={
                    "question": "Which family of NCA repairs should code apply first?",
                    "focus": "cells / tape_stack / program / board. Do not write Lean.",
                },
                criteria={fam: FAMILY_CRITERIA[fam] for fam in families if fam in FAMILY_CRITERIA},
            ),
            "repair": Choice(
                instructions={
                    "question": "Which closed NCA repair kernel in that family should code apply?",
                    "focus": "Pick one residual. Do not write Lean or Python.",
                },
                criteria={key: REPAIR_CRITERIA[key] for key in names if key in REPAIR_CRITERIA},
            ),
            "unsafe": Noul(
                instructions={
                    "question": "Is applying this kernel to this state wrong?",
                    "focus": "true = P(wrong). Abstain if the residual is already healthy.",
                },
                criteria={
                    "true": "The kernel would drop live program ops or unseed the board",
                    "false": "A closed structural repair that shrinks diagnose()",
                },
            ),
        }
        result = TypeSafeClient(timeout=45.0).system_one(state, questions)
        usage = dict(getattr(result, "usage", None) or {})
        if ledger is not None:
            inn = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 80)
            out = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
            ledger.record("jev", input_tokens=inn, output_tokens=out, model=getattr(t1, "JEV_MODEL_ID", "jev"))
        choices = getattr(result, "choices", None) or {}
        nouls = getattr(result, "nouls", None) or {}
        repair_ans = choices.get("repair")
        family_ans = choices.get("family")
        choice = str(getattr(repair_ans, "choice", None) or "")
        family = str(getattr(family_ans, "choice", None) or "")
        in_family = [name for name in names if family_of(name) == family] if family in HEAL_FAMILIES else names
        unsafe = float(getattr(nouls.get("unsafe"), "noul", 0.0) or 0.0)
        fire_t = hooks.const("fire_t")
        if fire_t is None:
            rc = hooks.try_import("random_canary")
            fire_t = float(getattr(rc, "FIRE_T", 0.7) if rc else 0.7)
        if unsafe > float(fire_t):
            return in_family[0] if in_family else names[0]
        if choice in in_family:
            return choice
        if choice in names:
            return choice
        return in_family[0] if in_family else names[0]
    except Exception:
        return names[0]


def apply_repair(memory: dict[str, Any], name: str) -> dict[str, Any]:
    for stem, fn in REPAIRS:
        if stem == name:
            return fn(memory)
    return memory


def heal(
    memory: dict[str, Any],
    *,
    pick: Optional[str] = None,
    pick_fn: Optional[Callable[[list[dict[str, Any]]], str]] = None,
    ledger: Any = None,
) -> dict[str, Any]:
    """Apply closed repairs until diagnostics are empty or a pass does not help.

    TypeSafe may pick one kernel via ``pick`` / ``pick_fn``; otherwise every
    residual's suggested repair runs (like a portable pipeline).
    """

    before = diagnose(memory)
    applied: list[str] = []
    if not before:
        return {"ok": True, "applied": [], "remaining": [], "called_docker0": False}
    names: list[str]
    if pick:
        names = [pick]
    elif pick_fn:
        chosen = pick_fn(before)
        names = [chosen] if chosen else []
    elif ledger is not None:
        chosen = typesafe_pick_repair(before, ledger=ledger)
        names = [chosen] if chosen else []
    else:
        names = []
        seen: set[str] = set()
        for issue in before:
            name = str(issue.get("repair") or "")
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    banned = set(((memory.get("nca") or {}).get("heal_blacklist")) or [])
    names = [name for name in names if name not in banned]
    snapshot = copy.deepcopy(memory)
    for name in names:
        apply_repair(memory, name)
        applied.append(name)
        if len(diagnose(memory)) <= len(diagnose(snapshot)):
            snapshot = copy.deepcopy(memory)
        else:
            memory.clear()
            memory.update(copy.deepcopy(snapshot))
            if applied and applied[-1] == name:
                applied[-1] = f"{name}#reverted"
                banned = list(((memory.get("nca") or {}).get("heal_blacklist")) or [])
                if name not in banned:
                    banned.append(name)
                memory.setdefault("nca", {})["heal_blacklist"] = banned[-16:]
    remaining = diagnose(memory)
    try:
        from jevops.nca import charge_budget

        charge_budget(memory, ledger=ledger, jev_calls=1 if ledger is not None else 0, event="heal")
    except Exception:
        pass
    return {
        "ok": not remaining,
        "applied": applied,
        "remaining": remaining,
        "before": len(before),
        "after": len(remaining),
        "called_docker0": False,
        "jev_writes_lean": False,
    }


def parse_jsonl_errors(
    stdout: str,
    *,
    severity: str = "error",
    cap: int = 6,
    data_cap: int = 400,
) -> list[dict[str, Any]]:
    """Parse compiler JSONL error objects. No Lean."""

    errors: list[dict[str, Any]] = []
    for line in str(stdout or "").splitlines():
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if payload.get("severity") != severity:
            continue
        errors.append({"pos": payload.get("pos"), "data": str(payload.get("data") or "")[: int(data_cap)]})
        if len(errors) >= int(cap):
            break
    return errors


def match_leading_indent(reference: str, tactics: str) -> str:
    """Prefix every non-blank tactic line with the reference's first indent."""

    ref_first = next((line for line in str(reference or "").splitlines() if line.strip()), "")
    indent = ref_first[: len(ref_first) - len(ref_first.lstrip())]
    body = str(tactics or "").lstrip("\n")
    if not indent or body.startswith(indent):
        return body
    return "\n".join((indent + line if line.strip() else line) for line in body.splitlines())


def align_generated(
    reference: str,
    text: str,
    *,
    extract_fn: Callable[[str], str],
    match_fn: Callable[[str, str], str],
    flatten_fn: Callable[[str, str], str],
) -> str:
    """Match hosted indent to the reference, then flatten extra case indent."""

    return flatten_fn(reference, match_fn(reference, extract_fn(text)))


def align_then_compile(
    text: str,
    reference: str,
    *,
    align_fn: Callable[[str, str], str],
    compile_fn: Callable[[str], Any],
) -> tuple[str, Any]:
    """Align generated tactics to the reference, then compile. Lake still admits."""

    repaired = align_fn(reference, text)
    return repaired, compile_fn(repaired)


def flatten_overindent(
    reference: str,
    tactics: str,
    *,
    header_fn: Any,
) -> str:
    """If header lines are deeper than the reference, strip the extra indent."""

    def indents(text: str) -> list[int]:
        found: list[int] = []
        for line in str(text or "").splitlines():
            stripped = line.lstrip()
            if header_fn(stripped):
                found.append(len(line) - len(stripped))
        return found

    ref_cases = indents(reference)
    tac_cases = indents(tactics)
    if not ref_cases or not tac_cases:
        return tactics
    extra = min(tac_cases) - min(ref_cases)
    if extra <= 0:
        return tactics
    floor = min(tac_cases)
    out: list[str] = []
    for line in str(tactics).splitlines():
        if not line.strip():
            out.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent >= floor:
            line = line[extra:]
        out.append(line)
    return "\n".join(out)


def forbidden_tokens(
    text: str,
    tokens: Sequence[str],
    *,
    boundary: str = r"(?<![A-Za-z0-9_']){token}(?![A-Za-z0-9_'])",
) -> tuple[str, ...]:
    """Which tokens appear as whole words. boundary.format(token=escaped)."""

    found: list[str] = []
    blob = str(text or "")
    for token in tokens:
        if re.search(boundary.format(token=re.escape(str(token))), blob, re.IGNORECASE):
            found.append(str(token))
    return tuple(found)


def ident_used(name: str, text: str, *, pattern: Optional[Any] = None) -> bool:
    """True if name appears as a whole ident in text."""

    if not name:
        return False
    if pattern is not None:
        return pattern.search(str(text or "")) is not None
    return re.search(r"(?<!\w)" + re.escape(str(name)) + r"(?!\w)", str(text or "")) is not None


def idents_in(text: str, *, pattern: Any, stopwords: Sequence[str] = ()) -> set[str]:
    banned = {str(item) for item in stopwords}
    return {tok for tok in pattern.findall(str(text or "")) if tok not in banned}


def class_ann_names(source: str, class_name: str) -> Optional[list[str]]:
    """AnnAssign field names on a top-level class, or None if the class is missing."""

    tree = ast.parse(str(source or ""))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == str(class_name):
            names: list[str] = []
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    names.append(item.target.id)
            return names
    return None


def names_used_later(
    text: str,
    end: int,
    names: Sequence[str],
    *,
    ident_fn: Any,
) -> list[str]:
    """Which binder names appear after end. ident_fn(text)->iterable."""

    if not names:
        return []
    later = set(ident_fn(str(text or "")[int(end) :]) or ())
    return [name for name in names if name in later]


def unique_findall(blob: str, pattern: Any) -> list[str]:
    return list(dict.fromkeys(pattern.findall(str(blob or ""))))


def join_errors(errors: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(str(item.get("data") or "") for item in errors)


def repair_on_needle(
    tactics: str,
    errors: Sequence[Mapping[str, Any]],
    needle: str,
    repair_fn: Any,
) -> Optional[str]:
    """If ``needle`` appears in joined error data, run repair_fn(tactics)."""

    if str(needle or "") not in join_errors(errors):
        return None
    return repair_fn(tactics)


def classify_text(
    blob: str,
    rules: Sequence[tuple[str, Sequence[str]]],
    *,
    default: str = "other",
    all_of: Sequence[tuple[str, Sequence[str]]] = (),
) -> str:
    """First matching needle wins. Optional all-of rules after. No Lean."""

    hay = str(blob or "")
    low = hay.lower()
    for label, needles in rules:
        for needle in needles:
            if needle.lower() in low:
                return str(label)
    for label, needles in all_of:
        if needles and all(str(needle).lower() in low for needle in needles):
            return str(label)
    return str(default)


def insert_missing_line(draft: str, reference: str, missing_line: str) -> str:
    """Put missing_line back next to a neighbor that still exists in draft."""

    if missing_line.strip() in {line.strip() for line in draft.splitlines()}:
        return draft
    ref_lines = reference.splitlines()
    try:
        index = next(i for i, line in enumerate(ref_lines) if line == missing_line)
    except StopIteration:
        try:
            index = next(i for i, line in enumerate(ref_lines) if missing_line.strip() in line)
            missing_line = ref_lines[index]
        except StopIteration:
            return missing_line + "\n" + draft
    draft_lines = draft.splitlines()
    for delta in range(1, 10):
        for neighbor_i in (index - delta, index + delta):
            if not 0 <= neighbor_i < len(ref_lines):
                continue
            neighbor = ref_lines[neighbor_i]
            if neighbor in draft_lines:
                pos = draft_lines.index(neighbor)
                insert_at = pos + 1 if neighbor_i < index else pos
                draft_lines.insert(insert_at, missing_line)
                return "\n".join(draft_lines)
    return missing_line + "\n" + draft


def restore_bound_lines(
    draft: str,
    reference: str,
    idents: Sequence[str],
    *,
    bound_fn: Any,
) -> str:
    """Restore reference lines that bound missing identifiers. bound_fn is injected."""

    out = draft
    for ident in idents:
        bound = bound_fn(reference, ident) if bound_fn is not None else None
        if bound:
            out = insert_missing_line(out, reference, bound)
    return str(out).strip("\n")


def attr_names(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.attr, str)
    }


def score_assignments(
    source: str,
    keys: Sequence[str],
    *,
    allow_none: bool = True,
) -> list[str]:
    """Flag invented numeric scores. None is allowed when allow_none."""

    tree = ast.parse(source)
    banned = set(keys)
    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in banned:
            value = node.value
            if allow_none and isinstance(value, ast.Constant) and value.value is None:
                continue
            issues.append(f"keyword {node.arg}={ast.dump(value)} at line {getattr(node, 'lineno', 0)}")
        if isinstance(node, ast.Assign):
            targets: list[str] = []
            for target in node.targets:
                if isinstance(target, ast.Name):
                    targets.append(target.id)
                elif isinstance(target, ast.Attribute):
                    targets.append(target.attr)
            if any(name in banned for name in targets):
                value = node.value
                if allow_none and isinstance(value, ast.Constant) and value.value is None:
                    continue
                issues.append(
                    f"assign {targets}={ast.dump(value)} at line {getattr(node, 'lineno', 0)}"
                )
    return issues


def uses_attr(source: str, attr: str) -> bool:
    tree = ast.parse(source)
    return any(isinstance(node, ast.Attribute) and node.attr == attr for node in ast.walk(tree))


def scan_constant_uses(
    source: str,
    needle: Any,
    *,
    methods: Sequence[str] = (),
    bare_fmt: str = "bare constant at line {line}",
    call_fmt: str = "{attr}(constant) scan at line {line}",
) -> list[str]:
    """AST walk: Constant==needle, and Call.attr in methods with that constant arg."""

    tree = ast.parse(source)
    issues: list[str] = []
    method_set = set(methods)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == needle:
            issues.append(bare_fmt.format(line=getattr(node, "lineno", 0)))
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in method_set:
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if isinstance(arg, ast.Constant) and arg.value == needle:
                issues.append(
                    call_fmt.format(attr=node.func.attr, line=getattr(node, "lineno", 0))
                )
    return issues


def imported_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".", 1)[0])
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".", 1)[0])
                names.add(node.module)
            for alias in node.names:
                names.add(alias.name)
    return names


def call_func_name(func: ast.AST) -> str:
    """Dotted name of a Call.func node (Name or Attribute chain)."""

    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = []
        cur: ast.AST = func
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def call_func_names(source: str) -> set[str]:
    names: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def attr_hits(source: str, names: Sequence[str]) -> list[str]:
    """Each Attribute.attr that is in names, in walk order."""

    want = {str(item) for item in names}
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in want:
            found.append(str(node.attr))
    return found


def subprocess_invokes(
    source: str,
    binaries: Sequence[str],
    *,
    spawn: Sequence[str] = ("Popen", "run", "call", "check_call", "check_output"),
) -> bool:
    """True if a subprocess-like Call passes a forbidden binary string."""

    tree = ast.parse(source)
    spawn_set = {str(item) for item in spawn}
    needles = tuple(str(item) for item in binaries)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        short = call_func_name(node.func).rsplit(".", 1)[-1]
        if short not in spawn_set:
            continue
        blobs: list[str] = []
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for child in ast.walk(arg):
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    blobs.append(child.value)
        joined = " ".join(blobs)
        if any(binary in joined for binary in needles):
            return True
    return False


def keyword_names(source: str) -> set[str]:
    return {
        node.arg
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.keyword) and isinstance(node.arg, str)
    }


def string_constants(source: str) -> list[str]:
    return [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def function_names(source: str) -> set[str]:
    return {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def call_short_name(func: ast.AST) -> str:
    dotted = call_func_name(func)
    return dotted.rsplit(".", 1)[-1] if dotted else ""


def call_short_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            name = call_short_name(node.func)
            if name:
                names.add(name)
    return names


def score_keys(source: str, forbidden: Sequence[str] = ()) -> list[str]:
    """keyword.arg / AnnAssign target.id in forbidden. None constants are skipped."""

    banned = set(forbidden)
    keys: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.keyword) and node.arg in banned:
            if isinstance(node.value, ast.Constant) and node.value.value is None:
                continue
            keys.append(str(node.arg))
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in banned:
                if isinstance(node.value, ast.Constant) and node.value.value is None:
                    continue
                keys.append(node.target.id)
    return keys


def has_constant(source: str, value: Any) -> bool:
    return any(
        isinstance(node, ast.Constant) and node.value == value
        for node in ast.walk(ast.parse(source))
    )


def assigned_constants(source: str, names: Sequence[str]) -> dict[str, Any]:
    tree = ast.parse(source)
    return {str(name): assigned_constant(tree, str(name)) for name in names}


def matching_constants(source: str, pred: Any) -> list[str]:
    return [value for value in string_constants(source) if pred(value)]


def ast_name_hits(tree: ast.AST, names: Sequence[str]) -> set[str]:
    want = {str(item) for item in names}
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in want:
            used.add(node.id)
        if isinstance(node, ast.Attribute) and node.attr in want:
            used.add(node.attr)
    return used


def call_kwarg_numbers(tree: ast.AST, keys: Sequence[str]) -> list[float]:
    want = {str(item) for item in keys}
    values: list[float] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg not in want:
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)):
                values.append(float(value.value))
    return values


def assigned_literal(
    source: str,
    name: str,
    *,
    error_cls: Any = ValueError,
    miss: str = "assignment not found",
    not_dict: str = "assignment must be a dict",
) -> Any:
    """ast.literal_eval of a Name assignment that must be a dict."""

    tree = ast.parse(source)
    want = str(name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == want:
                if not isinstance(value, ast.Dict):
                    raise error_cls(not_dict)
                return ast.literal_eval(value)
    raise error_cls(miss)


def assigned_constant(tree: ast.AST, name: str) -> Any:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = node.value
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            value = node.value
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                if isinstance(value, ast.Constant):
                    return value.value
    return None


def numeric_score_assignments(source: str, forbidden: Sequence[str] = ()) -> list[str]:
    tree = ast.parse(source)
    banned = set(forbidden)
    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in banned:
            value = node.value
            if isinstance(value, ast.Constant) and value.value is None:
                continue
            issues.append(f"keyword {node.arg} at line {getattr(node, 'lineno', 0)}")
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in banned:
                value = node.value
                if isinstance(value, ast.Constant) and value.value is None:
                    continue
                issues.append(f"ann {node.target.id} at line {getattr(node, 'lineno', 0)}")
    return issues


def membership(bag: Sequence[Any], mapping: Mapping[str, Sequence[str]]) -> dict[str, bool]:
    """Flag map: any listed name is in bag."""

    items = {str(x) for x in bag}
    return {key: any(str(name) in items for name in names) for key, names in dict(mapping).items()}


def audit_source(
    source: str,
    *,
    forbidden_imports: Sequence[str] = (),
    forbidden_calls: Sequence[str] = (),
    forbidden_scores: Sequence[str] = (),
    forbidden_attrs: Sequence[str] = (),
) -> dict[str, Any]:
    """AST audit of a Python source string. Does not execute. Never docker0."""

    tree = ast.parse(source)
    imported = imported_names(source)
    calls = call_func_names(source)
    shorts = call_short_names(source)
    attrs = attr_names(source)
    return {
        "imported_names": sorted(imported),
        "call_names": sorted(shorts),
        "attr_names": sorted(attrs),
        "string_constants": string_constants(source),
        "forbidden_imports": sorted(name for name in imported if name in set(forbidden_imports)),
        "forbidden_calls": sorted(name for name in shorts if name in set(forbidden_calls)),
        "forbidden_attrs": sorted(name for name in attrs if name in set(forbidden_attrs)),
        "score_issues": numeric_score_assignments(source, forbidden_scores),
        "score_keys": score_keys(source, forbidden_scores),
        "uses_lock_ex": any(
            isinstance(node, ast.Attribute) and node.attr == "LOCK_EX" for node in ast.walk(tree)
        ),
        "called_docker0": False,
        "call_func_names": sorted(calls),
    }


def pack_call_audit(
    out: Mapping[str, Any],
    *,
    required_calls: Sequence[str] = (),
    forbidden_call_names: Sequence[str] = (),
    extra: Optional[Mapping[str, Any]] = None,
    extra_ok: Sequence[bool] = (),
    flag_prefix: str = "uses_",
) -> dict[str, Any]:
    """Overlay required/forbidden Call names onto an AST audit. Live Calls stay in the consumer."""

    calls = set(out.get("call_names") or ())
    flags = {f"{flag_prefix}{name}": name in calls for name in required_calls}
    packed = {
        "imported_names": out.get("imported_names"),
        "forbidden_imports": out.get("forbidden_imports"),
        "forbidden_calls": out.get("forbidden_calls"),
        "score_assignments": list(out.get("score_keys") or ()),
        **flags,
        **dict(extra or {}),
    }
    packed["ok"] = bool(
        not out.get("forbidden_imports")
        and not out.get("forbidden_calls")
        and not out.get("forbidden_attrs")
        and not packed["score_assignments"]
        and all(name in calls for name in required_calls)
        and all(name not in calls for name in forbidden_call_names)
        and all(extra_ok)
    )
    return packed
