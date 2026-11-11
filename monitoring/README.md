# CuteDSL Production Monitor and Autofix

The primary monitor is a single systemd-timer-driven pipeline covering the
hydrated frontend, browser telemetry, the Go backend, inference readiness and
errors, and a real image generation/indexing canary.

## What it checks

- `check_frontend.mjs` opens the homepage at desktop and mobile sizes plus the
  gallery, docs, playground, search, account and trainer routes. It records
  `pageerror`, `console.error`, first-party request failures, 5xx responses,
  missing assets, empty hydration titles and the Next.js client-exception page.
- The existing `/api/frontend-error` JSONL stream is consumed incrementally.
- Public and local Go health plus GPU inference `/healthz` are checked.
- New `cutedsl.service` journal errors and structured inference 5xx JSONL rows
  are consumed and fingerprinted.
- Every six hours, an unlimited private canary identity makes one real Z-Image
  request through `https://cutedsl.cc/api/service`. The monitor requires the
  response to include a saved gallery row, downloads its image through the
  public origin, and queries `/api/images` until that exact ID is indexed.

Artifacts are written under ignored `monitoring/logs/`; offsets, cooldowns,
failure counters, handled fingerprints and the daily agent budget live under
ignored `monitoring/state/`.

## Repair behavior

Only one `cutedsl_monitor.py` process can run at once. The systemd service is a
oneshot, so a timer tick cannot overlap a long repair; an additional `flock`
also covers manual runs.

Noncritical signatures need two consecutive scans (gap <= 15 min) or three
occurrences within an hour. Panics, inference tracebacks/CUDA faults and
real-canary failures dispatch immediately. Health failures (including 5xx and
`starting`) are retried, use a stable per-endpoint fingerprint and need two
consecutive scans; Go health is skipped for one scan when `cutedsl.service` is
under 2 minutes old (never twice in a row, never in `--verify-only`). Journal
and inference-log noise is dropped: client disconnects, deadline/i/o timeouts,
DNS, 429/502/503/504, upstream, rate limit, shutdown, database starting. A single global repair
lock covers frontend, backend and inference incidents. Defaults:

- Agent: `gpt-6.1-terra`, high reasoning
- Global cooldown: 1 hour
- Per-category cooldown: 3 hours
- Daily repair-agent cap: 4
- Agent timeout: 3 hours
- Monitor interval: 5 minutes
- Real image canary: 6 hours; failed-canary retry: 15 minutes
- Health checks: 3 attempts, 10s/20s backoff (`CUTEDSL_HEALTH_RETRY_SECONDS`)

The production host also installs `deploy/cutedsl-resolv.conf` as
`/etc/resolv.conf`, providing multiple independent resolvers instead of relying
on the intermittently failing DHCP-provided resolver alone.

The repair prompt requires reproduction, a root-cause fix, a regression test,
focused and broad validation, deployment, and public post-deploy browser/API
verification. The parent monitor then independently repeats the relevant checks
before marking the fingerprint handled.

## Install and schedule

Provisioning creates or reuses a private `cutedsl-production-monitor` database
identity, marks only image generation unlimited, and stores its API key in the
gitignored `monitoring/.env` with mode `0600`.

```bash
./monitoring/install_systemd.sh --provision-canary
```

The installer places `cutedsl-monitor.service` and `cutedsl-monitor.timer` in
`/etc/systemd/system`, enables the timer and starts an initial check.

```bash
./monitoring/install_systemd.sh --status
systemctl list-timers cutedsl-monitor.timer
```

Manual checks:

```bash
# Full verification without launching an agent
python3 monitoring/cutedsl_monitor.py --verify-only --json

# Force a real generation, persistence, image and gallery-index check
python3 monitoring/cutedsl_monitor.py --verify-only --force-synthetic --json

# Exercise incident gating without launching Codex
python3 monitoring/cutedsl_monitor.py --dry-run-agent --skip-synthetic --json
```

Optional overrides can be placed in `/etc/cutedsl-monitor.env` or
`monitoring/.env`; see `.env.example`.

## Legacy monitors

The older supervisor/cron inference and frontend autofix entrypoints below are
kept for reference, but should not be enabled alongside the unified systemd
monitor because they use separate locks and cooldown state.

# Legacy CuteDSL Autofix Monitors

## Inference Errors

The inference monitor tails the structured inference error log:

`/nvme0n1-disk/tmp/cutedsl-inference-errors.jsonl`

When new `5xx` events appear, it launches CodexExec with a detailed repair prompt. It is rate-limited to one agent run per 3 hours by default.

