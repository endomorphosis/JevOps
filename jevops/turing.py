#!/usr/bin/env python3
"""Turing-machine tools on the neural tape + stack, feeding a decision transformer.

Tape: read / write / left / right / stay (bounded TAPE_N).
Stack: push / pop / peek (call_stack + TM aux stack).
Control: state, δ-table, step, bounded run, halt.
Decision transformer: (state, action, return-to-go milles) window from TM
history — the context TypeSafe/Grok consume. Jev does not write Lean.
Never docker0. Lake is the oracle. Not Arena scores.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

MILLE = 1000
MAX_TM_STEPS = 32
DT_WINDOW = 7
BLANK = "_"
TM_STEMS = (
    "turing",
    "tm_step",
    "tm_run",
    "tm_left",
    "tm_right",
    "tm_write",
    "tm_read",
    "tm_push",
    "tm_pop",
    "decision_transformer",
    "dt_context",
)


def is_tm_stem(stem: str) -> bool:
    text = str(stem or "").lower().replace("port_", "")
    if "thompson" in text:
        return False
    if text in {"tm", "dt"}:
        return True
    return any(tag in text for tag in TM_STEMS)


def _machine(memory: dict[str, Any]) -> dict[str, Any]:
    tm = memory.setdefault("nca", {}).setdefault("tm", {})
    tm.setdefault("state", "q0")
    tm.setdefault("halted", False)
    tm.setdefault("accepted", False)
    tm.setdefault("aux_stack", [])
    tm.setdefault("history", [])
    tm.setdefault("delta", {})
    return tm


def _tape(memory: dict[str, Any]):
    from jevops import tape as lra_tape

    tape = lra_tape.Tape.from_memory(memory)
    if not tape.cells:
        tape.write("blank", None, extra={"symbol": BLANK})
        tape.persist(memory)
    return tape


def _delta_lookup(tm: Mapping[str, Any], state: str, symbol: str) -> dict[str, str]:
    table = dict(tm.get("delta") or {})
    key = f"{state},{symbol}"
    row = table.get(key) or table.get(f"{state},*") or table.get("*,*")
    if isinstance(row, dict) and row.get("state"):
        return {
            "state": str(row.get("state") or state),
            "write": str(row.get("write") if row.get("write") is not None else symbol),
            "move": str(row.get("move") or "S"),
        }
    # Default scanner: halt on blank, else stay in q_run and move right.
    if symbol in {"", BLANK, "blank"}:
        return {"state": "q_halt", "write": BLANK, "move": "S"}
    return {"state": "q_run", "write": symbol, "move": "R"}


def tm_read(memory: dict[str, Any]) -> dict[str, Any]:
    tape = _tape(memory)
    tm = _machine(memory)
    sym = tape.read_symbol()
    tape.persist(memory)
    return {
        "ok": True,
        "kind": "port_tm_read",
        "symbol": sym,
        "state": tm.get("state"),
        "head": tape.head,
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }


def tm_write(memory: dict[str, Any], *, symbol: str = BLANK) -> dict[str, Any]:
    tape = _tape(memory)
    tm = _machine(memory)
    tape.poke(symbol)
    tape.persist(memory)
    _log(tm, "WRITE", symbol)
    return {
        "ok": True,
        "kind": "port_tm_write",
        "symbol": symbol,
        "head": tape.head,
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }


def tm_move(memory: dict[str, Any], *, direction: str = "R") -> dict[str, Any]:
    tape = _tape(memory)
    tm = _machine(memory)
    d = str(direction or "S").upper()[:1]
    if d == "L":
        tape.left()
        action = "LEFT"
    elif d == "R":
        tape.right(extend=True)
        action = "RIGHT"
    else:
        action = "STAY"
    tape.persist(memory)
    _log(tm, action, tape.read_symbol())
    return {
        "ok": True,
        "kind": "port_tm_left" if d == "L" else ("port_tm_right" if d == "R" else "port_tm_step"),
        "head": tape.head,
        "symbol": tape.read_symbol(),
        "action": action,
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }


def tm_push(memory: dict[str, Any], *, symbol: str = "") -> dict[str, Any]:
    from jevops import stack as lra_cs

    tape = _tape(memory)
    tm = _machine(memory)
    sym = str(symbol or tape.read_symbol())
    aux = list(tm.get("aux_stack") or [])
    aux.append(sym)
    tm["aux_stack"] = aux[-32:]
    stack = lra_cs.CallStack.from_dict(memory.get("_stack") or {})
    stack.call(f"ptr://cell/tm/{sym or 'blank'}", compose="call", node="tm_push")
    memory["_stack"] = stack.to_dict()
    tape.persist(memory)
    _log(tm, "PUSH", sym)
    return {
        "ok": True,
        "kind": "port_tm_push",
        "symbol": sym,
        "depth": len(tm["aux_stack"]),
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }


def tm_pop(memory: dict[str, Any]) -> dict[str, Any]:
    from jevops import stack as lra_cs

    tm = _machine(memory)
    aux = list(tm.get("aux_stack") or [])
    sym = aux.pop() if aux else BLANK
    tm["aux_stack"] = aux
    stack = lra_cs.CallStack.from_dict(memory.get("_stack") or {})
    if stack.depth():
        stack.ret({"symbol": sym, "ok": True})
        memory["_stack"] = stack.to_dict()
    _log(tm, "POP", sym)
    return {
        "ok": True,
        "kind": "port_tm_pop",
        "symbol": sym,
        "depth": len(aux),
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }


def _log(tm: dict[str, Any], action: str, symbol: str) -> None:
    hist = list(tm.get("history") or [])
    rtg = _rtg_m(tm)
    hist.append(
        {
            "state": str(tm.get("state") or "q0"),
            "action": action,
            "symbol": symbol,
            "rtg_m": rtg,
        }
    )
    tm["history"] = hist[-64:]


def _rtg_m(tm: Mapping[str, Any]) -> int:
    """Return-to-go milles: remaining steps until halt, scaled."""

    if tm.get("halted"):
        return 0
    n = len(tm.get("history") or [])
    return max(0, (MAX_TM_STEPS - n) * (MILLE // MAX_TM_STEPS))


def tm_step(memory: dict[str, Any]) -> dict[str, Any]:
    tape = _tape(memory)
    tm = _machine(memory)
    if tm.get("halted"):
        return {
            "ok": True,
            "kind": "port_tm_step",
            "halted": True,
            "state": tm.get("state"),
            "writes_lean": False,
            "integer": True,
        }
    symbol = tape.read_symbol()
    trans = _delta_lookup(tm, str(tm.get("state") or "q0"), symbol)
    tape.poke(trans["write"])
    move = trans["move"].upper()[:1]
    if move == "L":
        tape.left()
        action = "LEFT"
    elif move == "R":
        tape.right(extend=True)
        action = "RIGHT"
    else:
        action = "STAY"
    tm["state"] = trans["state"]
    if trans["state"] in {"q_halt", "halt", "q_accept", "q_reject"}:
        tm["halted"] = True
        tm["accepted"] = trans["state"] in {"q_halt", "q_accept", "halt"}
        action = "HALT"
    tape.persist(memory)
    _log(tm, action, tape.read_symbol())
    dt_context(memory)
    return {
        "ok": True,
        "kind": "port_tm_step",
        "state": tm.get("state"),
        "action": action,
        "symbol": tape.read_symbol(),
        "head": tape.head,
        "halted": bool(tm.get("halted")),
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }


def tm_run(memory: dict[str, Any], *, max_steps: int = MAX_TM_STEPS) -> dict[str, Any]:
    n = 0
    last: dict[str, Any] = {}
    for _ in range(max(1, int(max_steps))):
        last = tm_step(memory)
        n += 1
        if last.get("halted"):
            break
    last["kind"] = "port_tm_run"
    last["n_steps"] = n
    return last


def dt_context(memory: dict[str, Any]) -> dict[str, Any]:
    """Pack TM history as a decision-transformer window (s, a, R_t)."""

    tm = _machine(memory)
    hist = list(tm.get("history") or [])
    window = hist[-DT_WINDOW:]
    tokens = []
    for row in window:
        tokens.append(
            {
                "state": str(row.get("state") or ""),
                "action": str(row.get("action") or ""),
                "symbol": str(row.get("symbol") or ""),
                "rtg_m": int(row.get("rtg_m") or 0),
            }
        )
    memory.setdefault("nca", {})["dt"] = {
        "window": tokens,
        "n": len(hist),
        "halted": bool(tm.get("halted")),
        "integer": True,
    }
    ranked = [str(row.get("action") or "") for row in reversed(tokens) if row.get("action")]
    if ranked:
        from jevops.outer import head_seq

        memory["nca"]["pipeline_bias"] = head_seq(ranked, 8)
    return {
        "ok": True,
        "kind": "port_decision_transformer",
        "window": tokens,
        "n": len(hist),
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }


def call_tm(
    stem: str,
    *,
    memory: dict[str, Any],
    tactics: str = "",
    problem: str = "",
) -> dict[str, Any]:
    _ = (tactics, problem)
    text = str(stem or "").lower()
    if "decision_transformer" in text or "dt_context" in text or text.endswith("/dt") or text.endswith("_dt"):
        return dt_context(memory)
    if "push" in text:
        return tm_push(memory)
    if "pop" in text:
        return tm_pop(memory)
    if "read" in text:
        return tm_read(memory)
    if "write" in text:
        return tm_write(memory, symbol=BLANK)
    if "left" in text:
        return tm_move(memory, direction="L")
    if "right" in text:
        return tm_move(memory, direction="R")
    if "run" in text:
        return tm_run(memory)
    return tm_step(memory)
