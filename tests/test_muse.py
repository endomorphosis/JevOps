"""Muse router and Lean prompts. No live HTTP in this file."""
from __future__ import annotations

import io
import json
import urllib.request

import pytest

from jevops import llm_router, muse, muse_lean


def test_extract_lean_file_drops_a_planning_preamble() -> None:
    raw = "I need to formalize this.\n\ndef age : Nat := 25\ntheorem t : age = 25 := by decide\n<|im_start|>assistant\nmore"
    assert muse_lean.extract_lean_file(raw).startswith("def age")
    assert "<|im_start|>" not in muse_lean.extract_lean_file(raw)
    assert muse_lean.extract_lean_file("A boundary theorem must contain the number.") == ""
    buried = (
        'Plan. <|im_start|>tool_calls\n<|tool_call_begin|>tool\n'
        '{"name": "write_file", "arguments": {"path": "C.lean", "content": '
        '"def age : Nat := 25\\ntheorem t : age = 25 := by decide\\n"}}\n'
    )
    assert muse_lean.extract_lean_file(buried).startswith("def age")
    assert "theorem t" in muse_lean.extract_lean_file(buried)
    assert "write_file" not in muse_lean.extract_lean_file(buried)
    assert muse_lean.LEANSTRAL_AUTOFORMAL_MAX_TOKENS >= 4096
    assert muse_lean.MUSE_AUTOFORMAL_MAX_TOKENS >= 8192


def test_legal_autoformal_prompt_does_not_bake_in_the_text() -> None:
    from jevops.statement_lock import load_autoformal

    clause = "No Person shall be a Representative who shall not have attained to the Age of twenty five Years."
    autoformal = load_autoformal()
    msgs = autoformal.messages(clause)
    assert muse_lean.user_text(msgs) == clause
    assert "twenty five" not in msgs[0]["content"]
    assert "sorry" in msgs[0]["content"]
    assert "theorem unrel" not in msgs[0]["content"]
    assert "a = a" not in msgs[0]["content"]
    assert "do not add a rule" in msgs[0]["content"].lower()
    with pytest.raises(ValueError):
        autoformal.messages("theorem t : ∀ n : Nat, n = n := by rfl")


def test_autoformal_sentence_is_not_already_lean() -> None:
    sentence = "Zero placed on the left of a counting-number sum leaves that number unchanged."
    msgs = muse_lean.autoformal_messages(sentence)
    assert muse_lean.user_text(msgs) == sentence
    assert "Nat.zero_add" not in sentence
    assert "Nat.zero_add" in msgs[0]["content"]
    assert "named formalized" in msgs[0]["content"]
    with pytest.raises(ValueError):
        muse_lean.autoformal_messages("prove ∀ n : Nat, 0 + n = n")


def test_equation_prompt_keeps_addition_out_of_the_example() -> None:
    plain = muse_lean.equation_messages("Adding zero on the left leaves a natural number unchanged.")
    taught = muse_lean.equation_messages(
        "Adding zero on the left leaves a natural number unchanged.", nat_recursion=True,
    )
    assert muse_lean.user_text(plain).startswith("Adding zero on the left")
    assert "0 + n" not in plain[0]["content"]
    assert "a = a" in plain[0]["content"]
    assert "0 + n" in taught[0]["content"]
    assert "Nat.zero_add" in taught[0]["content"]


def test_prompts_keep_the_target_out_of_the_examples() -> None:
    zero = muse_lean.user_text(muse_lean.zero_shot(muse_lean.AND_COMM))
    icl = muse_lean.user_text(muse_lean.in_context(muse_lean.AND_COMM))
    examples, _task = icl.split("Now reply", 1)
    assert "rfl" not in zero and "exact ha" not in zero
    assert "sorry" in zero and "q ∧ p" in zero
    assert "rfl" in examples and "exact ha" in examples
    assert "q ∧ p" not in examples
    assert "q ∧ p" in icl


