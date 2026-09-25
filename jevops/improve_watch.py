#!/usr/bin/env python3
"""Watcher for the JevOps outer loop.

Collect lake evals, including the proof text that was evaluated, and ask
``llm_router`` for one closed harness action. When that call returns ``run``
and a recorded lake-ok proof is strictly shorter than the proof text stored
in one ``.py`` harness file, the watcher proposes that replacement. A change
is kept only when a re-eval is still lake-ok and strictly shorter than the
harness emission, and the other metric does not get worse. A logged candidate
is not the baseline. The watcher never writes a Lean file and never treats a
router proposal as an admit. Lake stays the oracle.
"""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

_PROOF_KEYS = ("tactics", "proof", "body", "src", "candidate")
_PROOF_CAP = 8192
_PROMPT_PROOF = 1200
_CLOSED_ACTIONS = (
    "run",
    "nest_inner",
    "mint",
    "mint_tactic",
    "repair_tactic",
    "hypothesis_refactor",
    "skip_stem",
    "stop",
)
_MEMORY_KEYS = ("blacklist", "expanded", "nca", "skills")


def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return None


def _proof_text(row: Mapping[str, Any]) -> str:
    """Tactic block or proof body from an eval. Truncated, not rewritten."""

    for key in _PROOF_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:_PROOF_CAP]
    return ""


def _strip_bulky(row: Mapping[str, Any]) -> dict[str, Any]:
    """Keep short metadata. The proof is stored separately, not dropped."""

    out: dict[str, Any] = {}
    for key, value in dict(row).items():
        if key in _PROOF_KEYS or key in {"header", "statement"}:
            continue
        if isinstance(value, str) and len(value) > 240:
            continue
        out[str(key)] = value
    return out


def eval_record(row: Mapping[str, Any], *, step: int = 0, source: str = "lake") -> dict[str, Any]:
    """One eval. ``lake_ok`` is the consumer's lake flag, not an admit by this module."""

    clean = _strip_bulky(row)
    sorry = bool(clean.get("sorry") or clean.get("sorryAx"))
    ok = bool(clean.get("lake_ok") if "lake_ok" in clean else clean.get("ok")) and not sorry
    tokens = _int_or_none(clean.get("tokens", clean.get("token_count")))
    heartbeats = _int_or_none(
        clean.get("heartbeats", clean.get("maxHeartbeats", clean.get("max_heartbeats")))
    )
    role = str(clean.get("role") or "")
    if role not in {"incumbent", "candidate"}:
        role = ""
    return {
        "name": str(clean.get("name") or ""),
        "tokens": tokens,
        "heartbeats": heartbeats,
        "lake_ok": ok,
        "sorry": sorry,
        "stem": str(clean.get("stem") or clean.get("kind") or ""),
        "role": role,
        "step": int(step),
        "source": source,
        "proof": _proof_text(row),
    }


