# Persistent supervisor watchdog

The JevOps campaign uses two enabled user services:

| Service | Responsibility |
| --- | --- |
| `jevops-agent-supervisor-watchdog.service` | Maintain the native watchdog, verify ownership and recover a dead or unresponsive watchdog. |
| `jevops-agent-supervisor-repair.service` | Observe task progress and dispatch one bounded maintenance agent for genuine unresolved incidents. |

Both restart automatically after a crash. User lingering is enabled on this host, so enabled services also run after logout and reboot. Native process locks and identity checks preserve a single owner. A monitor restart preserves healthy child actors; `KillMode=process` avoids terminating a production lane merely because its monitor restarts.

The guardian checks every 30 seconds. Recovery observes exact UID, executable, process start identity, repository, manifest and ownership. PIDFD signaling targets only a verified registered process. Fresh reports, advancing work, live check children, operator holds and storage pressure prevent an inappropriate watchdog replacement. The native watchdog independently handles lane heartbeats, progress stalls and eligible work left without an owner.

The repair dispatcher checks every 30 seconds, recognizes stale heartbeats after 120 seconds, stale watchdog reports after 600 seconds and absent progress after 900 seconds. It respects startup grace, actual cooldowns and operator holds. A maintenance worker has a 900-second deadline, a three-attempt incident limit and increasing cooldowns. Exit zero alone never establishes recovery: the dispatcher must observe fresh live evidence and resumed eligible work.

The maintenance agent uses the installed Codex CLI to repair supervisor code and setup. It is separate from the campaign's model route: all campaign proposals retain Grok 4.7 through `llm_router`, low reasoning effort, real traces and protected validation. The maintenance prompt preserves call budgets, task evidence, proof checks, unrelated work and explicit planned states. Idle observation makes no model calls. When the planned-work policy finds dependency-ready work without a runner, the bounded maintenance agent implements and validates the missing execution stage.

The original unstall manifest had zero provider/rescue caps that the framework rejected even with those features disabled. Its dormant caps are now positive, and all provider/rescue switches remain disabled. The separate bounded maintenance dispatcher handles unresolved operational repairs.

The fifteen bootstrap tasks have completed; the remaining twenty-three research stages are unfinished work. The enabled planned-work policy detects their dependency-ready frontier after 60 seconds without executable or active work, and dispatches a bounded materialization agent. The agent must implement and test a real producer and protected validator before queuing a stage. It preserves the bootstrap receipts and uses a versioned execution phase where necessary; changing a status alone cannot activate an experiment.

Future release dates use explicit UTC not-before gates with source evidence. Occupied GPU resources produce a real blocker and a cheap retry condition, while independent CPU work continues. Neither a planned label nor a fresh monitoring heartbeat establishes campaign completion. The watchdog preserves call history and exact-pin proof checks throughout continuation.

Research producers and their protected validators are registered in `config/lean_refactor_arena_20261024_execution_v2.json` and the separate `implementation_plan/lean_refactor_arena_20261024.execution-v2.todo.md` board. The original bootstrap contracts and receipts remain intact. The first registered stages prepare exact-pin projects, measure native baselines, qualify Leanstral resources and collect native span provenance. Missing projects, compiler timeouts and occupied GPUs remain explicit partial results or waits; they do not become proof successes.

Resource retries distinguish evidence consumed by an actual producer from observations made by a validation probe. A probe that first notices free resources cannot consume the producer's retry eligibility. Real producer refusals retain bounded backoff, and unchanged resource evidence cannot create a retry storm. The planned-work policy can materialize independent work during an evidenced resource wait, while actual producer and validation children prevent concurrent materialization.

Execution source changes require genuine focused tests followed by `tools/lean_refactor_execution_v2.py --refresh-tests <JUnit path>`. A source-only repair under a temporary integration hold uses `--source-only`, which requires a fresh paused lane acknowledgement, identical producer contracts and no active work. It archives prior approvals, rechecks semantic acceptance and preserves taskboard bytes. It cannot activate an additional stage or reset model budgets.

To reload dispatcher code from a maintenance worker, queue `systemctl --user start --no-block jevops-agent-supervisor-reload.service` and let the worker exit. This manual oneshot waits for the native repair-presence lock and an idle worker state before restarting only the registered repair daemon. It verifies a replacement process and a fresh report after the restart returns. A maintenance worker must not restart its own parent service or wait synchronously for this oneshot.

Run these commands from the JevOps root:

```bash
/home/barberb/lift_coding/external/ipfs_datasets/.venv/bin/python tools/manage_supervisor_watchdog.py
systemctl --user status jevops-agent-supervisor-watchdog.service jevops-agent-supervisor-repair.service
journalctl --user -u jevops-agent-supervisor-watchdog.service -u jevops-agent-supervisor-repair.service
```

The status command refreshes `data/lean_refactor_arena_20261024/persistent-watchdog/status.json`. Continuously updated observations are in `watchdog-guardian-status.json`, `watchdog-report.json` and `persistent-watchdog/repair-dispatcher/status.json` under the same campaign runtime directory. Installation and rollout verification receipts are retained alongside them.

Create `data/lean_refactor_arena_20261024/HOLD` to request an operator hold. The watchdog and repair dispatcher honor it. The setup tool does not remove operator holds. Reinstall with `tools/manage_supervisor_watchdog.py --install` after reviewing configuration changes; installation is serialized, backs up changed managed units and refuses unmanaged replacements.