def test_extract_tactic_prefers_the_fence_and_drops_the_statement() -> None:
    text = "thinking\n```lean\ntheorem museAnd (p q : Prop) : q ∧ p := by\n  cases h\n  exact And.intro right left\n```\n"
    assert muse_lean.extract_tactic(text) == "cases h\n  exact And.intro right left"
    assert muse_lean.extract_tactic("exact h") == "exact h"


def test_missing_login_does_not_call_the_network(monkeypatch, tmp_path) -> None:
    for name in ("MODEL_API_KEY", "META_API_KEY", "JEVOPS_MUSE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(muse, "_AUTH", tmp_path / "missing.json")
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("network"))
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_a, **_k: pytest.fail("network"))
    with pytest.raises(muse.MuseError, match="MODEL_API_KEY"):
        muse.chat_completion("theorem t : True := by\n  trivial")


def test_router_posts_only_to_meta_and_hides_the_key(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "fixture-key")
    seen: dict[str, object] = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "https://api.meta.ai/v1/chat/completions"

    class Opener:
        def open(self, request, timeout):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            seen["auth"] = request.get_header("Authorization")
            seen["body"] = json.loads(request.data.decode())
            payload = {
                "model": "muse-spark-1.3",
                "choices": [{"message": {"role": "assistant", "content": "exact h.2.and h.1"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            }
            return Response(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_a, **_k: Opener())
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("direct urlopen"))
    text = llm_router.generate_text(
        "",
        provider="meta",
        messages=muse_lean.zero_shot(muse_lean.IDENTITY),
        max_new_tokens=30,
        timeout=7,
    )
    assert text == "exact h.2.and h.1"
    assert seen["url"] == "https://api.meta.ai/v1/chat/completions"
    assert seen["timeout"] == 7
    assert seen["auth"] == "Bearer fixture-key"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "muse-spark-1.3"
    assert body["reasoning_effort"] == "low"
    assert body["max_tokens"] == 30
    assert "temperature" not in body
    assert body["messages"][0]["role"] == "developer"
    trace = json.dumps(llm_router.get_last_generation_trace())
    assert "fixture-key" not in trace
    assert llm_router.get_last_generation_trace()["effective_provider_name"] == "muse"


def test_foreign_host_and_other_providers_do_not_accept_muse_messages(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "fixture-key")
    with pytest.raises(muse.MuseError):
        muse.endpoint("https://example.invalid/v1")
    with pytest.raises(llm_router.LLMRouterError, match="Leanstral and Muse"):
        llm_router.generate_text("x", provider="deterministic", messages=[{"role": "user", "content": "a"}])


def test_lake_check_builds_the_named_module(monkeypatch, tmp_path) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["cwd"] = kwargs.get("cwd")

        class Proc:
            returncode = 0
            stdout = "✔ Built MuseLean (1ms)\n"
            stderr = ""

        return Proc()

    monkeypatch.setattr("subprocess.run", fake_run)
    (tmp_path / "lakefile.lean").write_text("package\n", encoding="utf-8")
    result = muse_lean._lake(tmp_path, muse_lean.IDENTITY, "exact h")
    assert seen["cmd"] == ["lake", "build", "MuseLean"]
    assert result["lake_ok"] is True
    empty = muse_lean._lake(tmp_path, muse_lean.IDENTITY, "")
    assert empty["lake_ok"] is False

    def zero_jobs(cmd, **kwargs):
        del cmd, kwargs

        class Proc:
            returncode = 0
            stdout = "Build completed successfully (0 jobs).\n"
            stderr = ""

        return Proc()

    monkeypatch.setattr("subprocess.run", zero_jobs)
    skipped = muse_lean._lake(tmp_path, muse_lean.IDENTITY, "exact h")
    assert skipped["lake_ok"] is False


def test_numpy_not_imported() -> None:
    import sys

    already = "numpy" in sys.modules
    import jevops.muse as muse_mod
    import jevops.muse_lean as lean_mod

    assert muse_mod.DEFAULT_MODEL == "muse-spark-1.3"
    assert lean_mod.IDENTITY.startswith("theorem")
    if not already:
        assert "numpy" not in sys.modules
