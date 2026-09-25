"""Zero-shot and in-context Lean prompts for Muse. The reply is not an admit.

Lake is the only check. These builders do not call the network and do not
write a file. The in-context examples are not the held-out target.
"""
from __future__ import annotations

import re
from typing import Mapping, Sequence


DEVELOPER = (
    "You complete Lean 4 proofs. Reply with only the tactic body that replaces sorry. "
    "No imports, no theorem line, no markdown, no explanation. "
    "Do not use sorry, admit, or axiom."
)

# Held out of the examples. Conjunction commutativity is the transfer task.
AND_COMM = "theorem museAnd (p q : Prop) (h : p ∧ q) : q ∧ p := by"
IDENTITY = "theorem museId (p : Prop) (h : p) : p := by"

_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("theorem iclRfl (n : Nat) : n = n := by", "rfl"),
    ("theorem iclExact (a : Prop) (ha : a) : a := by", "exact ha"),
)
_FENCE = re.compile(r"```(?:lean4?|plaintext)?\s*\n?(.*?)```", re.S | re.I)


def zero_shot(statement: str) -> list[dict[str, str]]:
    """No worked examples. The statement is the whole user turn."""

    return [
        {"role": "developer", "content": DEVELOPER},
        {"role": "user", "content": _task(statement)},
    ]


def refactor_prompt(record: Mapping, *, builder=None, available_lemmas: tuple[str, ...] = ()):
    """Source-bound refactoring/history messages, not the toy proof-completion task.

    Returns messages AND their provenance manifest. No transport, compilation,
    credential lookup or use of extract_tactic's permissive fence salvage.
    """
    from .refactor_prompts import RefactorPrompts
    if builder is None:
        builder = RefactorPrompts("coupled-repair")
    return builder.build_messages(record, provider="muse", available_lemmas=available_lemmas)


def in_context(statement: str, examples: Sequence[tuple[str, str]] = _EXAMPLES) -> list[dict[str, str]]:
    """Worked Lean pairs, then one new statement. Examples are not the target."""

    blocks = [_worked(header, tactic) for header, tactic in examples]
    blocks.append("Now reply with only the tactic body for:\n" + _task(statement))
    return [
        {"role": "developer", "content": DEVELOPER},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]


def extract_tactic(text: str) -> str:
    """Tactic body from a Muse reply. A fence is preferred. Not checked by Lake."""

    raw = str(text or "").strip()
    fenced = _FENCE.findall(raw)
    body = fenced[-1].strip() if fenced else raw
    if ":= by" in body:
        body = body.split(":= by", 1)[1]
    lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("```", "theorem ", "lemma ", "import ", "open ")):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def _task(statement: str) -> str:
    text = str(statement or "").strip()
    if not text:
        raise ValueError("empty Lean statement")
    return text + "\n  sorry\n"


def _worked(statement: str, tactic: str) -> str:
    body = "\n".join("  " + line if line else "" for line in str(tactic).splitlines())
    return str(statement).strip() + "\n" + body


def example_statements() -> tuple[str, ...]:
    return tuple(header for header, _tactic in _EXAMPLES)


def user_text(messages: Sequence[Mapping[str, str]]) -> str:
    return "\n".join(str(item.get("content") or "") for item in messages if item.get("role") == "user")


# Unrelated to the held-out equations. Copying it does not prove those goals.
EQUATION_EXAMPLE = "theorem unrel : ∀ a : Nat, a = a := by\n  intro a\n  rfl"
EQUATION_SYSTEM = (
    "Return ONLY one Lean 4 theorem and its proof. No imports, no markdown, no English. "
    "The statement must be an equation, or a conjunction of equations, written with =. "
    "Do not use sorry, admit, or axiom. "
    "Format-only example for an UNRELATED fact. Do not copy it.\n" + EQUATION_EXAMPLE
)
EQUATION_NAT = (
    " Nat.add recurses on its second argument, so n + 0 reduces to n and rfl is valid. "
    "0 + n does not reduce. Do not induct. The proof is intro, then exact Nat.zero_add, and then stop. "
    "A boolean variable does not reduce; case on it and then use rfl. "
    "A closed numeric comparison may use decide."
)


