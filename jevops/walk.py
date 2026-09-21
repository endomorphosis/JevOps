#!/usr/bin/env python3
"""Inner-walk helpers: per-name flags, nested traces, draft filters.

Lake, Lean folds, and hosted Jev HTTP live in implementations.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence


def no_drafts_flag(memory: dict[str, Any], record: Mapping[str, Any], key: str) -> bool:
    obs = memory.setdefault("observations", {})
    name = str(record.get("name") or "")
    by = obs.get(f"{key}_by") or {}
    return bool(by.get(name))


def set_no_drafts_flag(memory: dict[str, Any], record: Mapping[str, Any], key: str, value: bool = True) -> None:
    obs = memory.setdefault("observations", {})
    name = str(record.get("name") or "")
    obs.setdefault(f"{key}_by", {})[name] = value


def flatten_trace(trace: list[Any]) -> list[dict[str, Any]]:
    """Unroll nested_trace children so depth is visible to the outer loop."""

    rows: list[dict[str, Any]] = []
    for event in trace or []:
        if not isinstance(event, dict):
            continue
        rows.append(event)
        rows.extend(flatten_trace(list(event.get("nested_trace") or [])))
    return rows


CONTROL = frozenset(
    {
        "nest",
        "spawn",
        "analyze",
        "self_improve",
        "invoke_router",
        "return",
        "tick",
        "fork",
        "mutate",
        "hook",
        "bandit",
        "call",
        "instruct",
        "heal",
    }
)
COMPOSE_CRITERIA: dict[str, dict[str, str]] = {
    "keep": {"what": "No skill; pop this tree node", "not_for": "When a shorter closed fold exists"},
    "single": {"what": "Apply only the winning skill at this node", "not_for": "When two skills commute and both shorten"},
    "pipeline": {
        "what": "Compose un-blacklisted skills in memory-weighted order",
        "not_for": "When a step is Noul-fired or binder-unsafe",
    },
    "nest": {
        "what": "Open a nested TypeSafe loop on one child family/skill, then keep looping here",
        "not_for": "When this node is already a leaf or already_minimal",
    },
    "spawn": {
        "what": "Spawn a callable named subloop and join its return",
        "not_for": "When no registered subloop exists",
    },
    "analyze": {
        "what": "Run a static-analysis tool then keep looping; no outer Grok",
        "not_for": "When the next step is an oracle apply",
    },
    "self_improve": {
        "what": "Mint/expand keep-structure skills from memory without outer Grok",
        "not_for": "When a lake-valid portable draft is already in hand",
    },
    "invoke_router": {
        "what": "Call the outer loop for a closed skill action",
        "not_for": "The default TypeSafe self-improve path",
    },
    "return": {
        "what": "Pop this subloop and return tactics/observations to the parent",
        "not_for": "The root walker unless the outer step is done",
    },
    "tick": {
        "what": "NCA tick: feed each cell its last state + neighbors + TypeSafe scores",
        "not_for": "When no grid has been seeded",
    },
    "fork": {
        "what": "Fork high-energy cells as returnable subloops",
        "not_for": "Unbounded nested grok",
    },
    "mutate": {
        "what": "Gated mutation of pipeline/skills/tactics from NCA energy",
        "not_for": "Arbitrary repo file rewrites",
    },
    "hook": {
        "what": "Hook, walk, and evaluate an implementation module",
        "not_for": "Paths outside the implementation root",
    },
    "bandit": {
        "what": "Select a tactic/action arm and wait for an explicit reward before updating its NCA cell",
        "not_for": "Using an unverified selection as a proof or code change",
    },
    "call": {
        "what": "CALL ptr://skill|theorem|module|tool|cell|subloop|mcpplusplus|goal|task|codepath/…",
        "not_for": "Unknown pointers, live P2P, docker0, or depth > 3",
    },
    "instruct": {
        "what": "Compile NCA IR and program work ops; never write Lean without an oracle",
        "not_for": "Letting a model write Lean without lake",
    },
    "heal": {
        "what": "Diagnose malformed NCA/tape/stack/program_state and apply closed repairs",
        "not_for": "Healthy state or rewriting Lean",
    },
}


def bias_compose_no_drafts(
    compose: str,
    *,
    memory: Optional[Mapping[str, Any]] = None,
    skills: Optional[Mapping[str, Any]] = None,
    skill: str = "keep",
    name: str = "",
) -> str:
    """When drafts are exhausted and budget is alive, program NCA instruct next."""

    obs = dict((memory or {}).get("observations") or {})
    tree = (obs.get("no_drafts_tree_by") or {}).get(name)
    instructed = (obs.get("no_drafts_instructed_by") or {}).get(name)
    if not tree or instructed:
        return compose
    if compose in {"instruct", "heal", "return", "call", "nest", "spawn"}:
        return compose
    portable = [key for key in (skills or {}) if key != "keep"]
    if portable and str(skill or "keep") not in {"keep", "None", ""}:
        return compose
    return "instruct"


def persist_view(memory: dict[str, Any], tape: Any, stack: Any) -> None:
    """Snapshot tape window and call-stack forest onto memory."""

    memory["_tape_window"] = tape.window()
    memory["_stack_top"] = stack.tops(3)
    memory["_stack"] = stack.to_dict()
    memory["_stack_walk"] = [
        {
            "frame_id": frame.get("frame_id"),
            "parent_id": frame.get("parent_id"),
            "ptr": frame.get("ptr"),
            "node": frame.get("node"),
            "child_ids": list(frame.get("child_ids") or []),
            "args": list((frame.get("locals") or {}).keys()),
        }
        for frame in stack.walk()
    ]
    tape.persist(memory)


def begin_root_frame(
    *,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
    problem: str,
    tactics: str,
) -> Any:
    """CALL the theorem root and trim the working set. No Lean. Returns tape."""

    from jevops import kernel as lra_kern

    if stack.depth() != 0:
        return tape
    stack.call(
        f"ptr://theorem/{problem or 'goal'}",
        compose="root",
        node="root",
        locals_={"tactics": tactics},
    )
    tape.write("theorem", str(problem or ""), ptr=f"ptr://theorem/{problem}", tokens=0)
    tape.persist(memory)
    try:
        lra_kern.apply_context_budget(memory)
        from jevops import tape as tape_mod

        return tape_mod.Tape.from_memory(memory)
    except Exception:
        return tape


def begin_session(
    *,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
    problem: str,
    body: str,
    depth: int = 0,
    link_fn: Optional[Any] = None,
    overlay_fn: Optional[Any] = None,
) -> Any:
    """Root CALL + persist + optional board link/overlay. No Lean."""

    if depth == 0 and stack.depth() == 0:
        tape = begin_root_frame(
            memory=memory,
            tape=tape,
            stack=stack,
            problem=problem,
            tactics=body,
        )
        if link_fn is not None:
            try:
                link_fn(memory, problem)
            except Exception:
                pass
    persist_view(memory, tape, stack)
    if depth == 0 and overlay_fn is not None:
        try:
            overlay_fn(memory)
        except Exception:
            pass
    return tape


def after_call(
    *,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
    body: str,
    problem: str,
    kind: str,
    payload: Any,
    ptr: str = "",
    energy: float = 0.5,
    theorem_ok: Optional[bool] = None,
    tokens: int = 0,
) -> None:
    """Tape event + NCA tick + cell upsert. Does not write Lean."""

    from jevops import nca as lra_nca

    tape.write(
        kind,
        payload,
        ptr=ptr,
        parent_frame=str((stack.top() or {}).get("frame_id") or ""),
        energy=energy,
        theorem_ok=theorem_ok,
        tokens=tokens,
    )
    lra_nca.tick(memory, tactics=body, problem=problem, focus=ptr or None)
    parent_ptr = str((stack.parent() or {}).get("ptr") or "")
    lra_nca.upsert_from_event(
        memory,
        ptr=ptr or f"ptr://cell/{kind}",
        kind=kind,
        energy=energy,
        theorem_ok=theorem_ok,
        tokens=tokens,
        parent_ptr=parent_ptr,
    )
    persist_view(memory, tape, stack)


def do_return(
    *,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
    body: str,
    problem: str,
    node: str,
    n_steps: int,
) -> dict[str, Any]:
    popped = stack.ret(
        {
            "tactics": body,
            "ok": True,
            "node": node,
            "observations": dict(memory.get("observations") or {}),
            "n_steps": n_steps,
        }
    )
    tape.splice_return(
        popped.get("payload") or {},
        ptr=str((popped.get("child") or {}).get("ptr") or ""),
        parent_frame=str((popped.get("parent") or {}).get("frame_id") or ""),
    )
    after_call(
        memory=memory,
        tape=tape,
        stack=stack,
        body=body,
        problem=problem,
        kind="return",
        payload={"node": node},
        ptr=str((popped.get("child") or {}).get("ptr") or ""),
    )
    return {"flow": "break", "trace": {"action": "return", "node": node, "stack": popped.get("ok")}}


def do_analyze(
    *,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
    body: str,
    problem: str,
    tool_name: str = "",
) -> dict[str, Any]:
    from jevops import tools as lra_tools

    obs = lra_tools.run_tool(
        tool_name or "decision_tree",
        tactics=body,
        memory=memory,
        problem=problem,
        observations=memory.get("observations") or {},
    )
    memory.setdefault("observations", {})[str(obs.get("tool") or "analyze")] = obs
    after_call(
        memory=memory,
        tape=tape,
        stack=stack,
        body=body,
        problem=problem,
        kind="tool",
        payload={"tool": obs.get("tool"), "ok": obs.get("ok")},
        ptr=f"ptr://tool/{obs.get('tool') or 'analyze'}",
    )
    return {"flow": "continue", "trace": {"action": "analyze", "tool": obs.get("tool"), "ok": obs.get("ok")}}


def do_self_improve(
    *,
    memory: dict[str, Any],
    body: str,
    problem: str,
) -> dict[str, Any]:
    from jevops import tools as lra_tools

    improved = lra_tools.self_improve(memory, name=problem, tactics=body)
    memory.setdefault("observations", {})["self_improve"] = improved
    return {
        "flow": "continue",
        "trace": {
            "action": "self_improve",
            "proposed": improved.get("proposed"),
            "router": None,
        },
    }


def do_nca_compose(
    *,
    compose: str,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
    body: str,
    problem: str,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    from jevops import hooks

    nca_key = {
        "tick": "nca_tick",
        "fork": "nca_fork",
        "mutate": "nca_mutate",
        "hook": "nca_hook",
        "bandit": "nca_bandit",
    }.get(compose)
    if not nca_key:
        return {"flow": "fallthrough"}
    nca_tool = hooks.resolve("nca_tool", "typesafe_nca", "nca_tool")
    extra_kw = {k: v for k, v in dict(extra or {}).items() if k not in {"memory", "tactics", "problem", "name"}}
    if nca_tool:
        payload = nca_tool(nca_key, memory=memory, tactics=body, problem=problem, **extra_kw)
    else:
        # The kernel has safe built-ins for the closed NCA transitions. A
        # consumer hook may still override them, but a standalone JevOps
        # harness can now execute the same transition graph.
        from jevops import nca as lra_nca

        payload = lra_nca.dispatch_tool(
            nca_key,
            memory=memory,
            tactics=body,
            problem=problem,
            **extra_kw,
        )
    memory.setdefault("observations", {})[nca_key] = payload
    nxt = body
    if compose == "mutate" and isinstance((payload.get("applied") or {}).get("tactics"), str):
        nxt = str(payload["applied"]["tactics"]).strip("\n")
    after_call(
        memory=memory,
        tape=tape,
        stack=stack,
        body=nxt,
        problem=problem,
        kind=compose,
        payload=payload,
        ptr=f"ptr://tool/nca_{compose}",
    )
    return {"flow": "continue", "body": nxt, "trace": {"action": compose, "nca": payload}}


def do_heal(
    *,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
    body: str,
    problem: str,
    ledger: Any = None,
) -> dict[str, Any]:
    from jevops import repair as lra_heal

    healed = lra_heal.heal(memory, ledger=ledger)
    memory.setdefault("observations", {})["nca_heal"] = healed
    after_call(
        memory=memory,
        tape=tape,
        stack=stack,
        body=body,
        problem=problem,
        kind="heal",
        payload=healed,
        ptr="ptr://tool/nca_heal",
        energy=0.7 if healed.get("ok") else 0.3,
    )
    return {
        "flow": "continue",
        "trace": {"action": "heal", "applied": healed.get("applied"), "ok": healed.get("ok")},
    }


def open_ptr_call(
    *,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
    body: str,
    problem: str,
    nest_child: str,
    record: Optional[Mapping[str, Any]] = None,
    node: str = "",
) -> dict[str, Any]:
    """Resolve ptr://, push a frame, populate tape. Kind payload is the caller's job."""

    from jevops import stack as lra_cs
    from jevops import tape as lra_tape
    from jevops import tools as lra_tools

    ptr = lra_cs.coerce_ptr(nest_child or node, tools=lra_tools.TOOL_CRITERIA)
    resolved = lra_cs.resolve_ptr(
        ptr,
        memory=memory,
        record=record,
        tools=lra_tools.TOOL_CRITERIA,
        subloops=lra_tools.SUBLOOPS,
    )
    if not resolved.get("ok"):
        after_call(
            memory=memory,
            tape=tape,
            stack=stack,
            body=body,
            problem=problem,
            kind="error",
            payload=resolved,
            ptr=ptr,
            energy=0.2,
        )
        return {"ok": False, "flow": "continue", "ptr": ptr, "resolved": resolved, "trace": {"action": "call_fail", "ptr": ptr, "reason": resolved.get("reason")}}
    pushed = stack.call(
        ptr,
        compose="call",
        node=str(resolved.get("name") or ""),
        locals_={"tactics": body, "problem": problem, "tape_window": tape.window()},
        resolved=resolved,
    )
    if not pushed.get("ok"):
        after_call(
            memory=memory,
            tape=tape,
            stack=stack,
            body=body,
            problem=problem,
            kind="error",
            payload=pushed,
            ptr=ptr,
            energy=0.2,
        )
        return {"ok": False, "flow": "continue", "ptr": ptr, "resolved": resolved}
    lra_tape.populate_tape(
        tape,
        stack,
        tactics=body,
        problem=problem,
        observations=memory.get("observations") or {},
        ptr=ptr,
    )
    return {
        "ok": True,
        "ptr": ptr,
        "resolved": resolved,
        "args": dict(pushed.get("args") or {}),
        "kind": str(resolved.get("kind") or ""),
    }


