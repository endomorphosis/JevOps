#!/usr/bin/env python3
"""Static-analysis and subloop tools TypeSafe can invoke without llm_router.

Closed catalog: knowledge graph, harness AST, package exports, local MCP-like
schemas, and closed-vocab text diffusion. Subloops are named callables that
return a payload to the parent walker. Jev does not write Lean. Never docker0.


TypeSafe/JevOps kernel primitive. Harness AST/exports/Lean diffuse live in the implementation."""
from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

def _harness_dir() -> Optional[Path]:
    from jevops import hooks

    raw = hooks.const("harness_dir")
    if raw:
        return Path(raw)
    return None

# Closed MCP++ tool names TypeSafe may CALL. Local catalog / describe only —
# no live P2P, no docker0, no docker-hub submit from the LRA harness.
MCPPLUSPLUS_TOOLS: dict[str, dict[str, str]] = {
    "catalog": {
        "what": "List MCP++ tools (CID-native catalog, no live P2P)",
        "not_for": "Opening a docker0 or libp2p session",
    },
    "describe": {
        "what": "Describe one MCP++ tool schema and receipt shape",
        "not_for": "Invoking the remote tool",
    },
    "p2p_taskqueue_status": {
        "what": "MCP++ TaskQueue status envelope (local describe; no live peers)",
        "not_for": "Submitting tasks or docker images",
    },
    "p2p_taskqueue_list_tasks": {
        "what": "MCP++ TaskQueue list envelope (local describe)",
        "not_for": "Claiming or completing remote tasks",
    },
    "p2p_taskqueue_get_task": {
        "what": "MCP++ get-task envelope (local describe)",
        "not_for": "Waiting on a remote worker",
    },
    "p2p_workflow_status": {
        "what": "MCP++ workflow status envelope (local describe)",
        "not_for": "Scheduling a live P2P workflow",
    },
}

TOOL_CRITERIA: dict[str, dict[str, str]] = {
    "kg_skills": {
        "what": "Knowledge graph of skills, problems, residuals, wins/fails from memory",
        "not_for": "Writing Lean or calling grok",
    },
    "ast_harness": {
        "what": "AST of harness skill modules (fold_*, PIPELINE, walkers)",
        "not_for": "Executing those functions as Lean edits",
    },
    "pkg_exports": {
        "what": "Public callables exported by harness packages (navigate, do not exec Lean)",
        "not_for": "Importing docker0 or generate_text",
    },
    "mcp_catalog": {
        "what": "Local MCP-like tool schemas TypeSafe can navigate (no live Grok MCP)",
        "not_for": "Calling 172.17.0.1 or a nested grok CLI",
    },
    "mcpplusplus": {
        "what": "CALL ptr://mcpplusplus/<tool> — MCP++ catalog/describe receipt on the neural tape",
        "not_for": "Live P2P, docker-hub submit, or docker0",
    },
    "stack_walk": {
        "what": "Walk the call-stack forest: parent then children, with bound child args",
        "not_for": "Mutating Lean",
    },
    "stack_parent": {
        "what": "Current frame's parent (ptr, locals, child_ids)",
        "not_for": "Jumping to an unknown frame",
    },
    "stack_children": {
        "what": "Current frame's children and the args they were called with",
        "not_for": "Spawning extra children",
    },
    "tape_populate": {
        "what": "Write current stack-frame args onto the neural tape",
        "not_for": "Writing outside the tape ring",
    },
    "symbol_search": {
        "what": "Rank symbols from DuckDB AST/vector index, knowledge graph, Python ast, ripgrep",
        "not_for": "Semantic authority or paths outside the harness",
    },
    "board_walk": {
        "what": "Load LRA goal/subgoal/task DAG and seed NCA cells (read-only, no campaign write)",
        "not_for": "compare_and_set or materialize on control.duckdb",
    },
    "codepath_slice": {
        "what": "Walk callers/callees of an allowlisted harness or ipfs_accelerate_py symbol (ids only)",
        "not_for": "Paths outside those roots or dumping source bodies",
    },
    "nca_program": {
        "what": "Compile NCA state to IR (datasets compiler/autoencoder if present) and emit work instructions; optional hosted Leanstral",
        "not_for": "docker0 Leanstral or Jev writing Lean",
    },
    "nca_heal": {
        "what": "Closed-vocab repair of corrupted NCA grid/tape/stack/program_state (TypeSafe ranks kernels)",
        "not_for": "Inventing new Python or Lean",
    },
    "diffuse": {
        "what": "Closed-vocab symbol-diffusion drafts (mask/fill Lean tokens, llm=off)",
        "not_for": "Hosted Leanstral fills unless compose is invoke_router",
    },
    "decision_tree": {
        "what": "Composable skill decision tree for this script (families, skills, tools, subloops)",
        "not_for": "A tree of Lean text",
    },
    "nca_tick": {
        "what": "Neural-CA tick: each skill/module cell feeds its last energy + neighbors + TypeSafe scores",
        "not_for": "Writing Lean",
    },
    "nca_walk": {
        "what": "Hook and evaluate every harness Python file (AST, import, tests)",
        "not_for": "Walking paths outside the paper harness",
    },
    "nca_hook": {
        "what": "Hook one harness file, walk its AST, evaluate importability",
        "not_for": "Arbitrary filesystem paths",
    },
    "nca_mutate": {
        "what": "Gated mutation: reorder pipeline by energy, skip dying stems, mint keep-structure folds",
        "not_for": "Rewriting files outside the harness skill memory",
    },
    "nca_fork": {
        "what": "Fork high-energy cells as returnable subloops (cap 4)",
        "not_for": "Unbounded nested grok CLIs",
    },
}

