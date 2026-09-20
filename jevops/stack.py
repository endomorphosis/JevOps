#!/usr/bin/env python3
"""Call stack and fail-closed ptr:// addresses for TypeSafe.

CALL pushes a frame; RETURN pops and yields a payload for the parent tape.
Pointers never exec Python. Jev does not write Lean. Never docker0.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

PTR_RE = re.compile(
    r"^ptr://(skill|family|theorem|module|tool|cell|subloop|mcpplusplus|goal|subgoal|task|codepath)/([A-Za-z0-9_./:-]+)$"
)
KINDS = (
    "skill",
    "family",
    "theorem",
    "module",
    "tool",
    "cell",
    "subloop",
    "mcpplusplus",
    "goal",
    "subgoal",
    "task",
    "codepath",
)
MAX_DEPTH = 3


def parse_ptr(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {"ok": False, "reason": "empty_ptr"}
    match = PTR_RE.match(raw)
    if match:
        return {"ok": True, "kind": match.group(1), "name": match.group(2), "ptr": raw}
    return {"ok": False, "reason": "unknown_ptr", "ptr": raw}


def coerce_ptr(text: str, *, tools: Optional[Mapping[str, Any]] = None) -> str:
    """Turn a nest_child / skill name into ptr://… or leave a valid pointer."""

    raw = str(text or "").strip()
    if raw.startswith("ptr://"):
        return raw
    if not raw:
        return ""
    tool_keys = set((tools or {}).keys())
    if raw in tool_keys:
        return f"ptr://tool/{raw}"
    if raw.endswith(".py") and "/" not in raw and ".." not in raw:
        return f"ptr://module/{raw}"
    if raw.startswith("port_") or raw.startswith("mem_"):
        return f"ptr://skill/{raw}"
    if raw in {"search_space", "dead_code", "strength_reduction", "algebraic_simplification", "pca_keep", "symbol_diffuse"}:
        return f"ptr://family/{raw}"
    if raw in {"skill_walk", "nca_tick", "nca_fork", "eval_theorem"}:
        return f"ptr://subloop/{raw}"
    if raw == "mcpplusplus" or raw.startswith("mcpplusplus/") or raw.startswith("p2p_"):
        name = raw.split("/", 1)[-1] if raw.startswith("mcpplusplus/") else ("catalog" if raw == "mcpplusplus" else raw)
        return f"ptr://mcpplusplus/{name}"
    if raw.startswith("LRA-G"):
        return f"ptr://goal/{raw}"
    if raw.startswith("LRA-S"):
        return f"ptr://subgoal/{raw}"
    if raw.startswith("LRA-") and raw[4:5].isdigit():
        return f"ptr://task/{raw}"
    if raw.startswith("harness.") or raw.startswith("codepath/"):
        name = raw.split("/", 1)[-1] if raw.startswith("codepath/") else raw
        return f"ptr://codepath/{name}"
    if "." in raw and not raw.startswith("port_"):
        return f"ptr://theorem/{raw}"
    return f"ptr://skill/{raw}"


