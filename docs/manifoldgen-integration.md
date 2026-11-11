# ManifoldGen queued generation integration

CuteDSL keeps the ManifoldGen credential on the Go server and exposes durable,
user-owned video jobs to the frontend. Browser clients authenticate with their
normal CuteDSL API key; the ManifoldGen key is never returned to them.

## Server configuration

Set these values in the deployed CuteDSL environment file:

```bash
MANIFOLDGEN_API_KEY=sk-mg-...
MANIFOLDGEN_ORIGIN=https://manifoldgen.com
MANIFOLDGEN_DAILY_JOB_LIMIT=3
```

`MANIFOLDGEN_API_KEY` may fall back to the legacy `MANIFOLD_API_KEY` name.
The origin and daily limit are optional. A zero daily limit disables the quota;
accounts marked `unlimited_api` also bypass it.

## API

- `GET /api/generations/pricing` — cached ManifoldGen pricing preflight.
- `POST /api/generations` — validates and creates one durable AV1 video job.
- `GET /api/generations` — the authenticated user's recoverable job history.
- `GET /api/generations/{id}` — refreshes one job without resubmitting it.
- `POST /api/generations/{id}/publish` — opts a completed job into or out of
  the public gallery.
- `GET /api/videos` — cached merged feed of CuteDSL-published jobs and the
  explicitly public ManifoldGen featured feed.

Example:

```bash
curl -X POST https://cutedsl.cc/api/generations \
  -H "Authorization: Bearer $CUTEDSL_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "A glass whale swims through a flooded library",
    "aspect_ratio": "16:9",
    "size": "preview",
    "duration": 5,
    "num_steps": 20,
    "include_audio": true,
    "publish_on_finish": false
  }'
```

The response is HTTP 202 and contains a local `job_id` plus `status_url`.
Persist that ID and poll it. Never retry the POST merely because a client timed
out; GET polling is the recovery path.

## Indexing and media

New jobs always request `webm-av1`, regardless of a client-supplied output
format. Legacy featured MP4 clips remain playable through correct MIME
detection. Only explicitly published local jobs enter the public gallery.

`/sitemap-videos.xml` contains Google video extension records and is linked
from the root sitemap index. Public pages are `/video-gallery`; private history
is `/generations` and is marked `noindex`.
