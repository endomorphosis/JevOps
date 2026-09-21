#!/usr/bin/env python3
"""Run one fail-closed Grok CLI prompt as a router subprocess.

The installed Grok CLI's ``--prompt-file`` mode attaches to a long-running
leader session.  That is useful for the interactive TUI, but an outer LRA
router call can inherit the leader's exhausted turn budget and return
``max turns reached`` without generating anything.  The benchmark adapter
needs an independent, single-turn request instead.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys


_ACTIONS = frozenset(
    {
        "run",
        "nest_inner",
        "mint",
        "mint_tactic",
        "repair_tactic",
        "hypothesis_refactor",
        "skip_stem",
        "install_fold",
        "stop",
    }
)


def _first_outer_action(text: str) -> dict[str, object] | None:
    """Extract the first closed-vocabulary action from verbose Grok text.

    Grok's JSON envelope can contain a natural-language ``text`` field even
    when the prompt requests JSON-only output.  The benchmark's own parser is
    fail-closed, but normalising here keeps the router transport from
    discarding an otherwise valid first action because later model prose has
    additional braces.
    """

    decoder = json.JSONDecoder()
    source = str(text or "")
    for index, char in enumerate(source):
        if char != "{":
            continue
        try:
            candidate, _end = decoder.raw_decode(source, index)
        except json.JSONDecodeError:
            continue
        if not isinstance(candidate, dict):
            continue
        action = str(candidate.get("action") or "").strip()
        if action not in _ACTIONS:
            continue
        # Keep only the fields the outer protocol accepts.  This is a
        # transport normalisation step, not permission to invent an action.
        clean: dict[str, object] = {
            "action": action,
            "reason": str(candidate.get("reason") or "router"),
        }
        for key in (
            "stem",
            "name",
            "old",
            "new",
            "family",
            "strategy",
            "target",
            "hypothesis",
            "constraints",
            "evaluation",
            "focus",
            "path",
            "file",
            "diff",
        ):
            if key in candidate:
                clean[key] = str(candidate.get(key) or "")
        if isinstance(candidate.get("keep"), list):
            clean["keep"] = [str(item) for item in candidate["keep"]]
        return clean
    return None


def _normalise_cli_payload(stdout: str) -> str:
    """Return a JSON envelope whose text is one valid outer action when found."""

    try:
        payload = json.loads(str(stdout or ""))
    except json.JSONDecodeError:
        return stdout
    if not isinstance(payload, dict):
        return stdout
    action = _first_outer_action(str(payload.get("text") or ""))
    if action is not None:
        payload["text"] = json.dumps(action, separators=(",", ":"), ensure_ascii=False)
    return json.dumps(payload, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--leader-socket", default="")
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args(argv)

    binary = (
        os.environ.get("LRA_GROK_BIN", "").strip()
        or shutil.which("grok")
        or str(os.path.expanduser("~/.local/bin/grok"))
    )
    try:
        # Outer prompts contain the frozen board and Lake feedback.  Four
        # turns is not a reliable ceiling for Grok to emit the one JSON
        # action, and an exhausted request is not a useful benchmark sample.
        max_turns = max(1, int(os.environ.get("LRA_GROK_CLI_MAX_TURNS", "16")))
    except ValueError:
        max_turns = 16
    command = [
        binary,
        "--single",
        args.prompt,
        "--model",
        args.model,
        "--output-format",
        "json",
        "--no-plan",
        "--no-subagents",
        "--disable-web-search",
        "--no-memory",
        "--verbatim",
        "--max-turns",
        str(max_turns),
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
    ]
    if args.leader_socket:
        command[1:1] = ["--leader-socket", args.leader_socket]
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 127
    if result.stdout:
        sys.stdout.write(_normalise_cli_payload(result.stdout))
    if result.stderr:
        sys.stderr.write(result.stderr)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
