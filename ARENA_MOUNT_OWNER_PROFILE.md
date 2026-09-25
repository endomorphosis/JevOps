# Opt-in rootless mount-owner import access

The default native verifier still runs as container UID/GID `65534:65534`.
The alternative `DockerIsolation(..., mount_owner_user=True)` runs as container
UID/GID `0:0` **only with the existing rootless daemon**. It is a different
execution policy (`jevops-arena-rootless-mount-owner/v1`), never an automatic
fallback after import failure. The watcher and its frozen configuration are
not changed.

## Why this may solve the import failure

The prepared Strata imports exist on the owner-only FUSE filesystem, but its
mount owner is host UID/GID 1000. The subordinate UID used by the default
container cannot access that mount, even when its directories are `0755`.
Linux documents FUSE's mount-owner access restriction in the
[FUSE overview](https://www.kernel.org/doc/html/latest/filesystems/fuse/fuse.html).

In rootless Docker, container UID zero maps to the daemon owner's unprivileged
host UID, not host root. See Docker's
[UID/GID mapping documentation](https://docs.docker.com/engine/security/rootless/uid-gid-mapping/).
Selecting this identity may permit the original read-only import mounts to
work directly. It requires no import copy, FUSE remount, `allow_other`, source
permission change, cache deletion, image growth, or new storage allowance.

## Security tradeoff and preserved controls

This **changes the worker identity** and removes the extra subordinate-UID
separation from the host owner. It is not security-equivalent to the default
profile, nor does UID zero become safe merely because it is namespaced. The
kernel, rootless daemon, image, runtime, and mount policy remain trusted.

The opt-in rejects a host-root UID/GID. Both profiles require the caller-owned
local socket, rootless daemon, seccomp and cgroup-v2 controls. Every worker is
inspected before starting. Host user namespaces, supplementary groups, extra
mounts, writable inputs, extra capabilities, and relaxed resource limits are
rejected. Both retain:

- read-only root filesystem, compiler, driver, imports and `/etc` network files;
- no capabilities, `no-new-privileges`, no networking, private PID/IPC/cgroups;
- one CPU, 2 GiB memory by default, no additional swap, 64 PIDs, bounded 64 MiB scratch;
- no host home, credentials, repository root or Docker socket mounts;
- immutable image selection, owned-container cleanup and no host fallback.

The profile and selected worker identity enter the context/plan hashes. Old
receipts do not establish readiness or performance under this profile. This is
still a single-process Lean verifier, **not** a separate kernel/report authority.
No automatic training, promotion, or reward admission is enabled.

## Validation before a model experiment

Live use needs explicit selection. First run synthetic isolation canaries on
the prepared FUSE volume with the current socket/image. The existing test
`test_live_host_mount_network_environment_and_kernel_limits` now checks import
readability; blocked writes and chmod; hidden host files/socket; environment and
network isolation; CPU/memory/swap/PID limits; all five capability sets;
`NoNewPrivs`; seccomp; and UID/GID mappings. Its observations can be retained in
pytest's generated JUnit report. Also run positive/negative proof-boundary and
timeout/output-cleanup canaries. These are fixtures, not Arena score evidence.

The live tests require `JEVOPS_ARENA_DOCKER_TESTS=1` and the additional explicit
`JEVOPS_ARENA_MOUNT_OWNER_USER=1`. Existing image/socket/toolchain variables are
unchanged. Use a new guarded run directory, shared preparation lock, and pytest
`--test-seal=off`; do not reuse old test seals as live authorization.

After those checks, the bounded repair experiment can select the profile:

```bash
python -m jevops.leanstral_repair_lab --watcher-config /path/to/config.json \
  --output /existing/capped/volume/new-owner-repair-run \
  --problem Core.InitsUpdatesComm --mount-owner-user --run
```

The pilot and canary runner also accept explicit `--memory-gib 4` and
`--memory-gib 8` options for separately approved bounded trials. Both default to
2 GiB; the watcher configuration
is not edited. The chosen memory cap enters the execution policy and plan;
the inspected swap limit still allows **no additional swap**. No automatic
memory escalation or allocation above 8 GiB is exposed by these experiment CLIs.

The unchanged reference must pass on every required pin before any model
requests. Import or resource failure still stops the run as unknown, not as
proof rejection. Fresh controlled replay is required before claiming heartbeat
gains. The implementation alone does not establish runtime success or benchmark
improvement.

## Live validation, September 23

The [generated pilot receipt](papers/completion/lean_refactor_arena/evidence/mount-owner-pilot-2026-09-23.json)
records nine passing live canaries with the alternate profile. Observed UID/GID
maps were container zero to host 1000; all capability sets were zero, seccomp
was active and `NoNewPrivs` was set. Read-only imports, permission-change
protection, resource bounds, positive/negative proof checks, and cleanup passed.

The first canary-runner attempt stopped after one passing test because pytest's
convenience symlinks violated the existing storage guard. Its artifacts remain
intact. The runner now supplies symlink-free temporary directories; the guard
was not weakened. Run it with a fresh directory on the capped volume:

```bash
python papers/completion/lean_refactor_arena/tools/run_mount_owner_canary.py \
  --watcher-config /path/to/config.json \
  --output /existing/capped/volume/new-owner-canary-run
```

The subsequent real `Core.InitsUpdatesComm` reference attempt on Lean 4.29.1
exited 137. Docker recorded an OOM event during the exclusive reference-run
window under the unchanged 2 GiB memory cap. That event is retained with its
container identity and timing; it is not cryptographically receipt-bound.
The native receipt is `ERROR`, not proof rejection. The other pins were not
checked and **zero model requests** ran. No token/heartbeat gain, score,
training or promotion was established. The watcher, cache-retention policy,
50 GB storage cap and memory limit remain unchanged. A higher bounded-memory
experiment requires an explicit choice; it is not an automatic retry.

### Approved 4 GiB follow-up

The [generated 4 GiB receipt](papers/completion/lean_refactor_arena/evidence/mount-owner-4g-pilot-2026-09-23.json)
records nine passing live canaries and two fresh reference requests. The
unchanged `Core.InitsUpdatesComm` reference passed on v4.29.1: 224 reference
tokens and 4,227 scaled native reference heartbeats (4,227,602 raw). These are
single-control baseline observations, not a compression or heartbeat gain.

The v4.27.0 reference then exited 137, with a Docker OOM event during that run's
window. v4.26.0 was not attempted. Zero model requests ran; no training,
promotion, or official score resulted. The default remains 2 GiB, and no limit
was automatically increased beyond this explicitly approved 4 GiB experiment.

### Approved 8 GiB follow-up

The [generated 8 GiB receipt](papers/completion/lean_refactor_arena/evidence/mount-owner-8g-pilot-2026-09-23.json)
records nine passing isolation canaries and passing unchanged references on
all three required pins. The 224-token reference had scaled native reference
heartbeats of 4,227 (v4.29.1), 4,657 (v4.27.0), and 4,689 (v4.26.0). These are
per-pin single-control baselines, not official scores or compression gains.

The bounded experiment reserved six model requests and made six native checks
(three references and three checks of one proposal). It returned no verified
refactor: two responses included a forbidden outer `by`, one was malformed
JSON, one was truncated, and one passed intake but failed on every pin by
applying `Not.intro` to a conjunction goal. The final request received its own
source-bound compiler feedback but ended with an unmeasured router failure.
Thus this run does **not** establish which prompting policy is better.

Model-token reservations totaled 15,592. The five measured responses account
for 7,973 tokens; total actual usage is unknown because the sixth request was
unmeasured. No retry, training, promotion, watcher restart or memory escalation
followed. All caches and the 50 GB storage cap remain intact.

Afterward, the repair ledger was hardened to retain allowlisted router failure
categories and valid HTTP status codes without copying exception text or server
bodies. The original failure category was not recorded and is not retroactively
inferred. Existing receipts remain untouched.