def close_ptr_call(
    *,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
    body: str,
    problem: str,
    ptr: str,
    child_payload: Mapping[str, Any],
) -> dict[str, Any]:
    popped = stack.ret(dict(child_payload))
    tape.splice_return(
        popped.get("payload") or dict(child_payload),
        ptr=ptr,
        parent_frame=str((popped.get("parent") or {}).get("frame_id") or ""),
    )
    after_call(
        memory=memory,
        tape=tape,
        stack=stack,
        body=body,
        problem=problem,
        kind="call_return",
        payload=dict(child_payload),
        ptr=ptr,
        energy=float(child_payload.get("energy") or 0.5),
        theorem_ok=child_payload.get("theorem_ok") if isinstance(child_payload.get("theorem_ok"), bool) else None,
        tokens=int(child_payload.get("tokens") or 0),
    )
    return {"flow": "continue", "trace": {"action": "call_return", "ptr": ptr, "kind": child_payload.get("kind"), "injected": True}}


def handle_call_kind(
    kind: str,
    *,
    memory: dict[str, Any],
    body: str,
    problem: str,
    resolved: Mapping[str, Any],
    args: Mapping[str, Any],
) -> dict[str, Any]:
    """Default CALL-kind payloads. Implementations may register ``call_kind:<kind>`` hooks."""

    from jevops import hooks
    from jevops import tools as lra_tools

    handler = hooks.get(f"call_kind:{kind}")
    if handler is not None:
        return dict(handler(memory=memory, body=body, problem=problem, resolved=resolved, args=args) or {})
    if kind == "tool":
        obs = lra_tools.run_tool(
            str(args.get("tool") or resolved.get("tool") or ""),
            tactics=str(args.get("tactics") or body),
            memory=memory,
            problem=str(args.get("problem") or problem),
        )
        memory.setdefault("observations", {})[str(obs.get("tool") or "tool")] = obs
        return {"ok": True, "observations": {obs.get("tool"): obs}}
    if kind == "mcpplusplus":
        envelope = lra_tools.mcpplusplus_call(
            str(args.get("mcpplusplus") or resolved.get("mcpplusplus") or "catalog"),
            problem=str(args.get("problem") or problem),
            tactics=str(args.get("tactics") or body),
        )
        memory.setdefault("observations", {})["mcpplusplus"] = envelope
        return {
            "ok": True,
            "observations": {"mcpplusplus": envelope},
            "protocol": "MCP++",
            "energy": 0.6 if envelope.get("ok") else 0.2,
        }
    board = hooks.resolve("board_payload", "board_graph", "board_payload")
    load_board = hooks.resolve("load_board", "board_graph", "load_lra_board")
    if kind in {"goal", "subgoal", "task"} and board:
        payload = board(str(resolved.get("name") or ""), load_board() if load_board else None)
        memory.setdefault("observations", {})["board"] = payload
        return {
            "ok": True,
            "observations": {"board": payload},
            "energy": 0.2 if payload.get("blocked") else 0.6,
        }
    slice_cp = hooks.resolve("slice_codepath", "codepath_graph", "slice_cross_module")
    if kind == "codepath" and slice_cp:
        sliced = slice_cp(str(args.get("codepath") or resolved.get("codepath") or resolved.get("name") or ""))
        memory.setdefault("observations", {})["codepath"] = sliced
        return {"ok": True, "observations": {"codepath": sliced}, "energy": 0.6 if sliced.get("ok") else 0.2}
    nca_tool = hooks.resolve("nca_tool", "typesafe_nca", "nca_tool")
    if kind == "module" and nca_tool:
        hook = nca_tool("nca_hook", path=str(resolved.get("path") or ""))
        memory.setdefault("observations", {})["hook"] = hook
        return {"ok": True, "observations": {"hook": hook}}
    return {"ok": True, "kind": kind, "deferred": True}


