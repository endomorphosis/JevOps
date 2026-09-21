from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from jevops.harness import JevOpsHarness, _count_todo_markers
from jevops.outer import make_llm_router_generate, parse_action


def _write_fixture(root: Path, body: str = "def value():\n    return 1\n") -> None:
    package = root / "jevops"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "target.py").write_text(body, encoding="utf-8")


def test_parse_code_action_with_braces_and_changes() -> None:
    action = parse_action(
        "router note {not json}\n"
        + json.dumps(
            {
                "action": "update_code",
                "changes": [
                    {
                        "path": "jevops/target.py",
                        "old": "return {1}",
                        "new": "return {2}",
                    }
                ],
            }
        )
    )
    assert action["action"] == "update_code"
    assert action["changes"][0]["old"] == "return {1}"


def test_ipfs_router_adapter_accepts_fixture_router() -> None:
    calls: list[tuple[str, dict]] = []

    def generate_text(prompt: str, **kwargs: object) -> str:
        calls.append((prompt, dict(kwargs)))
        return '{"action":"run"}'

    generate = make_llm_router_generate(
        router=SimpleNamespace(generate_text=generate_text),
        model_name="fixture-model",
        provider="fixture",
        temperature=0.0,
    )
    assert generate("hello") == '{"action":"run"}'
    assert calls[0][1] == {"temperature": 0.0, "model_name": "fixture-model", "provider": "fixture"}


def test_harness_inner_analysis_and_outer_update_accept_only_improvement() -> None:
    with TemporaryDirectory() as temp:
        root = Path(temp)
        _write_fixture(root)
        prompts: list[str] = []

        def generate(prompt: str) -> str:
            prompts.append(prompt)
            return json.dumps(
                {
                    "action": "update_code",
                    "changes": [
                        {
                            "path": "jevops/target.py",
                            "old": "return 1",
                            "new": "return 2",
                        }
                    ],
                }
            )

        def evaluate(candidate_root: Path) -> dict[str, object]:
            text = (candidate_root / "jevops" / "target.py").read_text(encoding="utf-8")
            return {"ok": True, "score": 1 if "return 2" in text else 0}

        harness = JevOpsHarness(root=root, router_generate=generate, evaluate_fn=evaluate)
        result = harness.run(iterations=1)

        assert result["ok"] is True
        assert result["history"][0]["inner"] == "self_analysis"
        assert result["history"][0]["outer"] == "llm_router"
        assert result["history"][0]["applied"]["accepted"] is True
        assert "inner_self_analysis" in harness.memory["observations"]
        assert harness.memory["research"][-1]["name"] == "jevops.self"
        assert "inner_self_analysis" in prompts[0]
        assert "return 1" not in (root / "jevops" / "target.py").read_text(encoding="utf-8")


def test_harness_rejects_non_improving_code_without_touching_root() -> None:
    with TemporaryDirectory() as temp:
        root = Path(temp)
        _write_fixture(root)

        harness = JevOpsHarness(
            root=root,
            router_generate=lambda _prompt: json.dumps(
                {
                    "action": "update_code",
                    "path": "jevops/target.py",
                    "old": "return 1",
                    "new": "return 3",
                }
            ),
            evaluate_fn=lambda _root: {"ok": True, "score": 1},
        )
        result = harness.run(iterations=1)

        assert result["history"][0]["applied"]["accepted"] is False
        assert "return 1" in (root / "jevops" / "target.py").read_text(encoding="utf-8")


def test_harness_continuous_mode_persists_receipts_and_state() -> None:
    with TemporaryDirectory() as temp:
        root = Path(temp)
        _write_fixture(root)
        state_path = root / "state.json"
        receipt_path = root / "receipts.jsonl"
        harness = JevOpsHarness(
            root=root,
            router_generate=lambda _prompt: '{"action":"run"}',
            evaluate_fn=lambda _root: {"ok": True, "score": 1},
        )

        result = harness.run_forever(
            interval=0,
            state_path=state_path,
            receipt_path=receipt_path,
            max_cycles=2,
        )

        assert result["continuous"] is True
        assert result["cycles"] == 2
        assert len(receipt_path.read_text(encoding="utf-8").splitlines()) == 2
        assert '"outer_router"' in state_path.read_text(encoding="utf-8")


def test_todo_detection_counts_comments_not_detector_strings() -> None:
    source = (
        '# TODO: one\n'
        'value = "TODO in a string"\n'
        '"""FIXME in a docstring"""\n'
        '# FIXME FIXME: two more\n'
    )
    assert _count_todo_markers(source) == 3