def resolve_ptr(
    text: str,
    *,
    memory: Optional[Mapping[str, Any]] = None,
    record: Optional[Mapping[str, Any]] = None,
    tools: Optional[Mapping[str, Any]] = None,
    subloops: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Fail-closed pointer resolution. No exec of the name tail."""

    ptr = coerce_ptr(text, tools=tools)
    parsed = parse_ptr(ptr)
    if not parsed.get("ok"):
        return parsed
    kind = str(parsed["kind"])
    name = str(parsed["name"])
    payload: dict[str, Any] = {"kind": kind, "name": name, "ptr": ptr, "ok": True}
    if kind == "skill":
        payload["allow_skills"] = {name, name.replace("port_", ""), f"port_{name.replace('port_', '')}"}
    elif kind == "family":
        payload["allow_families"] = {name}
    elif kind == "theorem":
        rec_name = str((record or {}).get("name") or "")
        payload["theorem"] = name
        payload["same_record"] = name == rec_name
    elif kind == "module":
        if "/" in name or name.startswith(".") or not name.endswith(".py"):
            return {"ok": False, "reason": "module_not_allowed", "ptr": ptr}
        payload["path"] = name
    elif kind == "tool":
        if tools is not None and name not in tools:
            return {"ok": False, "reason": "unknown_tool", "ptr": ptr, "name": name}
        payload["tool"] = name
    elif kind == "cell":
        grid = ((memory or {}).get("nca") or {}).get("grid") or {}
        payload["cell"] = name
        payload["known"] = name in grid
    elif kind == "subloop":
        if subloops is not None and name not in subloops:
            return {"ok": False, "reason": "unknown_subloop", "ptr": ptr, "name": name}
        payload["subloop"] = name
    elif kind == "mcpplusplus":
        from typesafe_tools import MCPPLUSPLUS_TOOLS

        if name not in MCPPLUSPLUS_TOOLS:
            return {"ok": False, "reason": "unknown_mcpplusplus_tool", "ptr": ptr, "name": name}
        payload["mcpplusplus"] = name
        payload["protocol"] = "MCP++"
    elif kind in {"goal", "subgoal", "task"}:
        payload[kind + "_id"] = name
        payload["board"] = True
    elif kind == "codepath":
        payload["codepath"] = name
    return payload


CHILD_ARG_KEYS = (
    "tactics",
    "allow_families",
    "allow_skills",
    "problem",
    "path",
    "tool",
    "mcpplusplus",
    "subloop",
    "cell",
    "theorem",
    "ptr",
    "parent_frame_id",
    "tape_window",
    "node",
    "goal_id",
    "subgoal_id",
    "task_id",
    "codepath",
    "depends_on",
    "status",
)


def child_call_args(
    resolved: Mapping[str, Any],
    *,
    parent_locals: Optional[Mapping[str, Any]] = None,
    tactics: str = "",
    problem: str = "",
    tape_window: Optional[list[Any]] = None,
    parent_frame_id: str = "",
) -> dict[str, Any]:
    """Closed argument bag a parent frame passes to a child CALL. No secrets."""

    from jevops.outer import head_seq

    parent = dict(parent_locals or {})
    body = str(tactics or parent.get("tactics") or "")
    args: dict[str, Any] = {
        "ptr": str(resolved.get("ptr") or ""),
        "kind": str(resolved.get("kind") or ""),
        "name": str(resolved.get("name") or ""),
        "tactics": body,
        "problem": str(problem or parent.get("problem") or ""),
        "parent_frame_id": parent_frame_id,
        "tape_window": head_seq(tape_window or parent.get("tape_window"), 16),
        "node": str(resolved.get("name") or parent.get("node") or ""),
    }
    kind = str(resolved.get("kind") or "")
    if kind == "skill":
        args["allow_skills"] = sorted(resolved.get("allow_skills") or [])
    elif kind == "family":
        args["allow_families"] = sorted(resolved.get("allow_families") or [])
    elif kind == "theorem":
        args["theorem"] = str(resolved.get("theorem") or args["name"])
    elif kind == "module":
        args["path"] = str(resolved.get("path") or "")
    elif kind == "tool":
        args["tool"] = str(resolved.get("tool") or args["name"])
    elif kind == "mcpplusplus":
        args["mcpplusplus"] = str(resolved.get("mcpplusplus") or args["name"])
        args["protocol"] = "MCP++"
    elif kind == "subloop":
        args["subloop"] = str(resolved.get("subloop") or args["name"])
    elif kind == "cell":
        args["cell"] = str(resolved.get("cell") or args["name"])
    elif kind == "goal":
        args["goal_id"] = str(resolved.get("goal_id") or args["name"])
    elif kind == "subgoal":
        args["subgoal_id"] = str(resolved.get("subgoal_id") or args["name"])
    elif kind == "task":
        args["task_id"] = str(resolved.get("task_id") or args["name"])
    elif kind == "codepath":
        args["codepath"] = str(resolved.get("codepath") or args["name"])
    return {key: args[key] for key in list(args) if key in {"kind", "name", *CHILD_ARG_KEYS, "protocol"} and args.get(key) not in (None, "", [], set())}


class CallStack:
    def __init__(self, *, frames: Optional[list[dict[str, Any]]] = None) -> None:
        self.frames: list[dict[str, Any]] = list(frames or [])
        self.forest: dict[str, dict[str, Any]] = {str(f.get("frame_id")): dict(f) for f in self.frames if f.get("frame_id")}
        self._n = len(self.frames)

    def depth(self) -> int:
        return len(self.frames)

    def current(self) -> Optional[dict[str, Any]]:
        return self.top()

    def top(self) -> Optional[dict[str, Any]]:
        return self.frames[-1] if self.frames else None

    def tops(self, n: int = 3) -> list[dict[str, Any]]:
        if n <= 0:
            return []
        return list(self.frames[-n:])

    def get(self, frame_id: str) -> Optional[dict[str, Any]]:
        return self.forest.get(str(frame_id or ""))

    def parent(self, frame_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        frame = self.get(frame_id) if frame_id else self.top()
        if not frame:
            return None
        pid = str(frame.get("parent_id") or "")
        return self.forest.get(pid) if pid else None

    def children(self, frame_id: Optional[str] = None) -> list[dict[str, Any]]:
        frame = self.get(frame_id) if frame_id else self.top()
        if not frame:
            return []
        fid = str(frame.get("frame_id") or "")
        ids = list(frame.get("child_ids") or [])
        return [self.forest[cid] for cid in ids if cid in self.forest] or [
            row for row in self.forest.values() if str(row.get("parent_id") or "") == fid
        ]

    def ancestors(self, frame_id: Optional[str] = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cur = self.parent(frame_id)
        seen: set[str] = set()
        while cur and str(cur.get("frame_id") or "") not in seen:
            rows.append(cur)
            seen.add(str(cur.get("frame_id")))
            cur = self.parent(str(cur.get("frame_id") or ""))
        return rows

    def walk(self, frame_id: Optional[str] = None, *, _seen: Optional[set[str]] = None) -> list[dict[str, Any]]:
        """Root-to-leaves walk of the frame forest (parent then children)."""

        seen = _seen if _seen is not None else set()
        start = self.get(frame_id) if frame_id else None
        if start is None:
            roots = [f for f in self.forest.values() if not f.get("parent_id")]
            if not roots and self.frames:
                roots = [self.frames[0]]
            out: list[dict[str, Any]] = []
            for root in roots:
                out.extend(self.walk(str(root.get("frame_id") or ""), _seen=seen))
            return out
        fid = str(start.get("frame_id") or "")
        if not fid or fid in seen:
            return []
        seen.add(fid)
        ordered = [start]
        for child in self.children(fid):
            ordered.extend(self.walk(str(child.get("frame_id") or ""), _seen=seen))
        return ordered

    def set_local(self, key: str, value: Any, *, frame_id: Optional[str] = None) -> None:
        frame = self.get(frame_id) if frame_id else self.top()
        if not frame:
            return
        locals_ = dict(frame.get("locals") or {})
        locals_[str(key)] = value
        frame["locals"] = locals_
        live = self.top()
        if live and live.get("frame_id") == frame.get("frame_id"):
            live["locals"] = locals_

    def get_local(self, key: str, default: Any = None, *, frame_id: Optional[str] = None) -> Any:
        frame = self.get(frame_id) if frame_id else self.top()
        if not frame:
            return default
        return (frame.get("locals") or {}).get(key, default)

    def call(
        self,
        ptr: str,
        *,
        compose: str = "call",
        node: str = "",
        locals_: Optional[Mapping[str, Any]] = None,
        resolved: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        if self.depth() >= MAX_DEPTH:
            return {"ok": False, "reason": "max_depth", "ptr": ptr}
        parent = self.top()
        bound = child_call_args(
            resolved or {"ptr": ptr, "kind": "", "name": node},
            parent_locals=(parent or {}).get("locals") if parent else None,
            tactics=str((locals_ or {}).get("tactics") or (parent or {}).get("locals", {}).get("tactics") or ""),
            problem=str((locals_ or {}).get("problem") or ""),
            tape_window=list((locals_ or {}).get("tape_window") or []),
            parent_frame_id=str((parent or {}).get("frame_id") or ""),
        )
        bound.update({k: v for k, v in dict(locals_ or {}).items() if k in CHILD_ARG_KEYS or k in {"tactics", "problem"}})
        self._n += 1
        frame = {
            "frame_id": f"f{self._n}",
            "parent_id": str((parent or {}).get("frame_id") or ""),
            "ptr": ptr,
            "compose": compose,
            "node": node or ptr,
            "locals": bound,
            "child_ids": [],
            "return_slot": None,
            "live": True,
        }
        if parent:
            kids = list(parent.get("child_ids") or [])
            kids.append(frame["frame_id"])
            parent["child_ids"] = kids
            if parent.get("frame_id") in self.forest:
                self.forest[str(parent["frame_id"])]["child_ids"] = kids
        self.frames.append(frame)
        self.forest[frame["frame_id"]] = frame
        return {"ok": True, "frame": frame, "args": bound}

    def ret(self, payload: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        if not self.frames:
            return {"ok": False, "reason": "empty_stack", "payload": dict(payload or {})}
        child = self.frames.pop()
        child["return_slot"] = dict(payload or {})
        child["live"] = False
        self.forest[str(child.get("frame_id") or "")] = child
        parent = self.top()
        return {
            "ok": True,
            "child": child,
            "parent": parent,
            "payload": dict(payload or {}),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames": list(self.frames),
            "forest": dict(self.forest),
            "depth": self.depth(),
        }

    @classmethod
    def from_dict(cls, raw: Optional[Mapping[str, Any]]) -> "CallStack":
        data = dict(raw or {})
        stack = cls(frames=list(data.get("frames") or []))
        forest = dict(data.get("forest") or {})
        if forest:
            stack.forest = forest
        return stack


def walk_stack(stack: CallStack, *, frame_id: Optional[str] = None) -> list[dict[str, Any]]:
    return stack.walk(frame_id)


def parent_frame(stack: CallStack, frame_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    return stack.parent(frame_id)


def child_frames(stack: CallStack, frame_id: Optional[str] = None) -> list[dict[str, Any]]:
    return stack.children(frame_id)
