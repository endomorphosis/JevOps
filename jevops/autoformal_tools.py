"""Tools Leanstral may call while autoformalizing. Lake admits. No shell.

`lake_check` compiles one self-contained Lean file in a temporary package.
`extract_lean` drops a planning preamble. Neither writes the project tree,
and an `import` is refused before Lake runs so Mathlib is not fetched.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .leanstral_score import tautology_theorems
from .more_rankers import call_contrastive
from .nca import credit_skill
from .statement_lock import legal_documents, load_autoformal, lock_statement, pattern_from_rule, render_lean, statements
from .muse_lean import LEANSTRAL_AUTOFORMAL_MAX_TOKENS, extract_lean_file

MAX_SOURCE = 16_384
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lake_check",
            "description": "Compile one Lean 4 file with lake. Pass a JSON object {\"source\":\"<lean>\"}. The source must start with def. Returns lake_ok and compiler errors. Not an import or a file write.",
            "parameters": {
                "type": "object",
                "properties": {"source": {"type": "string", "description": "Complete Lean 4 source with no import."}},
                "required": ["source"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_lean",
            "description": "Drop a planning preamble and a later chat turn. Returns the Lean source. Does not compile it.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clause_get",
            "description": "Return one clause span. Not an admit.",
            "parameters": {
                "type": "object",
                "properties": {"document_id": {"type": "string"}, "clause_id": {"type": "string"}},
                "required": ["document_id", "clause_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compile_clause",
            "description": "Compile one clause to canonical rules. Abstain is a result, not an admit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "clause_id": {"type": "string"},
                    "frame_id": {"type": "string"},
                },
                "required": ["document_id", "clause_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decompile_rule",
            "description": "Return the decompiled text of rules already compiled for one clause.",
            "parameters": {
                "type": "object",
                "properties": {"document_id": {"type": "string"}, "clause_id": {"type": "string"}},
                "required": ["document_id", "clause_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rules_for_frame",
            "description": "Return rule rows stored under one ontology frame. Not an admit.",
            "parameters": {
                "type": "object",
                "properties": {"frame_id": {"type": "string"}},
                "required": ["frame_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "coverage",
            "description": "Count compiled, abstain, inactive, and failed rule rows for one document.",
            "parameters": {
                "type": "object",
                "properties": {"document_id": {"type": "string"}},
                "required": ["document_id"],
            },
        },
    },
]
_NAMES = frozenset(item["function"]["name"] for item in TOOLS)


def _store():
    return legal_documents().STORE


def lake_check(source: str) -> dict[str, Any]:
    """Compile `source` with `lake build Legal`. Imports are refused first."""

    raw = str(source or "")
    if "import " in raw or raw.lstrip().startswith("import"):
        return {"lake_ok": False, "error": "imports_refused"}
    body = extract_lean_file(raw) or raw.strip()
    if not body:
        return {"lake_ok": False, "error": "empty"}
    if len(body.encode()) > MAX_SOURCE:
        return {"lake_ok": False, "error": "source_too_large"}
    if any(word in body.split() for word in ("sorry", "admit", "axiom")):
        return {"lake_ok": False, "error": "sorry_or_axiom"}
    pkg = Path(tempfile.mkdtemp(prefix="autoformal-lake-"))
    (pkg / "lean-toolchain").write_text("leanprover/lean4:v4.26.0\n", encoding="utf-8")
    (pkg / "lakefile.lean").write_text(
        "import Lake\nopen Lake DSL\n\npackage «legal»\n\n@[default_target]\nlean_lib Legal\n",
        encoding="utf-8",
    )
    (pkg / "Legal.lean").write_text(body + "\n", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = str(Path.home() / ".elan" / "bin") + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        ["lake", "build", "Legal"], cwd=pkg, capture_output=True, text=True, timeout=180, env=env,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    errors = "\n".join(line for line in output.splitlines() if line.startswith("error:"))[:2000]
    ok = proc.returncode == 0 and "error:" not in output and "Built Legal" in output
    return {"lake_ok": ok, "error": "" if ok else errors or "build_failed"}


def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one allowlisted tool. An unknown name is an error payload, not a call."""

    if name not in _NAMES:
        return {"error": "unknown_tool", "name": name}
    if name == "extract_lean":
        text = arguments.get("text")
        if not isinstance(text, str):
            text = arguments.get("source")
        if not isinstance(text, str):
            return {"error": "text_required"}
        source = extract_lean_file(text)
        if not source:
            return {
                "source": "",
                "chars": 0,
                "error": 'no Lean definition in that text. Call lake_check with {"source":"<lean>"}. The source must start with def.',
            }
        return {"source": source[:MAX_SOURCE], "chars": len(source)}
    if name in {"clause_get", "compile_clause", "decompile_rule", "rules_for_frame", "coverage"}:
        return load_autoformal().dispatch(name, arguments)
    source = arguments.get("source")
    if not isinstance(source, str):
        return {"error": "source_required"}
    return lake_check(source)


