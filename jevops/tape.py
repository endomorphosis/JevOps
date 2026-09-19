#!/usr/bin/env python3
"""Bounded neural tape: the TypeSafe context window.

A ring of cells. The head is the current theorem/node. TypeSafe reads a
window around the head, not the whole memory file. Child RETURN splices a
cell onto the parent tape. Jev does not write Lean. Never docker0.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

TAPE_N = 64
WINDOW = 7


def _cell(
    *,
    kind: str,
    payload: Any,
    energy: float = 0.5,
    ptr: str = "",
    parent_frame: str = "",
    tokens: int = 0,
    theorem_ok: Optional[bool] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "kind": str(kind),
        "payload": payload,
        "energy": float(energy),
        "ptr": str(ptr or ""),
        "parent_frame": str(parent_frame or ""),
        "tokens": int(tokens or 0),
        "theorem_ok": theorem_ok,
    }
    if extra:
        row.update(dict(extra))
    return row


class Tape:
    """Ring tape with a moving head."""

    def __init__(self, *, cells: Optional[list[dict[str, Any]]] = None, head: int = 0) -> None:
        self.cells: list[dict[str, Any]] = list(cells or [])
        self.head = int(head) if self.cells else 0
        self._trim()

    def _trim(self) -> None:
        overflow = len(self.cells) - TAPE_N
        if overflow > 0:
            self.cells = self.cells[overflow:]
            self.head = max(0, self.head - overflow)
        if self.cells:
            self.head = min(self.head, len(self.cells) - 1)

    def write(
        self,
        kind: str,
        payload: Any = None,
        *,
        energy: float = 0.5,
        ptr: str = "",
        parent_frame: str = "",
        tokens: int = 0,
        theorem_ok: Optional[bool] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        cell = _cell(
            kind=kind,
            payload=payload,
            energy=energy,
            ptr=ptr,
            parent_frame=parent_frame,
            tokens=tokens,
            theorem_ok=theorem_ok,
            extra=extra,
        )
        self.cells.append(cell)
        self.head = len(self.cells) - 1
        self._trim()
        return cell

    def window(self, width: int = WINDOW) -> list[dict[str, Any]]:
        if not self.cells:
            return []
        lo = max(0, self.head - int(width))
        hi = min(len(self.cells), self.head + int(width) + 1)
        return list(self.cells[lo:hi])

    def splice_return(
        self,
        payload: Mapping[str, Any],
        *,
        ptr: str = "",
        parent_frame: str = "",
    ) -> dict[str, Any]:
        """Inject a child evaluation onto the parent tape."""

        energy = float(payload.get("energy") or 0.5)
        if payload.get("theorem_ok") is True:
            energy = max(energy, 0.7)
        if payload.get("theorem_ok") is False:
            energy = min(energy, 0.3)
        return self.write(
            "return",
            {
                "observations": payload.get("observations") or {},
                "tactics_head": str(payload.get("tactics") or "")[:240],
                "n_steps": payload.get("n_steps"),
                "ok": payload.get("ok", True),
            },
            energy=energy,
            ptr=ptr,
            parent_frame=parent_frame,
            tokens=int(payload.get("tokens") or 0),
            theorem_ok=payload.get("theorem_ok") if "theorem_ok" in payload else None,
            extra={"injected": True, "node": payload.get("node")},
        )

    def to_dict(self) -> dict[str, Any]:
        return {"cells": list(self.cells[-TAPE_N:]), "head": self.head, "n": len(self.cells)}

    @classmethod
    def from_memory(cls, memory: Optional[Mapping[str, Any]]) -> "Tape":
        raw = (memory or {}).get("tape") or {}
        cells = list(raw.get("cells") or [])
        head = int(raw.get("head") or max(0, len(cells) - 1))
        return cls(cells=cells, head=head)

    def persist(self, memory: dict[str, Any]) -> None:
        memory["tape"] = self.to_dict()

    def read(self) -> Optional[dict[str, Any]]:
        if not self.cells:
            return None
        return self.cells[self.head]

    def read_symbol(self) -> str:
        cell = self.read()
        if not cell:
            return "_"
        return str(cell.get("symbol") or cell.get("kind") or "_")

    def poke(self, symbol: str, *, energy: Optional[float] = None) -> dict[str, Any]:
        """Overwrite the cell under the head (Turing write). Does not append."""

        if not self.cells:
            return self.write("blank", None, extra={"symbol": str(symbol or "_")})
        cell = self.cells[self.head]
        cell["symbol"] = str(symbol or "_")
        if energy is not None:
            cell["energy"] = float(energy)
        return cell

    def left(self) -> Optional[dict[str, Any]]:
        if not self.cells:
            return None
        self.head = max(0, self.head - 1)
        return self.read()

    def right(self, *, extend: bool = True) -> Optional[dict[str, Any]]:
        if not self.cells:
            return self.write("blank", None, extra={"symbol": "_"})
        if self.head + 1 >= len(self.cells):
            if extend and len(self.cells) < TAPE_N:
                self.write("blank", None, extra={"symbol": "_"})
            else:
                self.head = len(self.cells) - 1
                return self.read()
        else:
            self.head += 1
        return self.read()

    def seek(self, index: int) -> Optional[dict[str, Any]]:
        if not self.cells:
            return None
        self.head = max(0, min(int(index), len(self.cells) - 1))
        return self.read()

    def cells_for_frame(self, frame_id: str) -> list[dict[str, Any]]:
        fid = str(frame_id or "")
        return [cell for cell in self.cells if str(cell.get("parent_frame") or "") == fid]

    def peek(self) -> Optional[dict[str, Any]]:
        return self.read()

    def pop(self) -> Optional[dict[str, Any]]:
        """Remove the cell under the head. Head stays at the same index."""

        if not self.cells:
            return None
        cell = self.cells.pop(self.head)
        if self.cells:
            self.head = min(self.head, len(self.cells) - 1)
        else:
            self.head = 0
        return cell

    def splice(self, cell: Optional[Mapping[str, Any]] = None, *, payload: Any = None, kind: str = "splice") -> dict[str, Any]:
        """Insert a cell at the head (context splice)."""

        row = dict(cell) if cell else _cell(kind=kind, payload=payload, extra={"symbol": kind})
        if not self.cells:
            self.cells = [row]
            self.head = 0
            return row
        self.cells.insert(self.head, row)
        self._trim()
        return row

    def mask_window(self, width: int = WINDOW) -> int:
        n = 0
        lo = max(0, self.head - int(width))
        hi = min(len(self.cells), self.head + int(width) + 1)
        for i, cell in enumerate(self.cells):
            if lo <= i < hi and i != self.head:
                cell["masked"] = True
                n += 1
        return n

    def unmask_all(self) -> int:
        n = 0
        for cell in self.cells:
            if cell.get("masked"):
                cell["masked"] = False
                n += 1
        return n

    def window_visible(self, width: int = WINDOW) -> list[dict[str, Any]]:
        return [c for c in self.window(width) if not c.get("masked")]

    def swap(self) -> bool:
        if self.head <= 0 or not self.cells:
            return False
        i = self.head
        self.cells[i], self.cells[i - 1] = self.cells[i - 1], self.cells[i]
        return True

    def dup(self) -> Optional[dict[str, Any]]:
        cell = self.read()
        if not cell:
            return None
        return self.splice(dict(cell), kind=str(cell.get("kind") or "dup"))

    def crop(self, width: int = WINDOW) -> int:
        win = self.window(width)
        if not win:
            return 0
        head_cell = self.read()
        self.cells = win
        self.head = win.index(head_cell) if head_cell in win else min(self.head, len(win) - 1)
        return len(win)

    def keep_k(self, k: int) -> int:
        """Keep the k highest-energy cells; head follows the max."""

        k = max(1, int(k))
        if len(self.cells) <= k:
            return len(self.cells)
        ranked = sorted(self.cells, key=lambda c: float(c.get("energy") or 0.0), reverse=True)[:k]
        ranked.sort(key=lambda c: self.cells.index(c) if c in self.cells else 0)
        self.cells = ranked
        self.head = min(self.head, len(self.cells) - 1)
        return len(self.cells)

    def trim_bytes(self, max_bytes: int) -> int:
        """Drop lowest-energy cells until json size fits. Never admits Lean."""

        import json

        cap = max(64, int(max_bytes))
        dropped = 0

        def size() -> int:
            return len(json.dumps(self.cells, default=str, separators=(",", ":")))

        while self.cells and size() > cap:
            head = self.read()
            others = [c for c in self.cells if c is not head]
            if not others:
                if isinstance(head.get("payload"), str) and len(head["payload"]) > 32:
                    head["payload"] = head["payload"][: len(head["payload"]) // 2]
                    dropped += 1
                    continue
                break
            victim = min(others, key=lambda c: float(c.get("energy") or 0.0))
            self.cells.remove(victim)
            dropped += 1
            if self.cells:
                self.head = min(self.head, len(self.cells) - 1)
        return dropped

    def drop_below(self, energy: float = 0.2) -> int:
        kept = [c for c in self.cells if float(c.get("energy") or 0.0) >= float(energy)]
        n = len(self.cells) - len(kept)
        self.cells = kept
        self.head = min(self.head, max(0, len(self.cells) - 1))
        return n

    def compress_blanks(self) -> int:
        n = 0
        out: list[dict[str, Any]] = []
        for cell in self.cells:
            sym = str(cell.get("symbol") or cell.get("kind") or "")
            if sym in {"_", "blank"} and out and str(out[-1].get("symbol") or out[-1].get("kind") or "") in {"_", "blank"}:
                n += 1
                continue
            out.append(cell)
        self.cells = out
        if self.cells:
            self.head = min(self.head, len(self.cells) - 1)
        return n

    def rotate(self, n: int = 1) -> None:
        if not self.cells:
            return
        k = int(n) % len(self.cells)
        self.cells = self.cells[k:] + self.cells[:k]
        self.head = (self.head - k) % len(self.cells)

    def clear(self) -> int:
        n = len(self.cells)
        self.cells = []
        self.head = 0
        return n

    def attn_m(self, width: int = WINDOW) -> list[int]:
        """Energy milles over the visible window (attention weights)."""

        win = self.window_visible(width)
        out = []
        for cell in win:
            try:
                e = float(cell.get("energy") or 0.0)
            except (TypeError, ValueError):
                e = 0.0
            out.append(int(e * 1000) if e <= 2 else int(e))
        return out

    def checkpoint(self) -> dict[str, Any]:
        return {"cells": [dict(c) for c in self.cells], "head": self.head}

    def restore(self, snap: Mapping[str, Any]) -> None:
        self.cells = [dict(c) for c in (snap.get("cells") or [])]
        self.head = int(snap.get("head") or 0)
        self._trim()

    def populate(
        self,
        *,
        stack: Any = None,
        tactics: str = "",
        problem: str = "",
        observations: Optional[Mapping[str, Any]] = None,
        ptr: str = "",
    ) -> dict[str, Any]:
        """Write the current stack frame's args onto the tape for TypeSafe."""

        frame = stack.top() if stack is not None and hasattr(stack, "top") else None
        locals_ = dict((frame or {}).get("locals") or {})
        if tactics:
            locals_["tactics"] = tactics
        if problem:
            locals_["problem"] = problem
        cell = self.write(
            "args",
            {
                "locals": {k: locals_[k] for k in list(locals_)[:12]},
                "observations_keys": sorted((observations or {}).keys())[:16],
            },
            ptr=ptr or str((frame or {}).get("ptr") or ""),
            parent_frame=str((frame or {}).get("frame_id") or ""),
            extra={"node": (frame or {}).get("node")},
        )
        return cell


def populate_tape(
    tape: Tape,
    stack: Any,
    *,
    tactics: str = "",
    problem: str = "",
    observations: Optional[Mapping[str, Any]] = None,
    ptr: str = "",
) -> dict[str, Any]:
    return tape.populate(
        stack=stack,
        tactics=tactics,
        problem=problem,
        observations=observations,
        ptr=ptr,
    )
