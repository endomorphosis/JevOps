from __future__ import annotations

import importlib
from pathlib import Path

from jevops import hooks
from jevops.proof_tokens import TOKENIZER_ID, proof_source_tokens


def test_length_counter_is_explicit_and_immune_to_consumer_hooks(monkeypatch):
    source = "theorem t (n : Nat) : n = n := by\n  exact ⟨h, h⟩\n"
    before = proof_source_tokens(source)
    monkeypatch.setitem(hooks._HOOKS, "token_count", lambda _: 999999)
    assert proof_source_tokens(source) == before == 6
    assert TOKENIZER_ID == "lra-local-ws-punct/v1"


def test_counter_matches_frozen_benchmark_on_unicode_and_punctuation(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "papers/completion/lean_refactor_arena/harness"))
    benchmark = importlib.import_module("run_warmup")
    assert benchmark.TOKENIZER_ID == TOKENIZER_ID
    for body in ("exact ⟨h, h⟩", "simp only [Nat.zero_add, Nat.add_zero, Nat.mul_one]",
                 "rfl", "exact f' α₁", "cases b\ncase false =>\n  assumption"):
        assert proof_source_tokens(body) == benchmark.token_count(body)
        assert proof_source_tokens("theorem t : True := by\n" + body) == benchmark.token_count(body)