def run_neighbor_objective(
    *,
    anchor_text: str,
    neighbor_text: str,
    triples: list[dict[str, str]],
    anchor_id: str,
    neighbor_id: str,
    scope: dict[str, Any] | None = None,
    memory: dict[str, Any] | None = None,
    usage: Any = None,
) -> dict[str, Any]:
    """One cited neighbor. An empty content id is not a proof."""

    workspace_root = Path(__file__).resolve().parents[2] / "external" / "ipfs_datasets"
    if workspace_root.is_dir() and str(workspace_root) not in sys.path:
        sys.path.insert(0, str(workspace_root))
    autoformal = load_autoformal()
    result = autoformal.SESSION.formalize_against(
        anchor_text,
        neighbor_text,
        triples=triples,
        anchor_id=anchor_id,
        neighbor_id=neighbor_id,
        scope=scope,
    )
    cell = memory if memory is not None else {}
    recorded = record_formalization(cell, result)
    receipt = {
        "work_id": f"neighbor:{neighbor_id}",
        "clause_id": recorded["clause_id"],
        "status": str((result.get("receipt") or {}).get("status") or "abstain"),
        "label": recorded["label"],
        "margin": recorded["margin"],
        "contrastive_m": recorded["contrastive_m"],
        "content_cid": recorded["content_cid"],
        "proved": bool(recorded["content_cid"]),
    }
    if usage is None:
        supervisor_root = Path(__file__).resolve().parents[2] / "hallucinate_app" / "ipfs_accelerate_py"
        if supervisor_root.is_dir() and str(supervisor_root) not in sys.path:
            sys.path.insert(0, str(supervisor_root))
        from ipfs_accelerate_py.agent_supervisor.control.control_plane import ProviderUsageControl

        usage = ProviderUsageControl()
    usage.record_receipt(receipt)
    stored = dict(usage._receipts[-1])
    return {
        "receipt": stored,
        "memory": cell,
        "admitted": False,
        "anchor_status": result.get("anchor_status"),
    }