def shorter(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    """True when after is lake-ok and strictly shorter, with no metric regression."""

    if not after.get("lake_ok") or after.get("sorry"):
        return False
    token_better = False
    hb_better = False
    before_tokens = _int_or_none(before.get("tokens"))
    after_tokens = _int_or_none(after.get("tokens"))
    before_hb = _int_or_none(before.get("heartbeats"))
    after_hb = _int_or_none(after.get("heartbeats"))
    if before_tokens is not None and after_tokens is not None:
        if after_tokens > before_tokens:
            return False
        token_better = after_tokens < before_tokens
    if before_hb is not None and after_hb is not None:
        if after_hb > before_hb:
            return False
        hb_better = after_hb < before_hb
    return token_better or hb_better


def _baseline_for(
    rows: Sequence[Mapping[str, Any]],
    name: str,
    *,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Metrics of the harness emission for one problem.

    The emission is the longest lake-ok proof text that occurs once in one
    ``.py`` file. A shorter logged candidate does not lower that baseline.
    With no file match, candidates are ignored and the best remaining lake-ok
    row is the baseline.
    """

    named = [
        row
        for row in rows
        if str(row.get("name") or "") == name and row.get("lake_ok") and not row.get("sorry")
    ]
    if root is not None:
        bodies = _py_bodies(Path(root))
        matched: list[tuple[int, Mapping[str, Any], str]] = []
        for row in named:
            proof = str(row.get("proof") or "")
            site = _unique_proof_site(bodies, proof)
            if site:
                matched.append((len(proof.strip()), row, site))
        if matched:
            matched.sort(key=lambda item: item[0])
            _length, row, site = matched[-1]
            return {
                "name": name,
                "tokens": _int_or_none(row.get("tokens")),
                "heartbeats": _int_or_none(row.get("heartbeats")),
                "lake_ok": True,
                "sorry": False,
                "proof": str(row.get("proof") or ""),
                "path": site,
            }
    best_tokens: Optional[int] = None
    best_hb: Optional[int] = None
    for row in named:
        if str(row.get("role") or "") == "candidate":
            continue
        tokens = _int_or_none(row.get("tokens"))
        heartbeats = _int_or_none(row.get("heartbeats"))
        if tokens is not None and (best_tokens is None or tokens < best_tokens):
            best_tokens = tokens
        if heartbeats is not None and (best_hb is None or heartbeats < best_hb):
            best_hb = heartbeats
    return {"name": name, "tokens": best_tokens, "heartbeats": best_hb, "lake_ok": True, "sorry": False}


def _py_bodies(root: Path) -> list[tuple[str, str]]:
    """Relative ``.py`` sources under the harness root. Capped so a miss stays closed."""

    bodies: list[tuple[str, str]] = []
    if not root.is_dir():
        return bodies
    for path in root.rglob("*.py"):
        if len(bodies) >= 200:
            break
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        try:
            if path.stat().st_size > 262_144:
                continue
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        bodies.append((relative.as_posix(), text))
    return bodies


def _unique_proof_site(bodies: Sequence[tuple[str, str]], proof: str) -> str:
    """One relative path where ``proof`` occurs once, else empty."""

    text = proof.strip()
    if len(text) < 4 or (" " not in text and "\n" not in text):
        return ""
    found = ""
    for rel, body in bodies:
        count = body.count(text)
        if count > 1:
            return ""
        if count == 1:
            if found:
                return ""
            found = rel
    return found


def _replacement_parses(bodies: Sequence[tuple[str, str]], rel: str, old: str, new: str) -> bool:
    body = next((text for path, text in bodies if path == rel), None)
    if body is None or not old or body.count(old) != 1:
        return False
    updated = body.replace(old, new, 1)
    try:
        ast.parse(updated)
    except SyntaxError:
        return False
    return True


class EvalWatch:
    """Append-only eval log and one recursive improvement step.

    ``on_step`` is the outer-loop hook (``run_steps(..., on_step=watch.on_step)``).
    ``improve`` asks the router for a closed action and accepts it only after
    ``reeval_fn`` reports a shorter lake-ok eval.
    """

    def __init__(
        self,
        path: Optional[Any] = None,
        *,
        memory: Optional[dict[str, Any]] = None,
        root: Optional[Any] = None,
        allow_paths: Optional[Sequence[str]] = None,
    ) -> None:
        self.path = Path(path) if path else None
        self.root = Path(root).resolve() if root else None
        self.allow_paths = tuple(Path(str(item)).as_posix() for item in (allow_paths or ()))
        self.rows: list[dict[str, Any]] = []
        self.memory: dict[str, Any] = memory if memory is not None else {}
        self.proposals: list[dict[str, Any]] = []
        if self.path is not None and self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    loaded = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(loaded, dict):
                    self.rows.append(eval_record(loaded, step=int(loaded.get("step") or 0), source=str(loaded.get("source") or "lake")))

    def observe(self, row: Mapping[str, Any], *, step: int = 0, source: str = "lake") -> dict[str, Any]:
        record = eval_record(row, step=step, source=source)
        if not record["name"] and record["tokens"] is None and record["heartbeats"] is None:
            return record
        self.rows.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def on_step(self, row: Mapping[str, Any]) -> None:
        """Outer-loop hook. Records lake rows and does not admit them."""

        step = int(row.get("step") or 0)
        payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
        lake = row.get("last_lake")
        if not lake:
            lake = payload.get("lake") or []
        for item in lake:
            if isinstance(item, Mapping):
                self.observe(item, step=step, source="lake")

    def summary(self) -> dict[str, Any]:
        """Per-problem best lake-ok cut, plus stem wins and losses. No proof text."""

        by_name: dict[str, dict[str, Any]] = {}
        stems: dict[str, dict[str, int]] = {}
        for row in self.rows:
            if row.get("source") != "lake":
                continue
            name = str(row.get("name") or "")
            stem = str(row.get("stem") or "")
            if name:
                slot = by_name.setdefault(
                    name,
                    {"name": name, "best_tokens": None, "best_heartbeats": None, "wins": 0, "losses": 0},
                )
                if row.get("lake_ok"):
                    slot["wins"] += 1
                    tokens = _int_or_none(row.get("tokens"))
                    heartbeats = _int_or_none(row.get("heartbeats"))
                    if tokens is not None and (slot["best_tokens"] is None or tokens < slot["best_tokens"]):
                        slot["best_tokens"] = tokens
                    if heartbeats is not None and (
                        slot["best_heartbeats"] is None or heartbeats < slot["best_heartbeats"]
                    ):
                        slot["best_heartbeats"] = heartbeats
                else:
                    slot["losses"] += 1
            if stem:
                stem_slot = stems.setdefault(stem, {"wins": 0, "losses": 0})
                stem_slot["wins" if row.get("lake_ok") else "losses"] += 1
        return {
            "n_evals": len(self.rows),
            "problems": list(by_name.values()),
            "stems": stems,
            "jev_writes_lean": False,
            "lake_oracle": True,
        }

    def _prompt_proofs(self) -> list[dict[str, Any]]:
        """Recent proofs the router may read. Not a file write."""

        proofs: list[dict[str, Any]] = []
        for row in self.rows[-8:]:
            if row.get("source") not in {"lake", "reeval"}:
                continue
            text = str(row.get("proof") or "")
            proofs.append(
                {
                    "name": row.get("name") or "",
                    "stem": row.get("stem") or "",
                    "role": row.get("role") or "",
                    "lake_ok": bool(row.get("lake_ok")),
                    "tokens": row.get("tokens"),
                    "heartbeats": row.get("heartbeats"),
                    "proof": text[:_PROMPT_PROOF],
                }
            )
        return proofs

    def _prompt(self) -> str:
        report = self.summary()
        return (
            "You are the JevOps outer-loop watcher. "
            "Return one JSON object and nothing else. "
            "action must be one of: skip_stem, mint, mint_tactic, repair_tactic, "
            "hypothesis_refactor, nest_inner, run, stop. "
            "The proofs below are eval evidence. Do not reply with a .lean path. "
            "Lake is the only admit. Use the proofs, token counts, and heartbeats. "
            "You may return update_code for one .py harness file with path, old, and new. "
            "That edit is kept only if a later lake eval is shorter. "
            "A stem with only losses should be skip_stem. "
            f"evals={json.dumps(report, sort_keys=True)}\n"
            f"proofs={json.dumps(self._prompt_proofs(), sort_keys=True)}\n"
            f"{self._harness_excerpt()}"
        )

    def _harness_excerpt(self) -> str:
        """Source the router may edit. Empty unless this watch listed paths."""

        if self.root is None or not self.allow_paths:
            return ""
        parts: list[str] = []
        for rel in self.allow_paths:
            path = self.root / rel
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            marker = 'if strategy == "local_alias_reduce":'
            if marker not in text:
                marker = "local_alias_reduce"
            if marker in text and len(text) > 5000:
                start = max(0, text.find(marker) - 200)
                text = text[start : start + 4500]
            elif len(text) > 5000:
                text = text[:5000]
            parts.append(f"harness_file {rel} follows. old and new must be exact substrings.\n{text}")
        if not parts:
            return ""
        return (
            "If a candidate proof is lake-ok and strictly shorter than the incumbent, "
            "return update_code for one harness file below. "
            "old and new are exact Python source substrings, not a tactic body. "
            "Do not return mint.\n"
            "Edit only these harness files.\n" + "\n".join(parts) + "\n"
        )

    def propose(
        self,
        *,
        generate_fn: Optional[Callable[[str], str]] = None,
        llm: bool = True,
    ) -> dict[str, Any]:
        """One closed action from llm_router. A proposal is not an admit."""

        from jevops.outer import make_llm_router_generate, parse_action, route_next

        generate = generate_fn
        if generate is None and llm:
            generate = make_llm_router_generate(provider="deterministic")
        action = route_next(
            gaps=[],
            last_lake=self._router_lake(),
            stalled=False,
            llm=bool(llm and generate is not None),
            memory=self.memory,
            generate_fn=generate,
            prompt=self._prompt(),
        )
        parsed = parse_action(json.dumps(action))
        parsed["router"] = str(action.get("router") or parsed.get("router") or "")
        routed = str(parsed.get("action") or "")
        if routed in {"update_code", "patch"}:
            edit, edit_reason = _py_edit(parsed)
            if not edit_reason and edit is not None and not _path_allowed(edit["path"], self.allow_paths):
                edit_reason = "path_not_allowed"
            refusal = edit_reason
        else:
            refusal = _refuse_lean(parsed) or _refuse_text(str(action.get("raw_head") or ""))
        if refusal:
            parsed = {"action": "run", "reason": refusal, "router": parsed.get("router") or "watcher"}
        elif routed not in _CLOSED_ACTIONS and routed not in {"update_code", "patch"}:
            parsed = {"action": "run", "reason": "action_not_closed", "router": "watcher"}
        elif routed == "run":
            cut = self._data_cut()
            if cut:
                cut["router"] = str(parsed.get("router") or "llm_router")
                cut["router_head"] = str(action.get("raw_head") or "")[:240]
                cut["source_action"] = "run"
                parsed = cut
            elif self.allow_paths:
                parsed = self._ask_harness_edit(generate, source_action="run") or parsed
        elif self.allow_paths and routed not in {"stop", "skip_stem"}:
            parsed = self._ask_harness_edit(generate, source_action=routed) or parsed
        self.proposals.append(dict(parsed))
        return parsed

    def _ask_harness_edit(
        self,
        generate: Optional[Callable[[str], str]],
        *,
        source_action: str,
    ) -> Optional[dict[str, Any]]:
        """One more router call when the first action did not edit an allowed file."""

        if generate is None or not self._shorter_candidate_exists():
            return None
        from jevops.outer import parse_action

        prompt = (
            "Return one JSON object and nothing else. "
            "action must be update_code. "
            f"path must be one of {json.dumps(list(self.allow_paths))}. "
            "old and new must be exact substrings of that Python file. "
            "The edit is kept only if the harness then emits a shorter lake-ok proof. "
            "Do not return mint, run, or a .lean path.\n"
            + self._prompt()
        )
        try:
            text = generate(prompt)
        except Exception:
            return None
        parsed = parse_action(str(text))
        if str(parsed.get("action") or "") not in {"update_code", "patch"}:
            return None
        edit, reason = _py_edit(parsed)
        if reason or edit is None or not _path_allowed(edit["path"], self.allow_paths):
            return None
        parsed["router"] = "llm_router"
        parsed["router_head"] = str(text)[:240]
        parsed["source_action"] = source_action
        return parsed

    def _shorter_candidate_exists(self) -> bool:
        names = {str(row.get("name") or "") for row in self.rows if row.get("name")}
        for name in names:
            before = _baseline_for(self.rows, name, root=self.root)
            for row in self.rows:
                if str(row.get("name") or "") == name and shorter(before, row):
                    return True
        return False

    def _data_cut(self) -> Optional[dict[str, Any]]:
        """Replace the harness proof with a shorter lake-ok proof from the log.

        Used only after ``llm_router`` returns ``run``. The replacement is a
        proposal. ``improve_round`` still rolls it back unless the re-eval is
        shorter than the text the file held before the edit.
        """

        if self.root is None:
            return None
        bodies = _py_bodies(self.root)
        best: Optional[dict[str, Any]] = None
        best_key: Optional[tuple[int, int, int]] = None
        seen: set[str] = set()
        for row in self.rows:
            name = str(row.get("name") or "")
            if not name or name in seen:
                continue
            seen.add(name)
            before = _baseline_for(self.rows, name, root=self.root)
            old = str(before.get("proof") or "")
            rel = str(before.get("path") or "")
            if not old or not rel or not _path_allowed(rel, self.allow_paths):
                continue
            for candidate in self.rows:
                if str(candidate.get("name") or "") != name or not candidate.get("lake_ok"):
                    continue
                new = str(candidate.get("proof") or "")
                if not new or new == old or not shorter(before, candidate):
                    continue
                if not _replacement_parses(bodies, rel, old, new):
                    continue
                tokens = _int_or_none(candidate.get("tokens"))
                heartbeats = _int_or_none(candidate.get("heartbeats"))
                key = (
                    tokens if tokens is not None else 10**12,
                    heartbeats if heartbeats is not None else 10**12,
                    len(new),
                )
                if best_key is not None and key >= best_key:
                    continue
                best_key = key
                best = {
                    "action": "update_code",
                    "path": rel,
                    "old": old,
                    "new": new,
                    "name": name,
                    "reason": "recorded_lake_ok_proof_is_shorter",
                }
        return best

    def _router_lake(self) -> list[dict[str, Any]]:
        """Recent evals in the shape ``route_next`` already understands.

        A lake loss is marked ``port_<stem>`` so the router can quarantine it.
        Proof text is not included.
        """

        rows: list[dict[str, Any]] = []
        for row in self.rows:
            if row.get("source") not in {"lake", "reeval"}:
                continue
            stem = str(row.get("stem") or "")
            kind = stem
            if stem and not row.get("lake_ok") and not stem.startswith("port_"):
                kind = f"port_{stem}"
            rows.append(
                {
                    "name": row.get("name") or "",
                    "ok": bool(row.get("lake_ok")),
                    "tokens": row.get("tokens"),
                    "heartbeats": row.get("heartbeats"),
                    "kind": kind,
                }
            )
        return rows[-12:]

    def run_outer(
        self,
        *,
        n: int,
        inner_fn: Callable[[int], Mapping[str, Any]],
        board_fn: Callable[[], Any],
        reeval_fn: Callable[[Mapping[str, Any], dict[str, Any]], Mapping[str, Any]],
        rounds: int = 1,
        llm: bool = True,
        generate_fn: Optional[Callable[[str], str]] = None,
        gaps_fn: Optional[Callable[[], Any]] = None,
        route_fn: Optional[Callable[..., Any]] = None,
        apply_fn: Optional[Callable[..., Any]] = None,
    ) -> dict[str, Any]:
        """Run the outer loop, then recursively improve from the evals it just collected.

        ``inner_fn`` is the lake-backed inner step. ``reeval_fn`` is the same
        kind of lake check for one proposed harness action. Neither is an admit
        by this watcher.
        """

        from jevops.outer import apply_action, run_steps

        stepped = run_steps(
            n=n,
            memory=self.memory,
            llm=False,
            gaps_fn=gaps_fn or (lambda: []),
            route_fn=route_fn or (lambda **_k: {"action": "nest_inner"}),
            apply_fn=apply_fn or (lambda memory, action: apply_action(memory, action)),
            inner_fn=inner_fn,
            board_fn=board_fn,
            on_step=self.on_step,
        )
        improved = self.improve(
            reeval_fn,
            rounds=rounds,
            generate_fn=generate_fn,
            llm=llm,
            apply_fn=apply_fn,
        )
        return {
            "ok": bool(stepped.get("ok", True)) or bool(improved.get("ok")),
            "outer": {
                "stop_reason": stepped.get("stop_reason"),
                "best_total": stepped.get("best_total"),
                "history": stepped.get("history"),
            },
            "improve": improved,
            "jev_writes_lean": False,
            "lake_oracle": True,
            "arena_score": None,
        }

    def improve_round(
        self,
        reeval_fn: Callable[[Mapping[str, Any], dict[str, Any]], Mapping[str, Any]],
        *,
        generate_fn: Optional[Callable[[str], str]] = None,
        llm: bool = True,
        apply_fn: Optional[Callable[..., Any]] = None,
    ) -> dict[str, Any]:
        """Propose, apply in memory, re-eval, and roll back unless the cut is real."""

        from jevops.outer import apply_action

        action = self.propose(generate_fn=generate_fn, llm=llm)
        kind = str(action.get("action") or "run")
        if kind in {"run", "stop"}:
            return {
                "ok": True,
                "accepted": False,
                "action": action,
                "reason": "no_harness_change",
                "jev_writes_lean": False,
            }
        name = str(action.get("name") or "")
        before = _baseline_for(self.rows, name, root=self.root)
        snapshot = copy.deepcopy({key: self.memory.get(key) for key in _MEMORY_KEYS})
        file_undo: Optional[Callable[[], None]] = None
        if str(action.get("action") or "") in {"update_code", "patch"}:
            applied, file_undo = self._apply_harness_edit(action)
        else:
            apply = apply_fn or apply_action
            applied = dict(apply(self.memory, action) or {})
        if not applied.get("ok", True):
            _restore(self.memory, snapshot)
            if file_undo is not None:
                file_undo()
            return {
                "ok": False,
                "accepted": False,
                "action": action,
                "applied": applied,
                "reason": str(applied.get("reason") or "apply_failed"),
                "jev_writes_lean": False,
            }
        try:
            after_raw = reeval_fn(action, self.memory)
        except Exception as exc:
            _restore(self.memory, snapshot)
            if file_undo is not None:
                file_undo()
            return {
                "ok": False,
                "accepted": False,
                "action": action,
                "reason": f"reeval_error:{type(exc).__name__}",
                "jev_writes_lean": False,
            }
        after = eval_record(after_raw if isinstance(after_raw, Mapping) else {}, source="reeval")
        self.observe(after, step=len(self.rows), source="reeval")
        if not name:
            name = after["name"]
            before = _baseline_for(self.rows[:-1], name, root=None)
        accepted = shorter(before, after)
        if not accepted:
            _restore(self.memory, snapshot)
            if file_undo is not None:
                file_undo()
        return {
            "ok": True,
            "accepted": accepted,
            "action": action,
            "applied": applied,
            "before": before,
            "after": after,
            "reason": "shorter_lake_ok" if accepted else "not_shorter",
            "jev_writes_lean": False,
            "lake_oracle": True,
        }

    def _apply_harness_edit(self, action: Mapping[str, Any]) -> tuple[dict[str, Any], Optional[Callable[[], None]]]:
        """Write one .py edit under the harness root. Caller rolls it back."""

        edit, reason = _py_edit(action)
        if not reason and edit is not None and not _path_allowed(edit["path"], self.allow_paths):
            reason = "path_not_allowed"
        if reason or edit is None:
            return {"ok": False, "reason": reason or "not_a_py_edit"}, None
        if self.root is None:
            return {"ok": False, "reason": "no_harness_root"}, None
        ok, why, undo = _write_py(self.root, edit)
        if not ok or undo is None:
            return {"ok": False, "reason": why, "applied": "update_code_rejected"}, None
        return {"ok": True, "applied": "update_code", "path": edit["path"], "reason": why}, undo

    def improve(
        self,
        reeval_fn: Callable[[Mapping[str, Any], dict[str, Any]], Mapping[str, Any]],
        *,
        rounds: int = 3,
        generate_fn: Optional[Callable[[str], str]] = None,
        llm: bool = True,
        apply_fn: Optional[Callable[..., Any]] = None,
    ) -> dict[str, Any]:
        """Repeat propose/reeval until a cut stalls. Does not run forever."""

        history: list[dict[str, Any]] = []
        stalled = 0
        for _ in range(max(0, int(rounds))):
            result = self.improve_round(
                reeval_fn,
                generate_fn=generate_fn,
                llm=llm,
                apply_fn=apply_fn,
            )
            history.append(result)
            if result.get("accepted"):
                stalled = 0
            else:
                stalled += 1
            if str(result.get("action", {}).get("action") or "") == "stop":
                break
            if stalled >= 2:
                break
        return {
            "ok": any(bool(item.get("accepted")) for item in history),
            "accepted": sum(1 for item in history if item.get("accepted")),
            "rounds": len(history),
            "history": history,
            "summary": self.summary(),
            "jev_writes_lean": False,
            "lake_oracle": True,
            "arena_score": None,
        }


def _path_allowed(rel: str, allow: Sequence[str]) -> bool:
    """True when no allow-list is set, or ``rel`` is one listed harness file."""

    if not allow:
        return True
    return Path(rel).as_posix() in {Path(item).as_posix() for item in allow}


def _py_edit(action: Mapping[str, Any]) -> tuple[Optional[dict[str, str]], str]:
    """One relative .py replacement. Lean paths are refused."""

    rel = str(action.get("path") or action.get("file") or "")
    old = action.get("old")
    new = action.get("new")
    if not rel or not isinstance(old, str) or not isinstance(new, str):
        return None, "change_requires_path_old_new"
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts:
        return None, "path_outside_root"
    if path.suffix == ".lean":
        return None, "refusing_lean_path"
    if path.suffix != ".py":
        return None, "suffix_not_allowed"
    if old == new:
        return None, "empty_change"
    return {"path": path.as_posix(), "old": old, "new": new}, ""


def _write_py(root: Path, edit: Mapping[str, str]) -> tuple[bool, str, Optional[Callable[[], None]]]:
    """Replace old with new exactly once. Syntax must parse. Returns an undo."""

    import ast

    path = (Path(root) / str(edit["path"])).resolve()
    try:
        path.relative_to(Path(root).resolve())
    except ValueError:
        return False, "path_outside_root", None
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    old = str(edit["old"])
    new = str(edit["new"])
    if old:
        if current.count(old) != 1:
            return False, "old_text_not_unique", None
        updated = current.replace(old, new, 1)
    else:
        if path.exists():
            return False, "empty_old_requires_new_file", None
        updated = new
    try:
        ast.parse(updated, filename=str(path))
    except SyntaxError:
        return False, "syntax", None
    backup = current if path.is_file() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")

    def undo() -> None:
        if backup is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(backup, encoding="utf-8")

    return True, "applied", undo


def _refuse_lean(action: Mapping[str, Any]) -> str:
    """Memory actions must not name a Lean file. Proof text in the log is allowed."""

    for key in ("path", "file"):
        value = str(action.get(key) or "")
        if value.endswith(".lean"):
            return "refusing_lean_path"
    return ""


def _refuse_text(text: str) -> str:
    """Ignore ordinary words. A reply that targets a .lean file is refused upstream."""

    del text
    return ""


def rows_from_keepbest(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Historical lake rows. ``tactics_head`` is the stored proof excerpt, not a new admit."""

    name = str(payload.get("name") or "")
    rows: list[dict[str, Any]] = []
    for item in payload.get("candidates") or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            {
                "name": name,
                "ok": bool(item.get("ok")),
                "tokens": item.get("token_count"),
                "kind": item.get("kind") or "",
                "sorry": bool(item.get("sorry_in_theorem")),
                "tactics": item.get("tactics_head") or "",
            }
        )
    return rows


def replay_recorded(
    payload: Mapping[str, Any],
    *,
    path: Optional[Any] = None,
    root: Optional[Any] = None,
    rounds: int = 1,
    generate_fn: Optional[Callable[[str], str]] = None,
) -> dict[str, Any]:
    """Run one outer step over recorded lake rows, then one router improvement pass.

    The re-eval returns the best recorded lake-ok row unchanged. This does not
    start lake and does not invent a shorter proof, so a harness edit is not kept.
    """

    recorded = rows_from_keepbest(payload)
    best = None
    for row in recorded:
        record = eval_record(row, source="lake")
        if not record["lake_ok"]:
            continue
        if best is None or shorter(best, record):
            best = record
    watch = EvalWatch(path, memory={}, root=root)

    def inner(_step: int) -> dict[str, Any]:
        return {"lake": recorded}

    def reeval(_action: Mapping[str, Any], _memory: dict[str, Any]) -> dict[str, Any]:
        if best is None:
            return {"name": str(payload.get("name") or ""), "ok": False, "tokens": None}
        return {
            "name": best["name"],
            "ok": True,
            "tokens": best["tokens"],
            "heartbeats": best["heartbeats"],
            "tactics": best.get("proof") or "",
            "kind": best.get("stem") or "",
        }

    result = watch.run_outer(
        n=1,
        inner_fn=inner,
        board_fn=lambda: ({str(payload.get("name") or ""): int(best["tokens"]) if best and best.get("tokens") else 0}, int(best["tokens"]) if best and best.get("tokens") else 0),
        reeval_fn=reeval,
        rounds=rounds,
        llm=True,
        generate_fn=generate_fn,
    )
    result["live_lake"] = False
    result["recorded_rows"] = len(recorded)
    result["problem"] = str(payload.get("name") or "")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Replay one recorded canary through the watcher. Does not start lake."""

    import argparse

    parser = argparse.ArgumentParser(description="Run the JevOps eval watcher on recorded lake rows.")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args(list(argv) if argv is not None else None)
    payload = json.loads(args.evidence.read_text(encoding="utf-8"))
    result = replay_recorded(payload, path=args.log, rounds=args.rounds)
    print(json.dumps({k: result[k] for k in ("ok", "live_lake", "recorded_rows", "problem", "jev_writes_lean", "lake_oracle") if k in result}, sort_keys=True))
    improve = result.get("improve") or {}
    print(json.dumps({"accepted": improve.get("accepted"), "rounds": improve.get("rounds"), "summary": improve.get("summary")}, sort_keys=True, default=str))
    return 0


def _restore(memory: dict[str, Any], snapshot: Mapping[str, Any]) -> None:
    for key, value in snapshot.items():
        if value is None:
            memory.pop(key, None)
        else:
            memory[key] = copy.deepcopy(value)


if __name__ == "__main__":
    raise SystemExit(main())