def halt_step(
    memory: dict[str, Any],
    *,
    depth: int,
    name: str = "",
    round_i: int = 0,
) -> dict[str, Any]:
    """Return a terminal step for idle/budget-dead state; cold seed does not halt."""

    from jevops import nca as lra_nca

    halt = lra_nca.should_halt(memory)
    if halt.get("budget_dead"):
        return {
            "flow": "break",
            "halt": halt,
            "trace": {"depth": depth, "action": "nca_budget", "budget_energy": halt.get("budget_energy")},
            "lake": {"name": name, "skipped": "nca_budget", "round": round_i},
        }
    if halt.get("halt"):
        return {
            "flow": "break",
            "halt": halt,
            "trace": {
                "depth": depth,
                "action": "nca_halt",
                **{k: halt[k] for k in ("n_issues", "n_pending_ops", "n_hot_tasks")},
            },
            "lake": {"name": name, "skipped": "nca_halt", "round": round_i},
        }
    return {"flow": "continue", "halt": halt}


def absorb_nested(
    memory: dict[str, Any],
    nested: Mapping[str, Any],
    *,
    compose: str,
    child: str,
    depth: int,
    body: str,
    lake: list[dict[str, Any]],
) -> dict[str, Any]:
    lake.extend(list(nested.get("lake") or []))
    nxt = body
    if nested.get("tactics"):
        nxt = str(nested["tactics"]).strip("\n")
    returns = memory.setdefault("subloop_returns", [])
    returns.append(
        {
            "name": child,
            "ok": nested.get("ok", True),
            "n_steps": nested.get("n_steps"),
            "returned": True,
        }
    )
    return {
        "body": nxt,
        "trace": {
            "depth": depth,
            "action": "spawn_return" if compose == "spawn" else "nest_return",
            "child": child,
            "nested_trace": nested.get("trace") or [],
        },
    }


