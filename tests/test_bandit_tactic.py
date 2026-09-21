from __future__ import annotations

from jevops import rankers, tools
from jevops.nca import dispatch_tool
from jevops.tactics import multi_armed_bandit


def test_action_bandit_requires_observation_and_mirrors_nca_state() -> None:
    memory: dict = {"nca": {}}
    first = multi_armed_bandit(memory, ["port_simp", "port_cases"], seed=7)

    assert first["ok"] is True
    assert first["new_selection"] is True
    selected = first["selected_arm"]
    assert first["pending_arm"] == selected
    assert memory["nca"]["bandits"]["default"]["arms"][selected]["pulls"] == 0

    pending = multi_armed_bandit(memory, ["port_simp", "port_cases"])
    assert pending["new_selection"] is False
    assert pending["reason"] == "pending_observation"

    second = multi_armed_bandit(memory, ["port_simp", "port_cases"], reward=0.8)
    row = memory["nca"]["bandits"]["default"]["arms"][selected]
    assert second["observed_arm"] == selected
    assert row["pulls"] == 1
    assert row["reward_sum"] == 0.8
    assert memory["nca"]["grid"][f"ptr://skill/{selected}"]["wins"] == 1
    assert "ptr://cell/bandit/default" in memory["nca"]["grid"]
    assert ["ptr://cell/bandit/default", f"ptr://skill/{selected}"] in memory["nca"]["board_edges"]
    assert any(event["event"] == "bandit_observe" for event in memory["nca"]["journal"])


def test_bandit_policies_are_deterministic_and_reward_is_explicit() -> None:
    memory: dict = {"nca": {}}
    first = multi_armed_bandit(memory, ["a", "b"], name="ucb", policy="ucb1", seed=3)
    bad = multi_armed_bandit(memory, ["a", "b"], name="ucb", reward=2.0)
    assert bad["ok"] is False
    assert bad["reason"] == "reward_out_of_range"
    assert memory["nca"]["bandits"]["ucb"]["arms"][first["selected_arm"]]["pulls"] == 0

    observed = multi_armed_bandit(memory, ["a", "b"], name="ucb", reward=True)
    assert observed["observed_reward"] == 1.0
    assert observed["policy"] == "ucb1"
    assert observed["selected_arm"] in {"a", "b"}


def test_bandit_is_available_through_tool_nca_and_ranker_dispatch() -> None:
    memory: dict = {"nca": {}}
    tool_out = tools.run_tool(
        "multi_armed_bandit",
        memory=memory,
        observations={"arms": ["x", "y"], "bandit_name": "tool"},
    )
    assert tool_out["ok"] is True
    assert tool_out["tool"] == "multi_armed_bandit"

    nca_out = dispatch_tool("nca_bandit", memory=memory, arms=["x", "y"], bandit_name="nca")
    assert nca_out["ok"] is True
    assert nca_out["bandit"] == "nca"

    rank_out = rankers.call_ranker(
        "port_bandit",
        memory={"nca": {"grid": {"ptr://skill/arm": {"kind": "skill"}}}},
        selected="arm",
    )
    assert rank_out["ok"] is True
    assert rank_out["kind"] == "port_bandit"
    assert rank_out["selected_arm"] == "arm"

    invalid = tools.run_tool(
        "multi_armed_bandit",
        memory=memory,
        observations={"arms": ["x"], "reward": 2.0},
    )
    assert invalid["ok"] is False
    assert invalid["reason"] == "reward_out_of_range"