AUTOFORMAL_SYSTEM = (
    "Autoformalize one informal sentence into Lean 4. "
    "Return ONLY one theorem named formalized, and its proof. "
    "No imports, no markdown, and no English. Do not use sorry, admit, or axiom. "
    "The statement must be an equation written with =. "
    "Parenthesize the sides, as in (a + b) = c, because = binds tighter than ||, &&, +, and *. "
    "The sentence does not name Lean identifiers. You choose the binders and the equation. "
    "Compiler facts, which are not the sentence: "
    "Nat.add and Nat.mul recurse on the second argument, so n + 0 reduces and rfl is valid, "
    "while 0 + n and n * 1 do not. Do not induct for those. "
    "For a left zero of addition the proof is intro, then exact Nat.zero_add, then stop. "
    "For multiplication on the right by one the proof is intro, then exact Nat.mul_one, then stop. "
    "Bool.or matches its left argument, so a false on the left reduces and a false on the right does not. "
    "Case on a boolean variable and then use rfl. Closed numeric equations may use decide. "
    "Do not call tools and do not emit JSON. The reply must start with theorem formalized. "
    "The theorem name must be formalized, never unrel. "
    "The equation must use the operation in the sentence: addition needs +, multiplication needs *, "
    "and boolean or needs ||. Do not answer a = a. "
    "Format-only example for an UNRELATED fact. Do not copy its name or its equation.\n" + EQUATION_EXAMPLE
)


# Local Leanstral declares an 8192-token context. The legal prompt is short,
# so the completion can use the rest. Muse spends completion tokens on
# reasoning before it emits the file, so its cap is higher.
LEANSTRAL_AUTOFORMAL_MAX_TOKENS = 4096
MUSE_AUTOFORMAL_MAX_TOKENS = 8192

def _write_file_payload(text: str) -> str:
    """Lean buried in a write_file JSON string. Empty when that string has no Lean line."""

    marker = '"content": "'
    start = text.find(marker)
    if start < 0:
        return ""
    index = start + len(marker)
    escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}
    out: list[str] = []
    while index < len(text):
        char = text[index]
        if char == "\\":
            if index + 1 >= len(text):
                break
            out.append(escapes.get(text[index + 1], text[index + 1]))
            index += 2
            continue
        if char == '"':
            break
        out.append(char)
        index += 1
    decoded = "".join(out)
    if any(line.lstrip().startswith(("def ", "theorem ", "inductive ")) for line in decoded.splitlines()):
        return decoded
    return ""


def extract_lean_file(text: str) -> str:
    """Lean source from a completion. Drops a planning preamble and a later chat turn.

    Not a proof check. A file that still contains sorry is returned as written.
    A write_file payload is read only when its content has a Lean declaration line.
    """

    cut = _write_file_payload(str(text or "")) or str(text or "")
    for marker in ("<|im_end|>", "</s>", "<|endoftext|>"):
        cut = cut.split(marker, 1)[0]
    if "```" in cut:
        body = cut.split("```", 2)[1]
        if body.startswith("lean"):
            body = body[4:]
        cut = body
    lines = cut.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.lstrip().startswith(("def ", "theorem ", "inductive "))),
        None,
    )
    if start is None:
        return ""
    cut = "\n".join(lines[start:])
    for marker in ("<|im_start|>", "<|im_end|>"):
        cut = cut.split(marker, 1)[0]
    return cut.strip()


def autoformal_messages(sentence: str) -> list[dict[str, str]]:
    """Informal sentence in, one named equation theorem out. Not an admit."""

    text = str(sentence or "").strip()
    if not text:
        raise ValueError("empty informal sentence")
    if any(token in text for token in ("Nat.", ":=", "∀", "∧", "∨")):
        raise ValueError("informal sentence must not already be Lean")
    return [
        {"role": "developer", "content": AUTOFORMAL_SYSTEM},
        {"role": "user", "content": text},
    ]


