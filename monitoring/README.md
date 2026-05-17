# CuteDSL Autofix Monitors

## Inference Errors

The inference monitor tails the structured inference error log:

`/nvme0n1-disk/tmp/cutedsl-inference-errors.jsonl`

When new `5xx` events appear, it launches CodexExec with a detailed repair prompt. It is rate-limited to one agent run per 3 hours by default.

## Command

The monitor uses:

```bash
codex exec -C /nvme0n1-disk/code/cutedsl-site \
  --add-dir /nvme0n1-disk/code/cutedsl \
  -m gpt-5.5 \
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
