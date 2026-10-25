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

Repeated failed retries retain their original escalation clock across subsequent producer and validator invocations. Unrelated board or monitor edits cannot postpone a qualified hard failure indefinitely. Cooling failures are reported as retry waits, and a cached controller policy that differs from the current source requires source review. Neither state clears the maintenance budget or establishes recovery.

The runtime qualifier receives only the validated local user-manager bus under `/run/user/<UID>`. Other experiment subprocesses retain their restricted environment. A failed launch produces a failure artifact containing its actual error evidence; it cannot copy an earlier qualification result. Completed smoke evidence remains historical: later acceptance checks current model custody, live resource guards and the same exact actor instead of expiring that evidence after five minutes or generating another response.

The reviewed `gpu-release-20261024` activation permits one additional ARC-dependent preload through an exclusive phase marker. It preserves the original preload marker and model verification receipts. Repeated launches cannot create another phase or refund that attempt. The server still keeps at least 16 GiB of host memory available, limits its RSS to 48 GiB and GPU usage to 20 GiB per card, and runs in a four-hour unit with no automatic model restart. Cache reclaim is an estimate; actual runtime guards remain authoritative.

The repair service also has a 120-second systemd watchdog. Notifications follow completed control-loop observations or real bounded worker polls, with no independent heartbeat thread. Status distinguishes the control heartbeat from the last full lane observation, so an active maintenance job does not fabricate campaign progress. On a watchdog timeout, systemd kills only the unresponsive dispatcher and restarts it; an active worker retains its original identity, shared exclusion marker, deadline and attempt count for adoption. Normal administrative reloads still use the idle-only oneshot.

A normal four-hour lane expiry receives a bounded native-restart grace before a code-repair worker is dispatched. The grace normally lasts 180 seconds, requires a verified responsive native watchdog, and is anchored to the exited process rather than refreshed polling timestamps. Failed restarts, crashes and stale watchdogs do not receive that grace.

Reviewed source extensions can use `tools/lean_refactor_execution_v2.py --refresh-tests <JUnit> --quiescent-maintenance` while the existing lane is held and has no active task or children. This checks actual process ownership, the unchanged registered scope and the exact hold before publication. Prepare source changes first, retain backups, and complete or roll back the bounded integration before releasing only its own hold. The source-only mode retains its stricter prohibition on contract and taskboard changes.

Completed runtime qualification is checked against its immutable response, captured ownership/resource guards and current artifact custody. It does not require an expired service to keep running. Current inference capability remains a separate live ownership check; neither historical evidence nor service renewal refunds a consumed experiment budget. Negative experiments remain recorded without completing tickets whose acceptance requires a verified improvement.

Run these commands from the JevOps root:

```bash
/home/barberb/lift_coding/external/ipfs_datasets/.venv/bin/python tools/manage_supervisor_watchdog.py
systemctl --user status jevops-agent-supervisor-watchdog.service jevops-agent-supervisor-repair.service
journalctl --user -u jevops-agent-supervisor-watchdog.service -u jevops-agent-supervisor-repair.service
```

The status command refreshes `data/lean_refactor_arena_20261024/persistent-watchdog/status.json`. Continuously updated observations are in `watchdog-guardian-status.json`, `watchdog-report.json` and `persistent-watchdog/repair-dispatcher/status.json` under the same campaign runtime directory. Installation and rollout verification receipts are retained alongside them.

Create `data/lean_refactor_arena_20261024/HOLD` to request an operator hold. The watchdog and repair dispatcher honor it. The setup tool does not remove operator holds. Reinstall with `tools/manage_supervisor_watchdog.py --install` after reviewing configuration changes; installation is serialized, backs up changed managed units and refuses unmanaged replacements.