def do_instruct(
    *,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
    body: str,
    problem: str,
    ledger: Any = None,
    compile_fn: Any = None,
    record: Optional[Mapping[str, Any]] = None,
    args: Any = None,
    restore: bytes = b"",
    lake_round: Optional[Any] = None,
    round_i: int = 0,
) -> dict[str, Any]:
    from jevops import program as lra_prog

    programmed = lra_prog.program_nca(
        memory,
        tactics=body,
        problem=problem,
        llm="off",
        ledger=ledger,
        compile_fn=compile_fn,
        record=record,
        args=args,
        restore=restore,
    )
    memory.setdefault("observations", {})["nca_program"] = programmed
    before = body
    nxt = str((programmed.get("executed") or {}).get("tactics") or (programmed.get("program_state") or {}).get("tactics") or "")
    if nxt.strip():
        nxt = nxt.strip("\n")
    else:
        nxt = body
    lake_rows: list[dict[str, Any]] = []
    already_laked = any(
        str(op.get("op")) == "CALL" and str(op.get("ptr") or "").startswith("ptr://skill/") and op.get("ok")
        for op in ((programmed.get("executed") or {}).get("ran") or [])
    )
    if lake_round is not None and compile_fn is not None and nxt.strip("\n") != before.strip("\n") and not already_laked:
        accepted, rows = lake_round(
            record=record or {"name": problem},
            tactics=before,
            analysis={"n_tokens": max(8, len(before.split()))},
            drafts=[
                {
                    "kind": "nca_instruct",
                    "tactics": nxt,
                    "family": "search_space",
                    "token_count": max(1, len(nxt.split())),
                }
            ],
            intent={"skill": "nca_instruct", "compose": "single"},
            ranked={"beam_kinds": ["nca_instruct"], "fired": False, "fired_leaves": []},
            memory=memory,
            args=args,
            restore=restore,
            round_i=round_i,
            compile_one=compile_fn,
        )
        lake_rows = list(rows or [])
        if accepted:
            nxt = str(accepted).strip("\n")
    after_call(
        memory=memory,
        tape=tape,
        stack=stack,
        body=nxt,
        problem=problem,
        kind="instruct",
        payload=programmed.get("program_state") or {},
        ptr="ptr://tool/nca_program",
    )
    return {
        "flow": "continue",
        "body": nxt,
        "lake": lake_rows,
        "trace": {"action": "instruct", "ops": (programmed.get("program_state") or {}).get("ops")},
    }


def do_nest_or_spawn(
    *,
    compose: str,
    nest_child: str,
    tree: Mapping[str, Any],
    subloops: Mapping[str, Any],
    depth: int,
    max_depth: int,
    spawn_fn: Optional[Any] = None,
    nest_fn: Optional[Any] = None,
    allow_families: Optional[set[str]] = None,
) -> dict[str, Any]:
    if compose not in {"nest", "spawn"} or depth >= max_depth:
        return {"flow": "fallthrough"}
    child = nest_child or ("skill_walk" if compose == "spawn" else "")
    if not child:
        return {"flow": "continue", "nested": {}}
    if compose == "spawn" and child in subloops and child not in tree and spawn_fn is not None:
        nested = spawn_fn(child)
        return {"flow": "absorb", "child": child, "nested": nested or {}}
    if nest_fn is None:
        return {"flow": "fallthrough"}
    if child in tree:
        child_fam: Optional[set[str]] = {child}
        child_sk: Optional[set[str]] = None
    else:
        child_fam = allow_families
        child_sk = {child}
    nested = nest_fn(child=child, allow_families=child_fam, allow_skills=child_sk)
    return {"flow": "absorb", "child": child, "nested": nested or {}}


def skip_lake_row(
    *,
    name: str,
    depth: int,
    node: str,
    round_i: int,
    skip_lake: bool,
    compose: str,
) -> Optional[dict[str, Any]]:
    if (skip_lake or compose == "keep") and compose not in CONTROL:
        return {
            "name": name,
            "round": round_i,
            "skipped": "intent_minimal" if skip_lake else "compose_keep",
            "depth": depth,
            "node": node,
        }
    return None


def dispatch_control(
    *,
    compose: str,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
    body: str,
    problem: str,
    node: str = "",
    n_steps: int = 0,
    tool_name: str = "",
    extra: Optional[Mapping[str, Any]] = None,
    ledger: Any = None,
    compile_fn: Any = None,
    record: Optional[Mapping[str, Any]] = None,
    args: Any = None,
    restore: bytes = b"",
    lake_round: Optional[Any] = None,
    round_i: int = 0,
    intent: Optional[Mapping[str, Any]] = None,
    router_fn: Optional[Any] = None,
    skip_lake: bool = False,
    name: Any = "",
    depth: int = 0,
) -> dict[str, Any]:
    """Closed CONTROL composes. flow=fallthrough means drafts/oracle next."""

    if compose == "return":
        out = do_return(
            memory=memory, tape=tape, stack=stack, body=body, problem=problem, node=node, n_steps=n_steps
        )
        return {"flow": "break", "trace": out["trace"], "body": body}
    if compose == "analyze":
        out = do_analyze(
            memory=memory,
            tape=tape,
            stack=stack,
            body=body,
            problem=problem,
            tool_name=tool_name or "decision_tree",
        )
        return {"flow": "continue", "trace": out["trace"], "body": body}
    if compose == "self_improve":
        out = do_self_improve(memory=memory, body=body, problem=problem)
        return {"flow": "continue", "trace": out["trace"], "body": body}
    if compose in {"tick", "fork", "mutate", "hook", "bandit"}:
        out = do_nca_compose(
            compose=compose,
            memory=memory,
            tape=tape,
            stack=stack,
            body=body,
            problem=problem,
            extra=extra,
        )
        nxt = str(out.get("body") or body)
        return {"flow": "continue", "trace": out.get("trace") or {}, "body": nxt}
    if compose == "heal":
        out = do_heal(memory=memory, tape=tape, stack=stack, body=body, problem=problem, ledger=ledger)
        return {"flow": "continue", "trace": out["trace"], "body": body}
    if compose == "instruct":
        out = do_instruct(
            memory=memory,
            tape=tape,
            stack=stack,
            body=body,
            problem=problem,
            ledger=ledger,
            compile_fn=compile_fn,
            record=record,
            args=args,
            restore=restore,
            lake_round=lake_round,
            round_i=round_i,
        )
        return {
            "flow": "continue",
            "trace": out["trace"],
            "body": str(out.get("body") or body),
            "lake": list(out.get("lake") or []),
        }
    if compose == "invoke_router":
        out = do_invoke_router(
            memory=memory,
            body=body,
            problem=problem,
            intent=intent or {},
            router_fn=router_fn,
            ledger=ledger,
        )
        return {"flow": "continue", "trace": out["trace"], "body": body}
    skipped = skip_lake_row(
        name=name,
        depth=depth,
        node=node,
        round_i=round_i,
        skip_lake=skip_lake,
        compose=compose,
    )
    if skipped:
        return {"flow": "break", "lake": [skipped], "body": body}
    return {"flow": "fallthrough", "body": body}


