from __future__ import annotations

from jevops import nca


def test_budget_and_pick_observations_do_not_halt_a_cold_nested_walk() -> None:
    memory = {"nca": {"grid": {}, "program_state": {"ops": [], "last_ran": []}}}

    nca.journal_event(memory, event="jev", ptr="ptr://tool/budget", op="BUDGET")
    nca.journal_event(memory, event="jev_pick", ptr="ptr://skill/port_x", op="PICK")

    halt = nca.should_halt(memory)

    assert halt["halt"] is False
    assert halt["budget_dead"] is False


def test_completed_program_receipt_can_halt_when_the_grid_is_idle() -> None:
    memory = {
        "nca": {
            "grid": {
                "ptr://goal/LRA-G000": {
                    "id": "ptr://goal/LRA-G000",
                    "kind": "goal",
                    "energy": 0.5,
                }
            },
            "program_state": {"ops": [{"op": "KEEP"}], "last_ran": [{"op": "TICK"}]},
        }
    }

    halt = nca.should_halt(memory)

    assert halt["halt"] is True
