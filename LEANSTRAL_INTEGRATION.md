# Leanstral harness compatibility after migration

For empirical prompt/context selection and failure-mode measurements, see the
[Leanstral prompt lab](LEANSTRAL_PROMPT_LAB.md). Its bounded structured-message
path preserves this migration's default single-user prompt behavior.

Compatibility reference: the user's pinned
[`lift_coding` warm-up harness at `680c83db`](https://github.com/endomorphosis/lift_coding/blob/680c83db61c747d409f066750e3d753099008a52/papers/completion/lean_refactor_arena/harness/run_warmup.py).
That path uses **local docker0 Leanstral**, not hosted Mistral. Its contract is
unchanged: splice/retrieve → generate when healthy → lexical admission → every
listed Lean/Lake pin → keep-best. An unavailable server retains the reference;
generation failure is recorded, not converted into a successful fallback.
TypeSafe and hammers remain off on this frozen v1 path. No official score is
established by the local composite, these checks or the model response.

## What was repaired

- `harness/generate_text.py` now loads the in-tree router by default instead of
  unconditionally importing `ipfs_accelerate_py.llm_router`. It passes its pinned
  endpoint explicitly and reuses the warm-up loop's health observation.
- `jevops.leanstral` implements the bounded stdlib HTTP client;
  `jevops.llm_router` exposes `leanstral_local`, `leanstral-local` and `leanstral`.
  The deterministic default and other providers are unchanged. Strict route
  checking recognizes the alias, and failures clear stale generation traces.
- The toolchain shim previously auto-imported the datasets frontend merely
  because a sibling directory existed. It now requires
  `JEVOPS_USE_EXTERNAL_DEPS=1`. Default pinned compiler execution stays local.
- `run_warmup.py --offline-self-check` makes the 15-problem synthetic protocol
  explicitly offline, including health checks. Reports label these as fixtures.
  The historical `--self-check` and `--no-live` options retain their meanings.

`JEVOPS_USE_EXTERNAL_ROUTER=1` still explicitly selects the deprecated external
router. It is not needed here. No new runtime package dependency was added.

## Local usage

From this checkout, first perform a read-only health check:

```bash
python papers/completion/lean_refactor_arena/harness/run_warmup.py --probe-health
```

It queries docker0 `172.17.0.1:8080` and the loopback health alias, without starting
a server or taking its GPU lock. Success requires the **docker0** endpoint;
loopback availability alone never substitutes for it. A missing loopback alias
does not mark a healthy docker0 endpoint as erroneous.

To run a bounded actual warm-up problem with existing pinned Lean environments:

```bash
python papers/completion/lean_refactor_arena/harness/run_warmup.py \
  --run --name Core.InitsUpdatesComm --network deny \
  --state-root /prepared/track1-lake --elan-home /prepared/elan \
  --max-new-tokens 512 --generate-timeout 120 --compile-timeout 120 \
  --receipts-dir /owned/new-warmup-receipts
```

Replace the placeholder directories with prepared paths. This command was **not
run** during the migration check; it requires all of that task's pinned versions.
Do not use `--synthetic-compile` as evidence of a real Lean success. Follow the
[shared preparation lock and storage limits](ARENA_PREPARATION.md) for native
experiments, and leave GPU ownership to the existing server operator. This
change neither starts the owner script nor copies/downloads model weights.

The generic JevOps harness/router can also explicitly choose
`provider="leanstral_local", model_name="Leanstral"`. For callers outside the
frozen docker0 harness, pass `base_url="http://127.0.0.1:PORT/v1"` or set
`JEVOPS_LEANSTRAL_BASE_URL`; the legacy
`IPFS_ACCELERATE_LLAMA_CPP_BASE_URL` is also recognized. The frozen warm-up
continues pinning docker0 rather than obeying an unrelated generic endpoint.

Only HTTP docker0/loopback URLs with explicit ports and `/v1` or
`/v1/chat/completions` are accepted. There is no proxy inheritance, redirect,
authentication header, retry, autostart or cross-provider fallback. Invalid or
zero token/time budgets fail before a request. Responses are size-bounded,
must contain text and a recognized server model alias, and retain usage (including
zero), finish reason and request ID. Tool calls are not executed. Socket timeouts
are not whole-run deadlines; callers still own aggregate call/spend budgets.

`Leanstral` is the legacy logical model name; `leanstral_local` is the alias used
by the existing ephemeral server. Both are accepted, with the raw server model
retained as `response_model`. This checks a server claim, **not its loaded
weights or hardware**. Legacy `spark_gb10` labels are not hardware attestation.
All generated tactics remain untrusted until admission and actual verification.

## Hosted Mistral remains separate

`harness/track1_mistral_leanstral.py` retains its hosted-only adapter, explicit
credentials, ledger and no-docker0 contract. The new local route does not send
Mistral/TypeSafe/OpenAI keys and does not silently select hosted generation.
Mistral's [model documentation](https://docs.mistral.ai/models/leanstral-1-5)
lists `labs-leanstral-1-5`; its
[changelog](https://docs.mistral.ai/resources/changelogs) announces retirement
on September 30, 2026. Check service availability before a hosted run; no
replacement model, hosted call or pricing change was inferred in this work.

## Validation on September 23, 2026

Offline coverage includes both router and warm-up wiring, default dependency
isolation, exact request fields, alias handling, malformed/wrong-model output,
zero/non-finite limits, oversized responses, timeouts, HTTP errors, redirects,
proxy/credential exclusion, stale traces, healthy/down paths, admission failures,
end-marker removal and the 15-task protocol. An in-process fixture HTTP server
also exercises real sockets and redirect rejection; it is not a model.

Fresh regression command:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=refresh \
  tests/test_leanstral.py tests/test_dependency_boundary.py tests/test_harness_loop.py \
  tests/test_router_tuning.py tests/test_kernel_boundary.py \
  tests/test_lean_refactor_corpus.py tests/test_lean_refactor_upstream.py
```

Observed: **121 passed in 77.65 s**, with zero reused test seals. The standalone
`--offline-self-check` also passed: 15 fixture generations on the healthy path,
the three deliberate Putnam `sorry` failures retained, and zero generations
with reference retention for all 15 tasks on the down path. These are protocol
fixtures, not 15 new Lean proofs. The read-only real health probe returned HTTP
200 for docker0; the loopback alias was unavailable and was not used as fallback.

One actual local completion also traversed `run_warmup.maybe_generate` through
the in-tree router under the shared preparation lock. The prompt was
`Return only the Lean tactic rfl, with no explanation.`, capped at 16 new tokens
and 45 seconds. The server returned `rfl<|im_end|>` without fallback, reporting
35 prompt / 9 completion tokens; measured client wall time was about 0.76 s.
The [saved response and route metadata](papers/completion/lean_refactor_arena/evidence/leanstral-migration-live-probe-2026-09-23.json)
record `compiled=false`, `arena_score=null` and
`server_identity_attested=false`. The existing tactic extractor strips that
end marker. This verifies live generation, not a new proof or optimization.
No server was started, no model downloaded, no hosted API called, and no
credentials used. No full-corpus optimization or full-repository test claim is
made by this migration check.