def handle_ptr_call(
    *,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
    body: str,
    problem: str,
    nest_child: str,
    record: Optional[Mapping[str, Any]] = None,
    node: str = "",
    theorem_fn: Optional[Any] = None,
    nest_fn: Optional[Any] = None,
    depth: int = 0,
    max_depth: int = 3,
    round_i: int = 0,
) -> dict[str, Any]:
    """Open ptr://, run kind handler or theorem_fn, close. No Lean in the kernel."""

    opened = open_ptr_call(
        memory=memory,
        tape=tape,
        stack=stack,
        body=body,
        problem=problem,
        nest_child=nest_child or node,
        record=record,
        node=node,
    )
    if not opened.get("ok"):
        return {"flow": "continue", "ok": False, "trace": opened.get("trace"), "body": body, "lake": []}
    ptr = str(opened["ptr"])
    resolved = dict(opened.get("resolved") or {})
    child_args = dict(opened.get("args") or {})
    child_payload: dict[str, Any] = {"ok": True, "ptr": ptr, "kind": resolved.get("kind"), "args": child_args}
    kind = str(opened.get("kind") or "")
    lake: list[dict[str, Any]] = []
    nxt = body
    if kind == "theorem" and theorem_fn is not None:
        evaled = dict(
            theorem_fn(
                str(resolved.get("theorem") or resolved.get("name") or ""),
                tactics=str(child_args.get("tactics") or body),
                resolved=resolved,
                args=child_args,
            )
            or {}
        )
        child_payload.update(evaled)
        lake.append(
            {
                "name": evaled.get("name") or (record or {}).get("name"),
                "kind": "ptr_theorem",
                "ok": evaled.get("theorem_ok"),
                "tokens": evaled.get("tokens"),
                "round": round_i,
                "skipped": evaled.get("reason"),
            }
        )
    else:
        handled = handle_call_kind(
            kind,
            memory=memory,
            body=body,
            problem=problem,
            resolved=resolved,
            args=child_args,
        )
        if handled.get("deferred") and nest_fn is not None and depth < max_depth:
            nested = nest_fn(
                tactics=str(child_args.get("tactics") or body),
                node=str(child_args.get("node") or resolved.get("name") or node),
                allow_families=set(child_args.get("allow_families") or resolved.get("allow_families") or []) or None,
                allow_skills=set(child_args.get("allow_skills") or resolved.get("allow_skills") or []) or None,
            ) or {}
            lake.extend(list(nested.get("lake") or []))
            if nested.get("tactics"):
                nxt = str(nested["tactics"]).strip("\n")
            child_payload.update(
                {
                    "tactics": nested.get("tactics"),
                    "observations": nested.get("observations"),
                    "n_steps": nested.get("n_steps"),
                }
            )
        else:
            child_payload.update(handled)
    closed = close_ptr_call(
        memory=memory,
        tape=tape,
        stack=stack,
        body=nxt,
        problem=problem,
        ptr=ptr,
        child_payload=child_payload,
    )
    return {"flow": "continue", "ok": True, "trace": closed.get("trace"), "body": nxt, "lake": lake}


def no_drafts_step(
    *,
    memory: dict[str, Any],
    record: Mapping[str, Any],
    body: str,
    problem: str,
    intent: Mapping[str, Any],
    depth: int,
    node: str,
    name: Any = "",
    round_i: int = 0,
    ledger: Any = None,
    compile_fn: Any = None,
    args: Any = None,
    restore: bytes = b"",
) -> dict[str, Any]:
    from jevops import nca as lra_nca

    if no_drafts_flag(memory, record, "no_drafts_tree"):
        halt = lra_nca.should_halt(memory)
        if not halt.get("budget_dead") and not no_drafts_flag(memory, record, "no_drafts_instructed"):
            set_no_drafts_flag(memory, record, "no_drafts_instructed")
            instructed = no_drafts_instruct(
                memory=memory,
                body=body,
                problem=problem,
                ledger=ledger,
                compile_fn=compile_fn,
                record=record,
                args=args,
                restore=restore,
                depth=depth,
            )
            return {
                "flow": "continue",
                "body": str(instructed.get("body") or body),
                "trace": instructed.get("trace"),
            }
        return {
            "flow": "break",
            "lake": [
                {
                    "name": name or record.get("name"),
                    "round": round_i,
                    "skipped": "no_drafts_after_self_improve",
                    "depth": depth,
                    "node": node,
                }
            ],
            "body": body,
        }
    improved = no_drafts_self_improve(
        memory=memory,
        body=body,
        problem=problem,
        intent=intent,
        depth=depth,
        node=node,
        name=str(name or record.get("name") or ""),
        round_i=round_i,
    )
    return {
        "flow": "continue",
        "ranked": dict(improved.get("ranked") or {}),
        "lake": [improved["lake"]],
        "trace": improved.get("trace"),
        "body": body,
    }


def admit_step(
    *,
    pick_fn: Any,
    record: Mapping[str, Any],
    analysis: Mapping[str, Any],
    drafts: list[dict[str, Any]],
    ledger: Any,
    memory: dict[str, Any],
    intent: Mapping[str, Any],
    lake_round: Any,
    body: str,
    args: Any,
    restore: bytes,
    round_i: int,
    compile_fn: Any,
) -> dict[str, Any]:
    """Pick drafts then admit via the injected oracle round. No Lean in the kernel."""

    ranked = pick_fn(record, analysis, drafts, ledger=ledger, memory=memory)
    ranked["intent"] = intent
    if ledger is not None:
        from jevops.nca import charge_budget

        charge_budget(memory, ledger=ledger, event="jev_pick")
    accepted, lake_step = lake_round(
        record=record,
        tactics=body,
        analysis=analysis,
        drafts=drafts,
        intent=intent,
        ranked=ranked,
        memory=memory,
        args=args,
        restore=restore,
        round_i=round_i,
        compile_one=compile_fn,
    )
    ok_any = any(item.get("ok") for item in (lake_step or []))
    nxt = str(accepted).strip("\n") if accepted else body
    return {
        "flow": "continue" if accepted else "break",
        "body": nxt,
        "lake": list(lake_step or []),
        "ranked": ranked,
        "ok": ok_any,
        "tokens": int(analysis.get("n_tokens") or 0),
    }


