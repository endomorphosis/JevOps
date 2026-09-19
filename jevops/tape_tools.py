#!/usr/bin/env python3
"""Tape context editor: splice, mask, pop, crop, keep-k, checkpoint, …

Manages the neural-tape window that feeds the decision transformer.
Does not write Lean. Never docker0. Distinct from MCA port_mask.
"""
from __future__ import annotations

from typing import Any, Optional

EDITOR_STEMS = (
    "tape_splice",
    "tape_mask",
    "tape_unmask",
    "tape_pop",
    "tape_peek",
    "tape_swap",
    "tape_dup",
    "tape_crop",
    "tape_keep",
    "tape_drop",
    "tape_compress",
    "tape_clear",
    "tape_rotate",
    "tape_mark",
    "tape_restore",
    "tape_attn",
)


def is_tape_editor_stem(stem: str) -> bool:
    text = str(stem or "").lower().replace("port_", "")
    if "conv" in text or "fft" in text:
        return False
    return text.startswith("tape_")


def _tape(memory: dict[str, Any]):
    from jevops import tape as lra_tape

    tape = lra_tape.Tape.from_memory(memory)
    return tape


def _ok(kind: str, tape, memory: dict[str, Any], **extra: Any) -> dict[str, Any]:
    tape.persist(memory)
    out = {
        "ok": True,
        "kind": kind,
        "n": len(tape.cells),
        "head": tape.head,
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }
    out.update(extra)
    return out


def call_tape_tool(
    stem: str,
    *,
    memory: dict[str, Any],
    tactics: str = "",
    problem: str = "",
) -> dict[str, Any]:
    _ = (tactics, problem)
    text = str(stem or "").lower()
    tape = _tape(memory)
    if "unmask" in text:
        n = tape.unmask_all()
        return _ok("port_tape_unmask", tape, memory, n_unmasked=n)
    if "mask" in text:
        n = tape.mask_window()
        return _ok("port_tape_mask", tape, memory, n_masked=n, visible=len(tape.window_visible()))
    if "splice" in text:
        tape.splice(kind="splice", payload={"problem": problem})
        return _ok("port_tape_splice", tape, memory)
    if "pop" in text:
        cell = tape.pop()
        return _ok("port_tape_pop", tape, memory, popped=str((cell or {}).get("symbol") or (cell or {}).get("kind") or ""))
    if "peek" in text:
        cell = tape.peek()
        return _ok("port_tape_peek", tape, memory, symbol=str((cell or {}).get("symbol") or (cell or {}).get("kind") or "_"))
    if "swap" in text:
        tape.swap()
        return _ok("port_tape_swap", tape, memory)
    if "dup" in text:
        tape.dup()
        return _ok("port_tape_dup", tape, memory)
    if "crop" in text:
        n = tape.crop()
        return _ok("port_tape_crop", tape, memory, kept=n)
    if "keep" in text:
        n = tape.keep_k(7)
        return _ok("port_tape_keep", tape, memory, kept=n)
    if "drop" in text:
        n = tape.drop_below(0.2)
        return _ok("port_tape_drop", tape, memory, dropped=n)
    if "compress" in text:
        n = tape.compress_blanks()
        return _ok("port_tape_compress", tape, memory, removed=n)
    if "clear" in text:
        n = tape.clear()
        return _ok("port_tape_clear", tape, memory, cleared=n)
    if "rotate" in text:
        tape.rotate(1)
        return _ok("port_tape_rotate", tape, memory)
    if "restore" in text:
        snap = ((memory.get("nca") or {}).get("tape_mark") or {})
        if snap:
            tape.restore(snap)
        return _ok("port_tape_restore", tape, memory, restored=bool(snap))
    if "mark" in text or "checkpoint" in text:
        snap = tape.checkpoint()
        memory.setdefault("nca", {})["tape_mark"] = snap
        return _ok("port_tape_mark", tape, memory, n_saved=len(snap.get("cells") or []))
    if "attn" in text:
        weights = tape.attn_m()
        return _ok("port_tape_attn", tape, memory, attn_m=weights)
    return {"ok": False, "reason": "unknown_tape_tool", "stem": stem, "writes_lean": False}