def equation_messages(task: str, *, nat_recursion: bool = False) -> list[dict[str, str]]:
    """One theorem whose statement is an equation. The example is not the task.

    ``nat_recursion`` adds the Lean-specific fact that ``n + 0`` is definitional
    and ``0 + n`` is not. Without that sentence the model often swaps them.
    """

    system = EQUATION_SYSTEM + (EQUATION_NAT if nat_recursion else "")
    text = str(task or "").strip()
    if not text:
        raise ValueError("empty equation task")
    return [
        {"role": "developer", "content": system},
        {"role": "user", "content": text},
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Call Muse, then Lake, for one zero-shot and one in-context target.

    Does nothing on the network unless ``--live`` is passed. A Muse reply is
    not an admit. The report records whether Lake accepted the tactic.
    """

    import argparse
    import json
    import os
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Zero-shot and in-context Lean proposals from Muse.")
    parser.add_argument("--live", action="store_true", help="Call Muse Spark and check the tactic with lake.")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.live:
        print(json.dumps({"called_muse": False, "reason": "pass --live to call Muse and Lake"}))
        return 0

    from jevops.lean import token_count
    from jevops.llm_router import LLMRouterError, generate_text, get_last_generation_trace

    os.environ["PATH"] = str(Path.home() / ".elan" / "bin") + os.pathsep + os.environ.get("PATH", "")
    root = Path(__file__).resolve().parents[1]
    out = args.out or (root / ".improve-watch" / "muse-lean.json")
    jobs = (
        ("zero_shot", IDENTITY, zero_shot(IDENTITY)),
        ("zero_shot", AND_COMM, zero_shot(AND_COMM)),
        ("in_context", AND_COMM, in_context(AND_COMM)),
    )
    pkg = Path(tempfile.mkdtemp(prefix="muse-lean-"))
    (pkg / "lean-toolchain").write_text("leanprover/lean4:v4.26.0\n", encoding="utf-8")
    (pkg / "lakefile.lean").write_text(
        "import Lake\nopen Lake DSL\n\npackage «muselean»\n\n@[default_target]\nlean_lib MuseLean\n",
        encoding="utf-8",
    )
    rows = []
    auth_failed = False
    for mode, statement, messages in jobs:
        row: dict[str, object] = {"mode": mode, "statement": statement, "lake_oracle": True, "admit": False}
        if auth_failed:
            row["error"] = "skipped_after_auth"
            rows.append(row)
            continue
        try:
            reply = generate_text(
                "",
                provider="muse",
                messages=messages,
                max_new_tokens=2000,
                timeout=180,
                reasoning_effort="low",
            )
        except LLMRouterError as exc:
            row["error"] = str(exc)
            row["http_status"] = exc.http_status
            if exc.http_status in {401, 403}:
                auth_failed = True
            rows.append(row)
            continue
        tactic = extract_tactic(reply)
        trace = get_last_generation_trace()
        row["tactic"] = tactic
        row["tokens"] = token_count(tactic) if tactic else None
        row["finish_reason"] = trace.get("finish_reason")
        row["response_model"] = trace.get("response_model")
        row["usage"] = trace.get("usage")
        checked = _lake(pkg, statement, tactic)
        row.update(checked)
        rows.append(row)
    report = {
        "provider": "muse",
        "model": "muse-spark-1.3",
        "called_muse": True,
        "lake_oracle": True,
        "admit": False,
        "package": str(pkg),
        "rows": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "rows": [
        {k: row.get(k) for k in ("mode", "statement", "tactic", "tokens", "lake_ok", "sorry", "error")}
        for row in rows
    ]}, indent=2))
    return 0 if any(row.get("lake_ok") for row in rows) else 1


def _lake(pkg, statement: str, tactic: str) -> dict[str, object]:
    import subprocess

    if not tactic:
        return {"lake_ok": False, "sorry": False, "reason": "empty_tactic"}
    sorry = "sorry" in tactic.split() or "admit" in tactic.split()
    body = "\n".join(("  " + line) if line else "" for line in tactic.splitlines())
    (pkg / "MuseLean.lean").write_text(statement.rstrip() + "\n" + body + "\n", encoding="utf-8")
    proc = subprocess.run(
        ["lake", "build", "MuseLean"],
        cwd=pkg,
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    declaration_sorry = "declaration uses 'sorry'" in output
    # `lake build` with no default target exits 0 and reports 0 jobs. That is
    # not a compile. An up-to-date `lake build MuseLean` reports jobs and no error.
    compiled = "Built MuseLean" in output or (
        proc.returncode == 0 and "0 jobs" not in output and "error:" not in output
    )
    return {
        "lake_ok": compiled and not sorry and not declaration_sorry,
        "sorry": sorry or declaration_sorry,
        "lake_exit": proc.returncode,
        "lake_tail": output[-400:],
    }


if __name__ == "__main__":
    raise SystemExit(main())