def reset_pass_flags(memory: dict[str, Any]) -> None:
    obs = memory.setdefault("observations", {})
    obs.pop("no_drafts_tree", None)
    obs.pop("no_drafts_instructed", None)
    obs["no_drafts_tree_by"] = {}
    obs["no_drafts_instructed_by"] = {}
    nca = memory.setdefault("nca", {})
    nca.setdefault("program_state", {})["last_ran"] = []
    nca["journal"] = [
        row
        for row in (nca.get("journal") or [])
        if str(row.get("event") or "") not in {"call", "instruct", "jev", "jev_pick", "grok"}
    ]


def walk_result(
    *,
    body: str,
    lake: list[dict[str, Any]],
    ranked: Mapping[str, Any],
    drafts: list[dict[str, Any]],
    analysis: Mapping[str, Any],
    trace: list[dict[str, Any]],
    n_steps: int,
    depth: int,
    node: str,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
) -> dict[str, Any]:
    tape.persist(memory)
    return {
        "tactics": body,
        "lake": lake,
        "ranked": ranked,
        "drafts": drafts,
        "analysis": analysis,
        "trace": trace,
        "n_steps": n_steps,
        "depth": depth,
        "node": node,
        "jev_generated_lean": False,
        "called_docker0": False,
        "returned": True,
        "observations": dict(memory.get("observations") or {}),
        "tape": tape.to_dict(),
        "stack": stack.to_dict(),
    }


def do_invoke_router(
    *,
    memory: dict[str, Any],
    body: str,
    problem: str,
    intent: Mapping[str, Any],
    router_fn: Optional[Any] = None,
    ledger: Any = None,
) -> dict[str, Any]:
    from jevops.outer import apply_action
    from jevops import tools as lra_tools

    action = None
    if router_fn is not None:
        action = router_fn(intent=intent, memory=memory, ledger=ledger)
    if isinstance(action, dict) and action.get("action"):
        applied = apply_action(memory, action)
        return {
            "flow": "continue",
            "trace": {"action": "invoke_router", "router_action": action.get("action"), "applied": applied},
        }
    improved = lra_tools.self_improve(memory, name=problem, tactics=body)
    return {
        "flow": "continue",
        "trace": {
            "action": "invoke_router_fallback_self_improve",
            "proposed": improved.get("proposed"),
        },
    }


def no_drafts_instruct(
    *,
    memory: dict[str, Any],
    body: str,
    problem: str,
    ledger: Any = None,
    compile_fn: Any = None,
    record: Optional[Mapping[str, Any]] = None,
    args: Any = None,
    restore: bytes = b"",
    depth: int = 0,
) -> dict[str, Any]:
    from jevops import program as lra_prog

    programmed = lra_prog.program_nca(
        memory,
        tactics=body,
        problem=problem,
        llm="off",
        ledger=ledger,
        compile_fn=compile_fn,
        record=record,
        args=args,
        restore=restore,
    )
    nxt = str((programmed.get("executed") or {}).get("tactics") or "")
    if nxt.strip():
        nxt = nxt.strip("\n")
    else:
        nxt = body
    return {
        "flow": "continue",
        "body": nxt,
        "trace": {"depth": depth, "action": "no_drafts_instruct", "ops": (programmed.get("executed") or {}).get("ran")},
    }


def no_drafts_self_improve(
    *,
    memory: dict[str, Any],
    body: str,
    problem: str,
    intent: Mapping[str, Any],
    depth: int,
    node: str,
    name: str = "",
    round_i: int = 0,
) -> dict[str, Any]:
    from jevops import tools as lra_tools

    improved = lra_tools.self_improve(memory, name=problem, tactics=body)
    tree_obs = lra_tools.run_tool(
        "decision_tree",
        tactics=body,
        memory=memory,
        problem=problem,
        observations=memory.get("observations") or {},
    )
    set_no_drafts_flag(memory, {"name": problem}, "no_drafts_tree")
    memory.setdefault("observations", {})["no_drafts_tree"] = tree_obs
    memory["observations"]["self_improve"] = improved
    return {
        "flow": "continue",
        "ranked": {
            "skipped": True,
            "reason": "no_drafts_self_improve",
            "intent": dict(intent),
            "jev_generated_lean": False,
            "arena_score": None,
        },
        "lake": {
            "name": name,
            "round": round_i,
            "skipped": "no_drafts_self_improve",
            "depth": depth,
            "node": node,
            "proposed": improved.get("proposed"),
        },
        "trace": {"depth": depth, "action": "no_drafts_self_improve", "proposed": improved.get("proposed")},
    }


