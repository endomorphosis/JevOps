#!/usr/bin/env python3
"""Two-level JevOps autoresearch harness.

The inner loop is deliberately local and deterministic: it parses the JevOps
source tree, records structural observations, and lets the existing Jev
AutoResearch memory propose closed improvements.  The outer loop is the only
place that talks to an LLM.  It uses ``ipfs_accelerate_py.llm_router`` to
return a closed JSON action and accepts a source change only after evaluating
the change in an isolated copy of the repository.

This module is implementation-agnostic.  A consumer can inject an evaluator
for its own harness, or use the default bounded pytest/compile evaluator.
No model output is executed as Python and no model output is applied directly
to a worktree without validation.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from . import memory as memory_mod
from .outer import (
    apply_action,
    format_prompt,
    head_chars,
    head_tail,
    make_llm_router_generate,
    nca_status,
    route_next,
)


_DEFAULT_ALLOWED_PREFIXES = ("jevops",)
_DEFAULT_ALLOWED_SUFFIXES = (".py",)
_COPY_IGNORES = shutil.ignore_patterns(
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "*.pyc",
)
_TODO_MARKER_RE = re.compile(r"\b(?:TODO|FIXME)\b")


def _count_todo_markers(source: str) -> int:
    """Count TODO/FIXME markers in Python comments, not arbitrary strings."""

    try:
        tokens = tokenize.generate_tokens(io.StringIO(str(source)).readline)
        return sum(
            len(_TODO_MARKER_RE.findall(token.string))
            for token in tokens
            if token.type == tokenize.COMMENT
        )
    except (IndentationError, tokenize.TokenError):
        # Syntax errors are reported separately by ``analyze_self``.  A
        # partially tokenized file should not turn detector implementation
        # strings into false residuals.
        return 0


@dataclass(frozen=True)
class Evaluation:
    """Normalized evaluator result used by the outer acceptance gate."""

    score: float
    ok: bool
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: Any) -> "Evaluation":
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            raw_score = value.get("score")
            if raw_score is None:
                raw_score = value.get("passed")
            try:
                score = float(raw_score) if raw_score is not None else float(bool(value.get("ok")))
            except (TypeError, ValueError):
                score = 0.0
            ok = bool(value.get("ok", True if raw_score is not None else score > 0.0))
            return cls(score=score, ok=ok, details=dict(value))
        if isinstance(value, bool):
            return cls(score=1.0 if value else 0.0, ok=value, details={})
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = 0.0
        return cls(score=score, ok=score > 0.0, details={"value": value})

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "ok": self.ok, "details": dict(self.details)}


def _default_root() -> Path:
    cwd = Path.cwd().resolve()
    if (cwd / "jevops").is_dir():
        return cwd
    return Path(__file__).resolve().parents[1]


def _command_tuple(command: Any) -> tuple[str, ...]:
    if isinstance(command, str):
        return tuple(shlex.split(command))
    if isinstance(command, Sequence):
        return tuple(str(item) for item in command)
    return ()


class JevOpsHarness:
    """Run inner self-analysis and outer router-guided code experiments.

    Parameters:
        root: Repository root.  The default is the checkout containing this
            package, or the current checkout when it contains ``jevops/``.
        router_generate: Optional ``generate(prompt)`` callback.  If omitted,
            the callback is lazy-backed by ``ipfs_accelerate_py.llm_router``.
        evaluate_fn: Optional callable receiving an isolated repository path
            and returning ``Evaluation``-compatible data.  Supplying this is
            recommended for a real harness because it can score its oracle,
            latency, or token objective.
        test_command: Optional argv/string used by the default evaluator.
        allowed_prefixes: Relative top-level directories the router may edit.
            The default only permits ``jevops/`` source files.
    """

    def __init__(
        self,
        root: Optional[Path | str] = None,
        *,
        memory: Optional[dict[str, Any]] = None,
        router_generate: Optional[Callable[[str], Any]] = None,
        router: Any = None,
        model_name: Optional[str] = None,
        provider: Optional[str] = None,
        router_kwargs: Optional[Mapping[str, Any]] = None,
        evaluate_fn: Optional[Callable[[Path], Any]] = None,
        test_command: Any = None,
        timeout: float = 120.0,
        max_files: int = 200,
        max_source_chars: int = 6000,
        allowed_prefixes: Sequence[str] = _DEFAULT_ALLOWED_PREFIXES,
        allowed_suffixes: Sequence[str] = _DEFAULT_ALLOWED_SUFFIXES,
        accept_equal: bool = False,
        stalled_limit: int = 2,
        objective: str = "Improve JevOps by analyzing the JevOps harness itself",
    ) -> None:
        self.root = Path(root or _default_root()).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError(f"harness root is not a directory: {self.root}")
        self.memory = memory if memory is not None else memory_mod.empty_memory()
        self.evaluate_fn = evaluate_fn
        self.test_command = test_command
        self.timeout = max(1.0, float(timeout))
        self.max_files = max(1, int(max_files))
        self.max_source_chars = max(500, int(max_source_chars))
        self.allowed_prefixes = tuple(
            str(item).strip("/") for item in allowed_prefixes if str(item).strip("/")
        )
        self.allowed_suffixes = tuple(str(item) for item in allowed_suffixes)
        self.accept_equal = bool(accept_equal)
        self.stalled_limit = max(1, int(stalled_limit))
        self.objective = str(objective or "Improve JevOps")
        self.router_config = {
            "module": "ipfs_accelerate_py.llm_router",
            "provider": str(provider or "auto"),
            "model_name": str(model_name or "auto"),
            "reasoning_effort": str((router_kwargs or {}).get("reasoning_effort") or ""),
            "cross_provider_fallback": bool(
                (router_kwargs or {}).get("allow_cross_provider_fallback", True)
            ),
        }
        self.memory.setdefault("observations", {})["outer_router"] = dict(self.router_config)
        self.router_generate = router_generate or make_llm_router_generate(
            router=router,
            model_name=model_name,
            provider=provider,
            **dict(router_kwargs or {}),
        )
        self._last_analysis: dict[str, Any] = {}
        self._current_evaluation: Optional[Evaluation] = None

    def _source_base(self) -> Path:
        package = self.root / "jevops"
        return package if package.is_dir() else self.root

    def source_files(self) -> list[Path]:
        """Bounded source inventory used by the inner self-analysis."""

        base = self._source_base()
        blocked = {".git", ".venv", "__pycache__", ".pytest_cache"}
        paths = [
            path
            for path in base.rglob("*.py")
            if not any(part in blocked for part in path.parts)
        ]
        return sorted(paths)[: self.max_files]

    def _relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.root))
        except ValueError:
            return str(path)

    def analyze_self(self) -> dict[str, Any]:
        """Inner-loop structural analysis of the JevOps harness.

        The result is intentionally compact enough to pass to an outer model,
        while retaining per-file hotspots for the code-change proposal.
        """

        rows: list[dict[str, Any]] = []
        syntax_errors: list[dict[str, str]] = []
        n_functions = 0
        n_classes = 0
        n_control = 0
        n_lines = 0
        n_chars = 0
        n_todos = 0
        for path in self.source_files():
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                rows.append({"path": self._relative(path), "error": head_chars(exc, 160)})
                continue
            rel = self._relative(path)
            lines = len(source.splitlines())
            n_lines += lines
            n_chars += len(source)
            n_todos += _count_todo_markers(source)
            row: dict[str, Any] = {
                "path": rel,
                "lines": lines,
                "chars": len(source),
                "digest": hashlib.sha256(source.encode("utf-8")).hexdigest()[:12],
            }
            try:
                tree = ast.parse(source, filename=rel)
            except SyntaxError as exc:
                error = head_chars(exc, 200)
                syntax_errors.append({"path": rel, "error": error})
                row.update({"syntax_error": error, "n_functions": 0, "n_classes": 0})
                rows.append(row)
                continue
            functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
            control = [
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith))
            ]
            n_functions += len(functions)
            n_classes += len(classes)
            n_control += len(control)
            row.update(
                {
                    "n_functions": len(functions),
                    "n_classes": len(classes),
                    "n_control": len(control),
                    "function_names": [node.name for node in functions[:24]],
                }
            )
            rows.append(row)

        rows.sort(key=lambda item: (int(item.get("n_control") or 0), int(item.get("lines") or 0)), reverse=True)
        kernel_ast: dict[str, Any]
        try:
            from . import tools

            kernel_ast = dict(tools.harness_ast())
        except Exception as exc:
            kernel_ast = {"files": [], "reason": head_chars(exc, 160)}

        summary: dict[str, Any] = {
            "ok": not syntax_errors,
            "target": "jevops",
            "n_files": len(rows),
            "n_functions": n_functions,
            "n_classes": n_classes,
            "n_control": n_control,
            "n_lines": n_lines,
            "n_chars": n_chars,
            "n_todos": n_todos,
            "n_syntax_errors": len(syntax_errors),
            "syntax_errors": syntax_errors[:12],
            "hot_files": rows[:12],
            "kernel_harness_ast": kernel_ast,
            "called_docker0": False,
        }

        # Feed the structural residuals into the same AutoResearch memory
        # surface used by the TypeSafe skill loop.  This makes self-analysis
        # useful even when a consumer has not installed its board hooks.
        memory_mod.remember_research(
            self.memory,
            name="jevops.self",
            residuals={
                "syntax_errors": len(syntax_errors),
                "unfinished_markers": n_todos,
                "control_surface": n_control,
            },
            unsafe={
                "syntax_errors": 1.0 if syntax_errors else 0.0,
                "unfinished_markers": 0.5 if n_todos else 0.0,
                "control_surface": 0.0,
            },
            help_scores={
                "syntax_errors": 1.0 if syntax_errors else 0.05,
                "unfinished_markers": 0.25 if n_todos else 0.05,
                "control_surface": min(1.0, n_control / 1000.0),
            },
            skill="self_analysis",
            compose="analyze",
        )

        # This is the inner AutoResearch step.  It updates only bounded memory
        # and skill proposals; source changes remain an outer-loop operation.
        try:
            from . import tools

            inner_improvement = tools.self_improve(
                self.memory,
                name="jevops.self",
                tactics="self_analyze_harness",
            )
        except Exception as exc:
            inner_improvement = {"ok": False, "reason": head_chars(exc, 160)}
        summary["inner_improvement"] = inner_improvement
        self._last_analysis = summary
        observations = self.memory.setdefault("observations", {})
        observations["inner_self_analysis"] = summary
        observations["inner_loop"] = {
            "target": "jevops",
            "phase": "self_analysis",
            "n_files": len(rows),
            "n_syntax_errors": len(syntax_errors),
        }
        autoresearch = self.memory.setdefault("autoresearch", {})
        autoresearch["last_inner_analysis"] = summary
        autoresearch["inner_iterations"] = int(autoresearch.get("inner_iterations") or 0) + 1
        return summary

    def _gaps(self, analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        if analysis.get("n_syntax_errors"):
            issues.append({"residual": "syntax_errors", "help": 1.0, "unsafe": 1.0})
        if analysis.get("n_todos"):
            issues.append({"residual": "unfinished_markers", "help": 0.25, "unsafe": 0.0})
        if not issues:
            issues.append({"residual": "self_analysis", "help": 0.1, "unsafe": 0.0})
        return [
            {
                "name": "jevops.self",
                "proposed": dict((analysis.get("inner_improvement") or {}).get("proposed") or {}),
                "top_help": issues[:4],
                "keep_structure": [],
            }
        ]

    def _source_context(self, analysis: Mapping[str, Any]) -> str:
        chunks: list[str] = []
        for row in list(analysis.get("hot_files") or [])[:3]:
            rel = str(row.get("path") or "")
            if not rel:
                continue
            path = self.root / rel
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            chunks.append(f"--- {rel} ---\n{head_tail(source, self.max_source_chars // 2, self.max_source_chars // 2)}")
        return "\n".join(chunks)

    def _prompt(
        self,
        *,
        analysis: Mapping[str, Any],
        evaluation: Evaluation,
        gaps: Sequence[Mapping[str, Any]],
        history: Sequence[Mapping[str, Any]],
    ) -> str:
        action_names = ("run", "update_code", "stop")
        preamble = (
            "You are the OUTER improvement router for a JevOps autoresearch loop.\n"
            f"Objective: {self.objective}\n"
            "The INNER loop has already analyzed the JevOps harness itself.\n"
            "Choose one action and return exactly one JSON object.\n"
            "For update_code, use {\"action\":\"update_code\",\"changes\":["
            "{\"path\":\"jevops/file.py\",\"old\":\"exact text\",\"new\":\"replacement\"}"
            "],\"reason\":\"...\"}.\n"
            "Only edit files under the allowed JevOps source tree; do not return Python to execute.\n"
            "A change is accepted only when the evaluator improves.\n"
        )
        history_text = head_chars(str(list(history)[-4:]), 5000)
        extra = (
            f"current_evaluation={evaluation.to_dict()}\n"
            f"recent_outer_history={history_text}\n"
            "Use exact source snippets from code_context; do not invent old text.\n"
        )
        return format_prompt(
            preamble=preamble,
            actions=action_names,
            extra=extra,
            board={"score": evaluation.score},
            gaps=gaps,
            last_lake=[
                {
                    "name": "jevops.self",
                    "kind": "harness_evaluation",
                    "ok": evaluation.ok,
                    "tokens": evaluation.details.get("tokens"),
                }
            ],
            nca_status=nca_status(self.memory),
            total=evaluation.score,
            self_analysis=analysis,
            code_context=self._source_context(analysis),
        )

    def _default_evaluate(self, root: Path) -> Evaluation:
        command = _command_tuple(self.test_command)
        if not command:
            if (root / "tests").is_dir() and importlib.util.find_spec("pytest") is not None:
                command = (sys.executable, "-m", "pytest", "-q")
            else:
                command = (sys.executable, "-m", "compileall", "-q", "jevops")
        env = os.environ.copy()
        prior = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(root) + (os.pathsep + prior if prior else "")
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            output = head_tail(
                (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else ""),
                1200,
                1200,
                limit=2600,
            )
            ok = completed.returncode == 0
            return Evaluation(
                score=1.0 if ok else 0.0,
                ok=ok,
                details={"command": list(command), "returncode": completed.returncode, "output": output},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return Evaluation(
                score=0.0,
                ok=False,
                details={"command": list(command), "error": head_chars(exc, 300)},
            )

    def evaluate(self, root: Optional[Path] = None) -> Evaluation:
        target = Path(root or self.root).resolve()
        if self.evaluate_fn is not None:
            return Evaluation.from_value(self.evaluate_fn(target))
        return self._default_evaluate(target)

    def _normalize_changes(self, action: Mapping[str, Any]) -> tuple[list[dict[str, str]], str]:
        raw = action.get("changes")
        if not isinstance(raw, list):
            if action.get("path") or action.get("file"):
                raw = [action]
            else:
                return [], "missing_changes"
        changes: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, Mapping):
                return [], "change_not_object"
            rel = str(item.get("path") or item.get("file") or "")
            old = item.get("old")
            new = item.get("new")
            if not rel or not isinstance(old, str) or not isinstance(new, str):
                return [], "change_requires_path_old_new"
            candidate = Path(rel)
            if candidate.is_absolute() or ".." in candidate.parts:
                return [], "path_outside_root"
            normalized = candidate.as_posix()
            if normalized in seen:
                return [], "duplicate_path"
            if not any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in self.allowed_prefixes):
                return [], "path_not_allowed"
            if candidate.suffix not in self.allowed_suffixes:
                return [], "suffix_not_allowed"
            if len(old) > 100_000 or len(new) > 100_000:
                return [], "change_too_large"
            if old == new:
                return [], "empty_change"
            seen.add(normalized)
            changes.append({"path": normalized, "old": old, "new": new})
        return changes, "ok"

    def _apply_to_root(self, root: Path, changes: Sequence[Mapping[str, str]]) -> tuple[bool, str]:
        for change in changes:
            path = (root / str(change["path"])).resolve()
            try:
                path.relative_to(root.resolve())
            except ValueError:
                return False, "path_outside_root"
            old = str(change["old"])
            new = str(change["new"])
            exists = path.is_file()
            current = path.read_text(encoding="utf-8", errors="replace") if exists else ""
            if old:
                if current.count(old) != 1:
                    return False, f"old_text_count_{path.name}_{current.count(old)}"
                updated = current.replace(old, new, 1)
            else:
                if exists:
                    return False, "empty_old_requires_new_file"
                updated = new
            if path.suffix == ".py":
                try:
                    ast.parse(updated, filename=str(path))
                except SyntaxError as exc:
                    return False, f"syntax:{head_chars(exc, 220)}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(updated, encoding="utf-8")
        return True, "applied"

    def _record_update(self, receipt: Mapping[str, Any]) -> None:
        observations = self.memory.setdefault("observations", {})
        observations["last_code_update"] = dict(receipt)
        autoresearch = self.memory.setdefault("autoresearch", {})
        history = autoresearch.setdefault("history", [])
        history.append(dict(receipt))
        autoresearch["history"] = history[-32:]

    def apply_code_action(
        self,
        action: Mapping[str, Any],
        *,
        memory: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Validate, evaluate, and conditionally apply one router proposal."""

        changes, reason = self._normalize_changes(action)
        if not changes:
            receipt = {"ok": False, "accepted": False, "reason": reason, "applied": "update_code_rejected"}
            self._record_update(receipt)
            return receipt
        baseline = self._current_evaluation or self.evaluate(self.root)
        self._current_evaluation = baseline
        backups: dict[Path, Optional[str]] = {}
        with tempfile.TemporaryDirectory(prefix="jevops-candidate-") as temp_name:
            candidate_root = Path(temp_name) / self.root.name
            try:
                shutil.copytree(self.root, candidate_root, ignore=_COPY_IGNORES, symlinks=True)
                ok, apply_reason = self._apply_to_root(candidate_root, changes)
                if not ok:
                    receipt = {"ok": False, "accepted": False, "reason": apply_reason, "applied": "update_code_rejected"}
                    self._record_update(receipt)
                    return receipt
                candidate = self.evaluate(candidate_root)
            except (OSError, shutil.Error) as exc:
                receipt = {
                    "ok": False,
                    "accepted": False,
                    "reason": head_chars(exc, 300),
                    "applied": "update_code_rejected",
                }
                self._record_update(receipt)
                return receipt

            improved = (
                candidate.score > baseline.score
                or (candidate.ok and not baseline.ok)
                or (self.accept_equal and candidate.score == baseline.score and candidate.ok)
            )
            accepted = bool(candidate.ok and improved)
            receipt: dict[str, Any] = {
                "ok": accepted,
                "accepted": accepted,
                "reason": "evaluation_improved" if accepted else "evaluation_not_improved",
                "baseline": baseline.to_dict(),
                "candidate": candidate.to_dict(),
                "paths": [str(item["path"]) for item in changes],
                "applied": "update_code" if accepted else "update_code_rejected",
            }
            if accepted:
                for change in changes:
                    path = (self.root / str(change["path"])).resolve()
                    backups[path] = path.read_text(encoding="utf-8") if path.is_file() else None
                try:
                    ok, apply_reason = self._apply_to_root(self.root, changes)
                    if not ok:
                        raise RuntimeError(apply_reason)
                except Exception as exc:
                    for path, text in backups.items():
                        if text is None:
                            try:
                                path.unlink()
                            except FileNotFoundError:
                                pass
                        else:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text(text, encoding="utf-8")
                    receipt.update(
                        {
                            "ok": False,
                            "accepted": False,
                            "reason": f"apply_rollback:{head_chars(exc, 240)}",
                            "applied": "update_code_rejected",
                        }
                    )
                else:
                    self._current_evaluation = candidate
            self._record_update(receipt)
            return receipt

    def run(
        self,
        iterations: int = 1,
        *,
        persist_fn: Optional[Callable[[dict[str, Any]], Any]] = None,
    ) -> dict[str, Any]:
        """Run repeated inner-self-analysis → outer-router experiments."""

        baseline = self.evaluate(self.root)
        self._current_evaluation = baseline
        current = baseline
        history: list[dict[str, Any]] = []
        stalled = 0
        stop_reason = ""
        for step in range(max(0, int(iterations))):
            analysis = self.analyze_self()
            gaps = self._gaps(analysis)
            prompt = self._prompt(
                analysis=analysis,
                evaluation=current,
                gaps=gaps,
                history=history,
            )
            action = route_next(
                gaps=gaps,
                last_lake=[{"name": "jevops.self", "kind": "harness_evaluation", "ok": current.ok}],
                stalled=stalled >= self.stalled_limit,
                llm=True,
                memory=self.memory,
                generate_fn=self.router_generate,
                prompt=prompt,
            )
            applied = apply_action(self.memory, action, code_updater=self.apply_code_action)
            if applied.get("accepted") and isinstance(applied.get("candidate"), Mapping):
                current = Evaluation.from_value(applied["candidate"])
            improved = bool(applied.get("accepted"))
            stalled = 0 if improved else stalled + 1
            row = {
                "step": step,
                "inner": "self_analysis",
                "outer": "llm_router" if action.get("router") == "llm_router" else str(action.get("router") or "deterministic"),
                "analysis": analysis,
                "action": dict(action),
                "applied": dict(applied),
                "evaluation": current.to_dict(),
                "improved": improved,
                "stalled": stalled,
            }
            history.append(row)
            if persist_fn is not None:
                persist_fn(self.memory)
            if str(action.get("action") or "") == "stop":
                stop_reason = str(action.get("reason") or "stop")
                break
            if stalled >= self.stalled_limit:
                stop_reason = "no_outer_improvement"
                break
        result = {
            "ok": bool(current.ok),
            "baseline": baseline.to_dict(),
            "final_evaluation": current.to_dict(),
            "history": history,
            "stop_reason": stop_reason,
            "memory": self.memory,
            "called_docker0": False,
        }
        self.memory.setdefault("autoresearch", {})["last_run"] = {
            "n_steps": len(history),
            "stop_reason": stop_reason,
            "final_evaluation": current.to_dict(),
        }
        return result

    def run_forever(
        self,
        *,
        interval: float = 60.0,
        state_path: Optional[Path | str] = None,
        receipt_path: Optional[Path | str] = None,
        stop_event: Any = None,
        max_cycles: Optional[int] = None,
    ) -> dict[str, Any]:
        """Keep running one bounded inner/outer cycle until explicitly stopped.

        A failed router/evaluator cycle is recorded and does not terminate the
        supervisor.  Source changes still pass ``apply_code_action``'s isolated
        evaluation gate, so continuous mode can emit accepted improvements but
        cannot apply an unvalidated proposal.
        """

        state_file = Path(state_path).expanduser() if state_path else None
        receipt_file = Path(receipt_path).expanduser() if receipt_path else None
        delay = max(0.0, float(interval))
        cycle = 0
        last_result: dict[str, Any] = {
            "ok": True,
            "continuous": True,
            "cycles": 0,
            "history": [],
        }
        while True:
            if stop_event is not None and bool(stop_event.is_set()):
                break
            if max_cycles is not None and cycle >= max(0, int(max_cycles)):
                break
            cycle += 1
            started = time.time()
            try:
                result = self.run(iterations=1)
                accepted = sum(
                    1
                    for row in result.get("history") or []
                    if isinstance(row, Mapping)
                    and bool((row.get("applied") or {}).get("accepted"))
                )
                record: dict[str, Any] = {
                    "ok": bool(result.get("ok")),
                    "cycle": cycle,
                    "started_at": started,
                    "finished_at": time.time(),
                    "accepted_improvements": accepted,
                    "stop_reason": result.get("stop_reason") or "",
                    "final_evaluation": result.get("final_evaluation") or {},
                    "history": list(result.get("history") or [])[-1:],
                }
                last_result = {
                    **result,
                    "continuous": True,
                    "cycle": cycle,
                    "cycles": cycle,
                }
            except Exception as exc:  # keep the supervisor alive across outages
                record = {
                    "ok": False,
                    "cycle": cycle,
                    "started_at": started,
                    "finished_at": time.time(),
                    "accepted_improvements": 0,
                    "error": head_chars(exc, 400),
                }
                last_result = {
                    "ok": False,
                    "continuous": True,
                    "cycle": cycle,
                    "cycles": cycle,
                    "error": record["error"],
                    "history": [],
                }

            if state_file is not None:
                try:
                    memory_mod.save_memory(self.memory, state_file)
                except Exception as exc:
                    record["state_error"] = head_chars(exc, 240)
            if receipt_file is not None:
                try:
                    receipt_file.parent.mkdir(parents=True, exist_ok=True)
                    with receipt_file.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
                except Exception as exc:
                    record["receipt_error"] = head_chars(exc, 240)

            if stop_event is not None and bool(stop_event.is_set()):
                break
            if max_cycles is not None and cycle >= max(0, int(max_cycles)):
                break
            if delay:
                time.sleep(delay)

        last_result["continuous"] = True
        last_result["cycles"] = cycle
        last_result["stopped"] = True
        return last_result