# Named callables the inner walker can spawn and join. Registered at runtime.
SUBLOOPS: dict[str, Callable[..., dict[str, Any]]] = {}


def register_subloop(name: str, fn: Callable[..., dict[str, Any]]) -> None:
    stem = str(name or "").strip()
    if stem:
        SUBLOOPS[stem] = fn


def spawn_subloop(name: str, **kwargs: Any) -> dict[str, Any]:
    """Call a registered subloop and return its payload to the parent."""

    fn = SUBLOOPS.get(str(name or "").strip())
    if fn is None:
        return {
            "ok": False,
            "returned": True,
            "reason": "unknown_subloop",
            "name": name,
            "available": sorted(SUBLOOPS),
        }
    payload = fn(**kwargs)
    if not isinstance(payload, dict):
        payload = {"value": payload}
    payload.setdefault("ok", True)
    payload["returned"] = True
    payload["subloop"] = str(name)
    return payload


def skill_knowledge_graph(memory: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Nodes = problems/skills/residuals; edges = success/fail/research/mint."""

    mem = dict(memory or {})
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def _node(nid: str, kind: str, **extra: Any) -> None:
        row = nodes.setdefault(nid, {"id": nid, "kind": kind})
        row.update({k: v for k, v in extra.items() if v is not None})

    for row in mem.get("successes") or []:
        problem = str(row.get("name") or "")
        skill = str(row.get("kind") or "")
        _node(problem, "problem")
        _node(skill, "skill")
        edges.append(
            {
                "src": problem,
                "dst": skill,
                "rel": "success",
                "from_tokens": row.get("from_tokens"),
                "to_tokens": row.get("to_tokens"),
            }
        )
    for row in mem.get("failures") or []:
        problem = str(row.get("name") or "")
        skill = str(row.get("kind") or "")
        _node(problem, "problem")
        _node(skill, "skill", error_class=row.get("error_class"))
        edges.append({"src": problem, "dst": skill, "rel": "fail", "error_class": row.get("error_class")})
    for row in mem.get("research") or []:
        problem = str(row.get("name") or "")
        _node(problem, "problem")
        for residual, help_score in (row.get("help") or {}).items():
            rid = f"residual:{residual}"
            _node(rid, "residual")
            edges.append(
                {
                    "src": problem,
                    "dst": rid,
                    "rel": "research",
                    "help": help_score,
                    "unsafe": (row.get("unsafe") or {}).get(residual),
                }
            )
    for spec in mem.get("skills") or []:
        stem = str(spec.get("stem") or "")
        _node(f"mem:{stem}", "memory_skill", keep=spec.get("keep"))
    for key in mem.get("blacklist") or []:
        _node(str(key), "ban")
    return {
        "n_nodes": len(nodes),
        "n_edges": len(edges),
        "nodes": list(nodes.values())[:80],
        "edges": edges[-80:],
        "called_docker0": False,
    }


def harness_ast(*, modules: Optional[list[str]] = None) -> dict[str, Any]:
    """Function/class names from harness skill modules (navigate, do not exec)."""

    from jevops import hooks

    extra = hooks.get("tool:ast_harness")
    if extra is not None:
        return extra(modules=modules)
    root = _harness_dir()
    if root is None:
        return {"files": [], "called_docker0": False, "reason": "no_harness_dir"}
    names = modules or [
        "portable_rewrites.py",
        "typesafe_inner.py",
        "symbol_diffuse.py",
        "binder_use.py",
        "typesafe_tools.py",
    ]
    files: list[dict[str, Any]] = []
    for name in names:
        path = root / name
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            files.append({"file": name, "error": str(exc)[:120]})
            continue
        functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
        assigns = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {"PIPELINE", "KEEP_STRUCTURE", "SKILL_CRITERIA", "TOOL_CRITERIA", "SUBLOOPS"}:
                        assigns.append(target.id)
        files.append(
            {
                "file": name,
                "functions": functions[:60],
                "classes": classes,
                "fold_fns": [fn for fn in functions if fn.startswith("fold_")],
                "assigns": assigns,
            }
        )
    return {"files": files, "called_docker0": False}


def harness_exports() -> dict[str, Any]:
    """Public callables on harness modules TypeSafe can navigate."""

    mods = (
        "portable_rewrites",
        "symbol_diffuse",
        "binder_use",
        "typesafe_inner",
        "typesafe_tools",
        "skill_improve_loop",
    )
    exported: dict[str, list[str]] = {}
    for mod_name in mods:
        try:
            module = importlib.import_module(mod_name)
        except Exception:
            continue
        names = [
            name
            for name in dir(module)
            if not name.startswith("_") and callable(getattr(module, name, None))
        ]
        exported[mod_name] = names[:80]
    return {"modules": exported, "called_docker0": False}


def mcp_catalog() -> dict[str, Any]:
    """Local MCP-like schemas. Does not call the Grok TUI MCP bus."""

    extra: list[dict[str, Any]] = []
    from jevops import hooks

    catalog_raw = hooks.const("mcp_catalog_path")
    catalog_path = Path(catalog_raw) if catalog_raw else Path()
    if catalog_raw and catalog_path.is_file():
        try:
            loaded = json.loads(catalog_path.read_text(encoding="utf-8"))
            extra = list(loaded.get("tools") or [])
        except json.JSONDecodeError:
            extra = []
    tools = [
        {
            "name": name,
            "description": spec["what"],
            "input_schema": {"type": "object", "properties": {"tactics": {"type": "string"}}},
        }
        for name, spec in TOOL_CRITERIA.items()
    ] + extra
    return {
        "server": "lra-typesafe-local",
        "n_tools": len(tools),
        "tools": tools[:40],
        "live_grok_mcp": False,
        "called_docker0": False,
    }


def mcpplusplus_call(name: str, *, problem: str = "", tactics: str = "") -> dict[str, Any]:
    """MCP++ CALL: local catalog/describe envelope. No live P2P, no docker0."""

    key = str(name or "catalog").strip()
    if key not in MCPPLUSPLUS_TOOLS:
        return {
            "ok": False,
            "protocol": "MCP++",
            "reason": "unknown_mcpplusplus_tool",
            "ptr": f"ptr://mcpplusplus/{key}",
            "available": sorted(MCPPLUSPLUS_TOOLS),
            "called_docker0": False,
            "live_p2p": False,
        }
    tools = [
        {
            "name": tool,
            "description": spec["what"],
            "not_for": spec["not_for"],
            "ptr": f"ptr://mcpplusplus/{tool}",
        }
        for tool, spec in MCPPLUSPLUS_TOOLS.items()
    ]
    schema = next(item for item in tools if item["name"] == key)
    envelope = {
        "protocol": "MCP++",
        "profile": "catalog",
        "tool": key,
        "problem": problem,
        "ptr": f"ptr://mcpplusplus/{key}",
        "receipt": {
            "kind": "describe" if key != "catalog" else "catalog",
            "ok": True,
            "p2p": False,
            "called_docker0": False,
            "tactics_tokens": len(tactics.split()) if tactics else 0,
        },
        "contract": {
            "cid_native": True,
            "live_p2p": False,
            "docker0": False,
        },
        "schema": schema,
        "catalog": tools if key == "catalog" else [schema],
    }
    return {
        "ok": True,
        "protocol": "MCP++",
        "ptr": f"ptr://mcpplusplus/{key}",
        "envelope": envelope,
        "called_docker0": False,
        "live_p2p": False,
    }


def diffuse_closed(tactics: str) -> dict[str, Any]:
    """Closed-vocab text-diffusion drafts (llm=off)."""

    from jevops import hooks

    token_count = hooks.resolve("token_count", "run_warmup", "token_count")
    lra_sym = hooks.try_import("symbol_diffuse")
    if lra_sym is None:
        return {"n_drafts": 0, "drafts": [], "llm": "off", "called_docker0": False, "reason": "no_diffuse"}

    body = str(tactics or "").strip("\n")
    rows = []
    for item in lra_sym.one_hole_closed_rows(body, max_pos=2)[:8]:
        nxt = str(item.get("tactics") or "")
        rows.append(
            {
                "kind": item.get("kind") or item.get("schedule_id") or "diffuse",
                "token_count": item.get("token_count") or (token_count(nxt) if token_count else len(nxt.split())),
                "n_masks": item.get("n_masks"),
                "span": item.get("span"),
            }
        )
    return {
        "n_drafts": len(rows),
        "drafts": rows,
        "llm": "off",
        "called_docker0": False,
    }


def compose_decision_tree(
    tactics: str,
    *,
    memory: Optional[Mapping[str, Any]] = None,
    name: str = "",
    observations: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Families → skills, plus tools and spawnable subloops."""

    from jevops import hooks

    tree_fn = hooks.resolve("decision_tree", "portable_rewrites", "decision_tree")
    tree = tree_fn(tactics, memory=dict(memory or {}), name=name) if tree_fn else {}
    port = hooks.try_import("portable_rewrites")
    return {
        "families": tree,
        "tools": sorted(TOOL_CRITERIA),
        "subloops": sorted(SUBLOOPS),
        "observed": sorted((observations or {}).keys()),
        "keep_structure": list(getattr(port, "KEEP_STRUCTURE", ()) or ()),
    }


def _stack_tape_tool(
    name: str,
    *,
    memory: dict[str, Any],
    tactics: str = "",
    problem: str = "",
) -> dict[str, Any]:
    from jevops import stack as lra_cs
    from jevops import tape as lra_tape

    stack = lra_cs.CallStack.from_dict(memory.get("_stack") or {})
    tape = lra_tape.Tape.from_memory(memory)
    if name == "stack_parent":
        parent = stack.parent()
        return {"ok": True, "parent": parent, "called_docker0": False}
    if name == "stack_children":
        kids = stack.children()
        return {
            "ok": True,
            "children": [
                {"frame_id": k.get("frame_id"), "ptr": k.get("ptr"), "args": k.get("locals")}
                for k in kids
            ],
            "called_docker0": False,
        }
    if name == "stack_walk":
        return {
            "ok": True,
            "walk": [
                {
                    "frame_id": f.get("frame_id"),
                    "parent_id": f.get("parent_id"),
                    "ptr": f.get("ptr"),
                    "child_ids": list(f.get("child_ids") or []),
                    "args": list((f.get("locals") or {}).keys()),
                }
                for f in stack.walk()
            ],
            "called_docker0": False,
        }
    cell = lra_tape.populate_tape(
        tape,
        stack,
        tactics=tactics,
        problem=problem,
        observations=memory.get("observations") or {},
        ptr=str((stack.top() or {}).get("ptr") or ""),
    )
    tape.persist(memory)
    return {"ok": True, "cell": cell, "called_docker0": False}


def run_tool(
    name: str,
    *,
    tactics: str = "",
    memory: Optional[Mapping[str, Any]] = None,
    problem: str = "",
    observations: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Dispatch a catalog tool. Never docker0. Never writes Lean via Jev."""

    key = str(name or "").strip()
    from jevops import hooks

    extra = hooks.get(f"tool:{key}")
    if extra is not None:
        payload = extra(tactics=tactics, memory=memory, problem=problem, observations=observations)
        payload = dict(payload or {})
        payload["ok"] = True
        payload["tool"] = key
        return payload
    if key == "kg_skills":
        payload = skill_knowledge_graph(memory)
    elif key == "ast_harness":
        payload = harness_ast()
    elif key == "pkg_exports":
        payload = harness_exports()
    elif key == "mcp_catalog":
        payload = mcp_catalog()
    elif key == "diffuse":
        payload = diffuse_closed(tactics)
    elif key == "decision_tree":
        payload = compose_decision_tree(
            tactics, memory=memory, name=problem, observations=observations
        )
    elif key in {"stack_walk", "stack_parent", "stack_children", "tape_populate"}:
        payload = _stack_tape_tool(key, memory=memory if isinstance(memory, dict) else dict(memory or {}), tactics=tactics, problem=problem)
    elif key == "nca_heal":
        from jevops import repair as lra_heal

        live = memory if isinstance(memory, dict) else dict(memory or {})
        payload = lra_heal.heal(live)
    elif key == "nca_program":
        from jevops import program as lra_prog

        live = memory if isinstance(memory, dict) else dict(memory or {})
        payload = lra_prog.program_nca(live, tactics=tactics, problem=problem, llm="off")
    elif key == "board_walk":
        seed_board = hooks.resolve("seed_board", "board_graph", "seed_nca_from_board")
        overlay_board = hooks.resolve("overlay_board", "board_graph", "overlay_live_board")
        load_board = hooks.resolve("load_board", "board_graph", "load_lra_board")
        window_fn = hooks.resolve("board_window", "board_graph", "board_window")
        live = memory if isinstance(memory, dict) else dict(memory or {})
        payload = seed_board(live) if seed_board else {"ok": False, "reason": "no_board"}
        overlay = overlay_board(live) if overlay_board else {}
        payload["board"] = load_board() if load_board else {}
        payload["window"] = window_fn(live) if window_fn else {}
        payload["overlay"] = overlay
    elif key == "codepath_slice":
        slice_cp = hooks.resolve("slice_codepath", "codepath_graph", "slice_cross_module")
        payload = (
            slice_cp(problem or "harness.portable_rewrites:fold_hoist_repeated_simp")
            if slice_cp
            else {"ok": False, "reason": "no_slice"}
        )
    elif key == "symbol_search":
        search = hooks.resolve("symbol_search", "symbol_search", "search_symbols")
        payload = (
            search(problem or tactics[:80], memory=memory, tactics=tactics)
            if search
            else {"ok": False, "reason": "no_search"}
        )
    elif key == "mcpplusplus":
        payload = mcpplusplus_call("catalog", problem=problem, tactics=tactics)
    elif key.startswith("nca_"):
        nca_tool = hooks.resolve("nca_tool", "typesafe_nca", "nca_tool")
        live = memory if isinstance(memory, dict) else dict(memory or {})
        payload = (
            nca_tool(key, tactics=tactics, memory=live, problem=problem)
            if nca_tool
            else {"ok": False, "reason": "no_nca_tool"}
        )
    else:
        return {"ok": False, "tool": key, "reason": "unknown_tool", "available": sorted(TOOL_CRITERIA)}
    payload["ok"] = True
    payload["tool"] = key
    return payload


def self_improve(memory: dict[str, Any], *, name: str, tactics: str = "") -> dict[str, Any]:
    """Mint/expand keep-structure skills from AutoResearch memory. No llm_router."""

    from jevops import hooks

    propose = hooks.resolve("propose_skill", "binder_use", "propose_skill_from_research")
    expand = hooks.resolve("expand_skills", "binder_use", "expand_skills_from_memory")
    prop = propose(memory, name) if propose else {}
    notes = expand(memory, name=name, tactics=tactics) if expand else []
    installed = None
    if prop.get("keep_structure") is False and prop.get("residual"):
        pass
    return {
        "ok": True,
        "proposed": prop,
        "expanded": notes,
        "installed": installed,
        "router": None,
        "called_docker0": False,
    }