def record_formalization(memory: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Copy a constraint label onto the NCA cell. Does not open a proof index."""

    receipt = result.get("receipt") if isinstance(result.get("receipt"), dict) else {}
    return record_pair_margin(
        memory,
        clause_id=str(receipt.get("clause_id") or ""),
        label=str(receipt.get("label") or "abstain"),
        margin=int(receipt.get("margin") or 0),
        positive=str(result.get("anchor_decompiled") or ""),
        negative=str(result.get("neighbor_decompiled") or ""),
        content_cid=str(receipt.get("content_cid") or ""),
    )


def record_pair_margin(
    memory: dict[str, Any],
    *,
    clause_id: str,
    label: str,
    margin: int,
    positive: str,
    negative: str,
    content_cid: str = "",
) -> dict[str, Any]:
    """Store the contrastive margin on the NCA cell. The rule text is not stored."""

    scored = call_contrastive(memory, tactics=negative, problem=positive)
    cell = memory.setdefault("nca", {}).setdefault("autoencoder", {})
    cell["contrastive_m"] = scored["loss_m"]
    cid = str(content_cid or "")
    return {
        "clause_id": clause_id,
        "label": label,
        "margin": int(margin),
        "contrastive_m": scored["loss_m"],
        "content_cid": cid,
        "proved": bool(cid),
        "completion_authoritative": False,
        "writes_lean": bool(scored.get("writes_lean")),
        "admitted": False,
    }


def admit_roundtrip_rule(
    row: dict[str, Any],
    reply: str,
    *,
    memory: dict[str, Any] | None = None,
    repository: Any = None,
) -> dict[str, Any]:
    """Lake-check one round-trip rule. A changed statement is not stored."""

    if row.get("status") != "roundtrip_ok":
        return {"lake_ok": False, "error": "not_roundtrip", "stored": False}
    pattern = pattern_from_rule(row.get("rule") if isinstance(row.get("rule"), dict) else None)
    if pattern is None:
        return {"lake_ok": False, "error": "not_renderable", "stored": False}
    source = render_lean(pattern)
    locked = lock_statement(source, reply)
    if not locked["ok"]:
        if memory is not None:
            credit_skill(memory, str(row.get("clause_id") or ""), ok=False)
        return {"lake_ok": False, "error": locked["error"], "stored": False}
    checked = lake_check(str(locked["source"]))
    lake_ok = bool(checked.get("lake_ok"))
    if memory is not None:
        credit_skill(memory, str(row.get("clause_id") or ""), ok=lake_ok)
    if not lake_ok:
        return {"lake_ok": False, "error": checked.get("error") or "", "stored": False}
    stored = load_autoformal().store_lake_attestation(
        clause_id=str(row.get("clause_id") or ""),
        rule_cid=str((row.get("rule") or {}).get("rule_cid") or row.get("clause_id") or ""),
        lean=str(locked["source"]),
        lake_log=str(checked.get("error") or "lake_ok"),
        repository=repository,
    )
    return {
        "lake_ok": True,
        "error": "",
        "stored": bool(stored.get("indexed")),
        "content_cid": stored.get("content_cid"),
        "repository": stored.get("repository"),
    }


def admit_locked(document_id: str, clause_id: str, reply: str) -> dict[str, Any]:
    """Lake-check a reply only after its statements match the harness."""

    expected = _store().obligations(document_id, clause_id)
    source = render_lean(expected.get("pattern"))
    if expected.get("error") or expected.get("disposition") != "pending" or not source:
        return {"ok": False, "error": expected.get("error") or expected.get("disposition") or "not_pending", "lake_ok": False}
    locked = lock_statement(source, reply)
    if not locked["ok"]:
        _store().mark(document_id, clause_id, "failed", str(locked["error"]))
        return {"ok": False, "error": locked["error"], "lake_ok": False}
    checked = lake_check(str(locked["source"]))
    _store().mark(
        document_id,
        clause_id,
        "admitted" if checked.get("lake_ok") else "failed",
        str(checked.get("error") or ""),
    )
    return {"ok": bool(checked.get("lake_ok")), "error": checked.get("error") or "", "lake_ok": bool(checked.get("lake_ok"))}


def run_leanstral(legal_text: str, *, rounds: int = 3) -> dict[str, Any]:
    """Give Leanstral lake_check and extract_lean, then keep the last Lean file.

    At most `rounds` model calls. A tool result is not an admit; the last
    source is compiled again and that result is `lake_ok`.
    """

    from .leanstral import chat_completion

    if not 1 <= rounds <= 4:
        raise ValueError("rounds must be 1..4")
    messages = [
        {"role": "system" if item["role"] == "developer" else item["role"], "content": item["content"]}
        for item in load_autoformal().messages(legal_text)
    ]
    trace: list[dict[str, Any]] = []
    final = ""
    for _ in range(rounds):
        reply = chat_completion(
            None,
            messages=messages,
            model="leanstral_local",
            max_new_tokens=LEANSTRAL_AUTOFORMAL_MAX_TOKENS,
            timeout=300,
            temperature=0,
            stop=["<|im_end|>", "</s>"],
            tools=TOOLS,
        )
        calls = list(reply.get("tool_calls") or [])
        text = str(reply.get("text") or "")
        trace.append({"finish": reply.get("finish_reason"), "tools": [call["name"] for call in calls], "chars": len(text)})
        assistant: dict[str, Any] = {"role": "assistant", "content": text or " "}
        if calls:
            assistant["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call["arguments"])},
                }
                for call in calls
            ]
        messages.append(assistant)
        if calls:
            for call in calls:
                result = dispatch(str(call.get("name") or ""), dict(call.get("arguments") or {}))
                messages.append({
                    "role": "tool",
                    "tool_call_id": str(call.get("id") or "call"),
                    "content": json.dumps(result)[:4000],
                })
            continue
        extracted = extract_lean_file(text)
        if extracted.startswith(("def ", "theorem ", "inductive ")):
            final = extracted
            checked_now = lake_check(extracted)
            example_only = "a = a" in extracted and "def " not in extracted
            repeated = tautology_theorems(extracted)
            trace[-1]["lake_ok"] = bool(checked_now.get("lake_ok")) and not example_only and not repeated
            if checked_now.get("lake_ok") and not example_only and not repeated:
                break
            if example_only:
                note = "The file is the unrelated example. Formalize the legal text."
            elif repeated:
                note = (
                    "These theorems only restate a definition: "
                    + ", ".join(repeated)
                    + ". Replace each with a boundary theorem that contains both numerals, "
                    "the integer that fails and the integer that meets."
                )
            else:
                note = "lake_check returned " + json.dumps(checked_now)[:2000]
            messages.append({
                "role": "user",
                "content": note + " Repair the file. Do not copy a solution.",
            })
            continue
        messages.append({
            "role": "user",
            "content": "tool_calls was empty or the reply was not Lean. Call lake_check with the Lean source.",
        })
    checked = lake_check(final) if final else {"lake_ok": False, "error": "no_lean_file"}
    return {"lake_ok": bool(checked.get("lake_ok")), "source": final, "error": checked.get("error"), "trace": trace}