def run_autoresearch(
    iterations: int = 1,
    *,
    root: Optional[Path | str] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience entry point for a JevOps inner/outer autoresearch run."""

    return JevOpsHarness(root=root, **kwargs).run(iterations)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for a bounded outer/inner run."""

    import argparse
    import json

    parser = argparse.ArgumentParser(description="Run JevOps self-analysis autoresearch")
    parser.add_argument("--root", default=str(_default_root()), help="JevOps repository root")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", dest="model_name", default=None)
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--strict-router", action="store_true", help="disable cross-provider fallback")
    parser.add_argument("--test-command", default=None, help="argv string used for candidate evaluation")
    parser.add_argument("--continuous", action="store_true", help="run one autoresearch cycle repeatedly")
    parser.add_argument("--interval", type=float, default=60.0, help="seconds between continuous cycles")
    parser.add_argument("--state-path", default=None, help="JSON memory state path for continuous mode")
    parser.add_argument("--receipt-path", default=None, help="JSONL cycle receipt path for continuous mode")
    args = parser.parse_args(list(argv) if argv is not None else None)
    state_path = args.state_path
    receipt_path = args.receipt_path
    if args.continuous:
        state_path = state_path or "/tmp/jevops-autoresearch-state.json"
        receipt_path = receipt_path or "/tmp/jevops-autoresearch-receipts.jsonl"
    router_kwargs = {}
    if args.reasoning_effort:
        router_kwargs["reasoning_effort"] = args.reasoning_effort
    if args.strict_router:
        router_kwargs["allow_cross_provider_fallback"] = False
    initial_memory = (
        memory_mod.load_memory(Path(state_path).expanduser()) if state_path else None
    )
    harness = JevOpsHarness(
        root=args.root,
        memory=initial_memory,
        provider=args.provider,
        model_name=args.model_name,
        router_kwargs=router_kwargs,
        test_command=args.test_command,
    )
    if args.continuous:
        result = harness.run_forever(
            interval=args.interval,
            state_path=state_path,
            receipt_path=receipt_path,
        )
    else:
        result = harness.run(args.iterations)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("ok") else 1


__all__ = ["Evaluation", "JevOpsHarness", "run_autoresearch", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