def restrict_drafts(
    drafts: list[dict[str, Any]],
    *,
    skip_port: Optional[set[str]] = None,
    allow_skills: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    # These are closed benchmark kernels whose bodies are still submitted to
    # Lake.  A recursive TypeSafe leaf may narrow ``allow_skills`` to an
    # unrelated local family; dropping a known verifier-backed kernel there
    # would make the outer loop unable to rediscover an existing best.  Keep
    # the kernel visible, but never treat it as accepted without the oracle.
    verifier_backed = {"inits_replay", "inits_best"}
    rows = list(drafts)
    blocked = set(skip_port or ())
    if blocked:
        blocked = {f"port_{name}" for name in blocked} | set(blocked)
        rows = [
            item
            for item in rows
            if str(item.get("kind") or "") not in blocked
            and not any(
                str(item.get("kind") or "").endswith(name) or name in str(item.get("kind") or "")
                for name in (skip_port or ())
            )
        ]
    if allow_skills:
        want = set(allow_skills) | {f"port_{s}" for s in allow_skills} | {s.replace("port_", "") for s in allow_skills}
        rows = [
            item
            for item in rows
            if str(item.get("kind") or "") in want
            or str(item.get("kind") or "").replace("port_", "") in want
            or str(item.get("kind") or "").startswith("port_pipeline")
            or str(item.get("kind") or "") in verifier_backed
        ]
    return rows


def nest_criteria(
    tree: Mapping[str, Any],
    *,
    tools: Optional[Mapping[str, Any]] = None,
    subloops: Optional[Mapping[str, Any]] = None,
    walk_name: str = "skill_walk",
) -> dict[str, dict[str, str]]:
    """Choice criteria for nest/spawn children. No Lean."""

    from jevops.outer import head_chars, head_seq

    out: dict[str, dict[str, str]] = {
        fam: {"what": f"Nested TypeSafe loop over {fam}: {head_chars(', '.join(str(k) for k in kids), 160)}"}
        for fam, kids in (tree or {}).items()
        if kids
    }
    for kids in (tree or {}).values():
        for kid in head_seq(kids, 8):
            out.setdefault(str(kid), {"what": f"Nested TypeSafe loop on skill {kid}"})
    out.setdefault(walk_name, {"what": f"Spawn the TypeSafe {walk_name} subloop and join its return"})
    for tool_name, spec in dict(tools or {}).items():
        if isinstance(spec, Mapping):
            out.setdefault(str(tool_name), {str(k): str(v) for k, v in spec.items()})
        else:
            out.setdefault(str(tool_name), {"what": str(spec)})
    for sub_name in dict(subloops or {}):
        out.setdefault(str(sub_name), {"what": f"Spawn registered subloop {sub_name}"})
    return out


def extra_payload(
    compose: str,
    *,
    nest_child: str = "",
    tool_name: str = "",
    fork: Optional[Mapping[str, Any]] = None,
    default_hook: str = "",
) -> dict[str, Any]:
    """Closed extra kwargs for nest/spawn/hook. No Lean."""

    kind = str(compose or "")
    if kind == "fork":
        return dict(fork or {})
    if kind == "hook":
        return {"path": nest_child or tool_name or default_hook}
    return {}


def pack_canary(
    walked: Mapping[str, Any],
    *,
    clone_exists: bool = True,
    skipped: str = "",
    name: Any = "",
) -> dict[str, Any]:
    """Compact inner-walk result for an outer canary row. No Lean."""

    if skipped:
        analysis = dict((walked or {}).get("analysis") or {})
        packed_analysis = (
            {k: analysis[k] for k in analysis if k != "tactics"} if analysis else {"name": name}
        )
        row_name = packed_analysis.get("name") or name
        return {
            "analysis": packed_analysis,
            "n_drafts": 0,
            "draft_kinds": [],
            "ranked": {"skipped": True, "reason": skipped},
            "lake": [{"name": row_name, "skipped": skipped}],
            "trace": [{"action": skipped}],
            "clone_exists": False,
            "n_steps": 0,
        }
    analysis = walked.get("analysis") or {}
    drafts = list(walked.get("drafts") or [])
    return {
        "analysis": {k: analysis[k] for k in analysis if k != "tactics"} if analysis else {},
        "n_drafts": len(drafts),
        "draft_kinds": [item.get("kind") for item in drafts],
        "ranked": walked.get("ranked") or {},
        "lake": list(walked.get("lake") or []),
        "trace": list(walked.get("trace") or []),
        "clone_exists": bool(clone_exists),
        "tactics": walked.get("tactics"),
        "n_steps": walked.get("n_steps"),
        "returned": True,
        "observations": walked.get("observations") or {},
    }


def run_nested(
    *,
    tactics: str,
    dest: Any,
    restore: bytes,
    name: Any = "",
    analyze_fn: Callable[..., Mapping[str, Any]],
    pack_fn: Callable[..., Mapping[str, Any]],
    budget_fn: Callable[[], tuple[int, int]],
    walk_fn: Callable[..., Mapping[str, Any]],
    restore_fn: Callable[..., Any],
) -> dict[str, Any]:
    """Walk a nested canary if the clone file exists. Restore after. No Lean writes."""

    if not getattr(dest, "is_file", lambda: False)():
        return pack_fn({"analysis": analyze_fn(tactics)}, skipped="no_clone", name=name)
    max_steps, max_depth = budget_fn()
    walked = walk_fn(tactics, restore=restore, max_steps=max_steps, max_depth=max_depth)
    restore_fn(dest, restore)
    return pack_fn(walked, clone_exists=True)


def slim_canary(row: Mapping[str, Any]) -> dict[str, Any]:
    """Outer evidence row: no tactics / observations."""

    return {
        "analysis": row.get("analysis") or {},
        "n_drafts": row.get("n_drafts") or 0,
        "draft_kinds": list(row.get("draft_kinds") or []),
        "ranked": row.get("ranked") or {},
        "lake": list(row.get("lake") or []),
        "trace": list(row.get("trace") or []),
        "clone_exists": bool(row.get("clone_exists")),
        "n_steps": row.get("n_steps"),
    }


def run_sampled(
    records: Sequence[Mapping[str, Any]],
    *,
    memory: dict[str, Any],
    halt_fn: Any,
    run_fn: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run one nested canary per record; terminal skips never lake."""

    canaries: list[dict[str, Any]] = []
    lake_rows: list[dict[str, Any]] = []
    for record in records:
        try:
            halt = dict(halt_fn(memory) or {})
        except Exception:
            halt = {}
        name = record.get("name")
        if halt.get("budget_dead") or halt.get("halt"):
            reason = "nca_budget" if halt.get("budget_dead") else "nca_halt"
            skipped = pack_canary({}, skipped=reason, name=name)
            canaries.append(skipped)
            lake_rows.append({"name": name, "skipped": reason})
            continue
        nested = dict(run_fn(record) or {})
        lake = list(nested.get("lake") or [])
        lake_rows.extend(lake)
        packed = pack_canary(nested, clone_exists=bool(nested.get("clone_exists")))
        canaries.append(slim_canary(packed))
    return canaries, lake_rows


def intent_window(memory: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Compact tape/stack/board snapshot for a Jev intent state. No Lean."""

    from jevops.outer import head_seq

    mem = dict(memory or {})
    nca = mem.get("nca") or {}
    return {
        "tape_window": head_seq(mem.get("_tape_window"), 16),
        "stack_top": head_seq(mem.get("_stack_top"), 3),
        "board_window": head_seq(nca.get("board_window"), 8),
    }


def inner_loop(
    *,
    memory: dict[str, Any],
    tape: Any,
    stack: Any,
    record: Mapping[str, Any],
    body: str,
    depth: int,
    node: str,
    max_steps: int,
    max_depth: int,
    counter: list[int],
    analyze_fn: Any,
    research_fn: Any,
    remember_fn: Any,
    expand_fn: Any,
    draft_fn: Any,
    pick_fn: Any,
    lake_round: Any,
    compile_fn: Any,
    ledger: Any,
    args: Any,
    restore: bytes,
    spawn_fn: Any,
    nest_fn: Any,
    ptr_nest_fn: Any,
    theorem_fn: Any,
    subloops: Mapping[str, Any],
    extra_fn: Optional[Any] = None,
    router_fn: Optional[Any] = None,
    allow_families: Optional[set[str]] = None,
    allow_skills: Optional[set[str]] = None,
) -> dict[str, Any]:
    """Keep-looping inner walker. Drafts and lake are injected. No Lean in the kernel."""

    from jevops.nca import charge_budget

    lake: list[dict[str, Any]] = []
    ranked: dict[str, Any] = {}
    drafts: list[dict[str, Any]] = []
    analysis: dict[str, Any] = {}
    trace: list[dict[str, Any]] = []
    nxt = str(body or "").strip("\n")
    persist_view(memory, tape, stack)
    while counter[0] < max_steps:
        stepped = halt_step(memory, depth=depth, name=str(record.get("name") or ""), round_i=counter[0])
        if stepped.get("trace"):
            trace.append(stepped["trace"])
        if stepped.get("lake"):
            lake.append(stepped["lake"])
        if stepped.get("flow") == "break":
            break
        counter[0] += 1
        analysis = dict(analyze_fn(nxt) or {})
        intent = dict(
            research_fn(analysis, nxt)
            or {}
        )
        if remember_fn is not None:
            remember_fn(intent, nxt)
        if expand_fn is not None:
            expand_fn(nxt)
        if ledger is not None:
            charge_budget(memory, ledger=ledger, event="jev")
        compose = str(intent.get("compose") or "single")
        nest_child = str(intent.get("nest_child") or "")
        tool_name = str(intent.get("tool_name") or "")
        trace.append(
            {
                "depth": depth,
                "node": node,
                "step": counter[0] - 1,
                "compose": compose,
                "nest_child": nest_child,
                "tool_name": tool_name,
                "skill": intent.get("skill"),
                "intent": intent.get("intent"),
            }
        )
        problem = str(record.get("name") or "")
        extra = extra_fn(compose, nest_child, tool_name, nxt) if extra_fn is not None else {}
        ctrl = dispatch_control(
            compose=compose,
            memory=memory,
            tape=tape,
            stack=stack,
            body=nxt,
            problem=problem,
            node=node,
            n_steps=counter[0],
            tool_name=tool_name or nest_child or "decision_tree",
            extra=extra,
            ledger=ledger,
            compile_fn=compile_fn,
            record=record,
            args=args,
            restore=restore,
            lake_round=lake_round,
            round_i=counter[0] - 1,
            intent=intent,
            router_fn=router_fn,
            skip_lake=bool(intent.get("skip_lake")),
            name=record.get("name"),
            depth=depth,
        )
        if ctrl.get("trace"):
            trace.append({"depth": depth, **ctrl["trace"]})
        lake.extend(ctrl.get("lake") or [])
        if ctrl.get("body"):
            nxt = str(ctrl["body"])
        if ctrl.get("flow") == "break":
            break
        if ctrl.get("flow") == "continue":
            continue
        if compose == "call" or nest_child.startswith("ptr://"):
            called = handle_ptr_call(
                memory=memory,
                tape=tape,
                stack=stack,
                body=nxt,
                problem=problem,
                nest_child=nest_child or tool_name or node,
                record=record,
                node=node,
                theorem_fn=theorem_fn,
                nest_fn=ptr_nest_fn,
                depth=depth,
                max_depth=max_depth,
                round_i=counter[0] - 1,
            )
            if called.get("trace"):
                trace.append({"depth": depth, **called["trace"]})
            lake.extend(called.get("lake") or [])
            if called.get("body"):
                nxt = str(called["body"])
            continue
        tree = dict(intent.get("tree") or {})
        if compose in {"nest", "spawn"}:
            def _spawn_now(child: str) -> dict[str, Any]:
                return spawn_fn(child, nxt)

            def _nest_now(
                *,
                child: str,
                allow_families: Optional[set[str]] = None,
                allow_skills: Optional[set[str]] = None,
            ) -> dict[str, Any]:
                return nest_fn(
                    child=child,
                    allow_families=allow_families,
                    allow_skills=allow_skills,
                    tactics=nxt,
                )

            nest_out = do_nest_or_spawn(
                compose=compose,
                nest_child=nest_child,
                tree=tree,
                subloops=subloops,
                depth=depth,
                max_depth=max_depth,
                spawn_fn=_spawn_now,
                nest_fn=_nest_now,
                allow_families=allow_families,
            )
            if nest_out.get("flow") == "absorb" and nest_out.get("nested"):
                absorbed = absorb_nested(
                    memory,
                    nest_out["nested"],
                    compose=compose,
                    child=str(nest_out.get("child") or ""),
                    depth=depth,
                    body=nxt,
                    lake=lake,
                )
                nxt = str(absorbed.get("body") or nxt)
                trace.append(absorbed["trace"])
                continue
        drafts = list(
            draft_fn(nxt, analysis, intent)
            or []
        )
        drafts = restrict_drafts(
            drafts,
            skip_port=set(intent.get("skip_skills") or []),
            allow_skills=allow_skills,
        )
        if not drafts:
            empty = no_drafts_step(
                memory=memory,
                record=record,
                body=nxt,
                problem=problem,
                intent=intent,
                depth=depth,
                node=node,
                name=record.get("name"),
                round_i=counter[0] - 1,
                ledger=ledger,
                compile_fn=compile_fn,
                args=args,
                restore=restore,
            )
            if empty.get("trace"):
                trace.append(empty["trace"])
            lake.extend(empty.get("lake") or [])
            if empty.get("ranked"):
                ranked = dict(empty["ranked"])
            if empty.get("body"):
                nxt = str(empty["body"])
            if empty.get("flow") == "break":
                break
            continue
        admitted = admit_step(
            pick_fn=pick_fn,
            record=record,
            analysis=analysis,
            drafts=drafts,
            ledger=ledger,
            memory=memory,
            intent=intent,
            lake_round=lake_round,
            body=nxt,
            args=args,
            restore=restore,
            round_i=counter[0] - 1,
            compile_fn=compile_fn,
        )
        ranked = dict(admitted.get("ranked") or {})
        lake.extend(admitted.get("lake") or [])
        after_call(
            memory=memory,
            tape=tape,
            stack=stack,
            body=nxt,
            problem=problem,
            kind="lake",
            payload={"n": len(admitted.get("lake") or []), "ok": admitted.get("ok")},
            energy=0.7 if admitted.get("ok") else 0.3,
            theorem_ok=bool(admitted.get("ok")),
            tokens=int(admitted.get("tokens") or 0),
        )
        if admitted.get("body"):
            nxt = str(admitted["body"])
        if admitted.get("flow") == "break":
            break
        continue
    return walk_result(
        body=nxt,
        lake=lake,
        ranked=ranked,
        drafts=drafts,
        analysis=analysis,
        trace=trace,
        n_steps=counter[0],
        depth=depth,
        node=node,
        memory=memory,
        tape=tape,
        stack=stack,
    )


def child_base(
    *,
    args: Any,
    memory: Any,
    ledger: Any,
    rng: Any,
    model: Any,
    restore: Any,
    depth: int,
    steps: Any,
    max_steps: int,
    max_depth: int,
    compile_one: Any,
    research_fn: Any,
    pick_fn: Any,
    router_fn: Any,
) -> dict[str, Any]:
    """Shared kwargs for nest/spawn/ptr-nest. Closures stay in the consumer."""

    return {
        "args": args,
        "memory": memory,
        "ledger": ledger,
        "rng": rng,
        "model": model,
        "restore": restore,
        "depth": int(depth),
        "steps": steps,
        "max_steps": int(max_steps),
        "max_depth": int(max_depth),
        "compile_one": compile_one,
        "research_fn": research_fn,
        "pick_fn": pick_fn,
        "router_fn": router_fn,
    }
