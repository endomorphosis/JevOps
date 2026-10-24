# Persistent supervisor watchdog

The JevOps campaign uses two enabled user services:

| Service | Responsibility |
| --- | --- |
| `jevops-agent-supervisor-watchdog.service` | Maintain the native watchdog, verify ownership and recover a dead or unresponsive watchdog. |
| `jevops-agent-supervisor-repair.service` | Observe task progress and dispatch one bounded maintenance agent for genuine unresolved incidents. |

Both restart automatically after a crash. User lingering is enabled on this host, so enabled services also run after logout and reboot. Native process locks and identity checks preserve a single owner. A monitor restart preserves healthy child actors; `KillMode=process` avoids terminating a production lane merely because its monitor restarts.

The guardian checks every 30 seconds. Recovery observes exact UID, executable, process start identity, repository, manifest and ownership. PIDFD signaling targets only a verified registered process. Fresh reports, advancing work, live check children, operator holds and storage pressure prevent an inappropriate watchdog replacement. The native watchdog independently handles lane heartbeats, progress stalls and eligible work left without an owner.

The repair dispatcher checks every 30 seconds, recognizes stale heartbeats after 120 seconds, stale watchdog reports after 600 seconds and absent progress after 900 seconds. It respects startup grace, actual cooldowns and operator holds. A maintenance worker has a 900-second deadline, a three-attempt incident limit and increasing cooldowns. Exit zero alone never establishes recovery: the dispatcher must observe fresh live evidence and resumed eligible work.

The maintenance agent uses the installed Codex CLI to repair supervisor code and setup. It is separate from the campaign's model route: all campaign proposals retain Grok 4.7 through `llm_router`, low reasoning effort, real traces and protected validation. The maintenance prompt preserves call budgets, task evidence, proof checks, unrelated work and explicit planned states. Idle monitoring makes no model calls.

The original unstall manifest had zero provider/rescue caps that the framework rejected even with those features disabled. Its dormant caps are now positive, and all provider/rescue switches remain disabled. The separate bounded maintenance dispatcher handles unresolved operational repairs.

The fifteen bootstrap tasks have completed. The remaining twenty-three research experiments are explicitly planned and need their reviewed executable producers, native environments and activation evidence. A worker that exits after its four-hour limit with no eligible tasks is legitimate idle. Monitoring reports that backlog without restarting completed work, resetting budgets or treating the scientific campaign as complete.

Run these commands from the JevOps root:

```bash
/home/barberb/lift_coding/external/ipfs_datasets/.venv/bin/python tools/manage_supervisor_watchdog.py
systemctl --user status jevops-agent-supervisor-watchdog.service jevops-agent-supervisor-repair.service
journalctl --user -u jevops-agent-supervisor-watchdog.service -u jevops-agent-supervisor-repair.service
```

The status command refreshes `data/lean_refactor_arena_20261024/persistent-watchdog/status.json`. Continuously updated observations are in `watchdog-guardian-status.json`, `watchdog-report.json` and `persistent-watchdog/repair-dispatcher/status.json` under the same campaign runtime directory. Installation and rollout verification receipts are retained alongside them.

Create `data/lean_refactor_arena_20261024/HOLD` to request an operator hold. The watchdog and repair dispatcher honor it. The setup tool does not remove operator holds. Reinstall with `tools/manage_supervisor_watchdog.py --install` after reviewing configuration changes; installation is serialized, backs up changed managed units and refuses unmanaged replacements.