The agent receives the CuteDSL kernels, native C gateway, text-generator
compatibility service, and RA1 gateway as writable related directories. Its
repair contract is to reproduce the failure, inspect the live managed-service
logs, add a regression test, restart only the affected managed unit, and then
retest localhost plus the public production route. It must preserve unrelated
dirty work and must not start duplicate inference processes.

For throughput incidents, inspect `/health` fields `gpu_queue`,
`dynamic_batching`, and `prompt_embedding_cache` before changing kernels.
`dynamic_batching.oom_batch_fallbacks` should remain zero. A high queue wait
with low pipeline time usually means the low-priority gallery generator is in
flight; public work should overtake it between images. The production service
uses adaptive batches, exact latent replay, CPU-resident text encoding, sticky
LoRAs, and an FP32 LoRA prewarm. Do not enable the Triton RoPE experiment on
Blackwell until its invalid-address-space failure has a regression test.

## Command

The monitor uses:

```bash
codex exec -C /nvme0n1-disk/code/cutedsl-site \
  --add-dir /nvme0n1-disk/code/cutedsl \
  --add-dir /nvme0n1-disk/code/omniserve-native \
  --add-dir /nvme0n1-disk/code/text-generator.io \
  --add-dir /nvme0n1-disk/code/netwrck \
  -m gpt-6.1-terra \
  -c model_reasoning_effort=high \
  -s danger-full-access \
  --dangerously-bypass-approvals-and-sandbox \
  -
```

If `/nvme0n1-disk/code/cutedsl` is not present, `--add-dir` is omitted.

## Run Manually

```bash
./monitoring/cutedsl_inference_autofix_monitor.sh
```

For a one-shot dry run against current unread errors:

```bash
/nvme0n1-disk/code/.venv/bin/python scripts/codexexec_autofix.py \
  --once \
  --dry-run \
  --error-log /nvme0n1-disk/tmp/cutedsl-inference-errors.jsonl
```

## Supervisor

Install or update the supervisor program with:

```bash
sudo cp monitoring/cutedsl-inference-autofix-supervisor.conf /etc/supervisor/conf.d/
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status cutedsl-inference-autofix
```

## Frontend Errors

The frontend app reports browser `error` and `unhandledrejection` events to:

`/api/frontend-error`

The Go server appends those events to:

`/nvme0n1-disk/tmp/cutedsl-frontend-errors.jsonl`

That path is a symlink to `/nvme0n1-disk/tmp/cutedsl-logs/frontend-errors.jsonl`,
owned by the `svc-cutedsl` service user: the service unit drops privileges, and
`/nvme0n1-disk/tmp` itself is not writable by that account. `deploy.sh`
re-creates the directory, file, and symlink. If the sink is ever unwritable the
server journals the event (`frontend error log append failed (event journaled)`)
instead of returning 500 to the browser reporter.

The frontend monitor only reacts to new JSONL error events in that file; it does not spin up agents for normal logs or non-error reports.

Run manually:

```bash
./monitoring/cutedsl_frontend_autofix_monitor.sh
```

Cron-compatible one-shot:

```bash
./monitoring/cutedsl_frontend_autofix_cron.sh
```

Example cron entry:

```cron
* * * * * /nvme0n1-disk/code/cutedsl-site/monitoring/cutedsl_frontend_autofix_cron.sh
```

Install or update the supervisor program with:

```bash
sudo cp monitoring/cutedsl-frontend-autofix-supervisor.conf /etc/supervisor/conf.d/
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status cutedsl-frontend-autofix
```

## Gallery Generator

The gallery dataset generator can run continuously as a low-priority background job:

```bash
sudo cp monitoring/cutedsl-gallery-generator-supervisor.conf /etc/supervisor/conf.d/
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status cutedsl-gallery-generator
```

It calls the local Z-Image endpoint with `low_priority=true`, so public `/api/service`
and `images.netwrck.com/create_and_upload_image` requests jump ahead of it between GPU jobs.
Logs go to `/nvme0n1-disk/tmp/cutedsl-gallery-generator.log`.

## Defaults

- Check interval: `60s`
- Cooldown: `10800s` / 3 hours
- Inference monitor log: `monitoring/cutedsl_inference_autofix_monitor.log`
- Frontend monitor log: `monitoring/cutedsl_frontend_autofix_monitor.log`
- Offset state: `/nvme0n1-disk/tmp/cutedsl-codexexec-autofix.state`
- Last-run state: `/nvme0n1-disk/tmp/cutedsl-codexexec-autofix-last-run`
- Frontend offset state: `/nvme0n1-disk/tmp/cutedsl-frontend-codexexec-autofix.state`
- Frontend last-run state: `/nvme0n1-disk/tmp/cutedsl-frontend-codexexec-autofix-last-run`
