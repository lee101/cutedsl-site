# ra2 image service

Adds a second image generation service, **ra2** ("ra2 art generator"), backed by a
separate omniserve-native instance. ra2 is now the default image service for
`POST /api/service` and for the on-site generators; `zimage` (Z-Image Turbo) stays
selectable everywhere.

## Backend contract

`RA2_BACKEND_URL` (default `http://127.0.0.1:8792`), auth via
`Authorization: Bearer $RA2_BACKEND_SECRET` and/or `X-API-Key` (both sent when the
secret is set; omitted when unset).

```
POST {RA2_BACKEND_URL}/v1/images/generations
{"prompt": str, "negative_prompt"?: str, "width": int, "height": int,
 "steps": int, "seed": int, "guidance_scale": float,
 "output_format": "webp", "n": 1, "teleport": true}
-> {"data":[{"b64_json": str, "seed": int, "inference_time_ms": int,
             "format": "webp"}], "model": str, "format": "webp"}
```

`POST /v1/images/edits` takes the same fields plus `image_base64` and backs the
`ra2-edit` service (same price as ra2). The Go server normalises the reply to the
zimage HTTP shape: `{image_base64, width, height, format, engine: "ra2", seed,
inference_time_ms, model}`, wrapped by the usual `/api/service` envelope
(`result`, `credits_used`, `credits_remain`, `usd_equivalent`, ...).

Width/height are clamped to positive multiples of 32 (default 1024x1024), steps
default 20, guidance_scale default 1.0.

## Changed files

- `server/services.go` — `ra2` / `ra2-edit` pricing, first-party tier, backend
  registration, `defaultServiceName()` (env `RA2_DEFAULT`), units map, `ra2-edit`
  input validation, `proxyToRA2` translation + response normalisation, `ra2`/
  `ra2-edit` routing in `proxyToBackend`.
- `server/models.go` — `ServiceUsageRequest` gains `negative_prompt` and
  `image_base64`; width/height/steps/guidance/seed now documented as shared image
  fields; default service comment updated.
- `server/api_test.go` — `TestPricing` also expects `ra2` and `ra2-edit`.
- `server/ra2_test.go` (new) — request translation, dimension snapping, edit
  endpoint + image passthrough, response normalisation, backend-error handling,
  service registration, default-service env behaviour, all against a mock backend.
- `server/prompt_pages.go` — `/docs/ra2` and `/docs/ra2-edit` added to the sitemap.
- `frontend/lib/models.ts` — `ra2` and `ra2-edit` model entries (docs pages,
  playgrounds, model explorer, `/docs` list are generated from this list).
- `frontend/app/gallery/page.tsx` — generator defaults to ra2 with a
  ra2 / Z-Image Turbo selector, per-service prices pulled from `/api/pricing`;
  about-section curl hint now shows `service: "ra2"`.
- `frontend/app/page.tsx` — Try It playground defaults to ra2 with a selector,
  ra2 model card (badged "default") in the models grid, ra2 in the API reference
  example and preview cards, service-count and footer copy.
- `frontend/app/layout.tsx`, `frontend/app/docs/layout.tsx`,
  `frontend/app/docs/page.tsx`, `frontend/lib/blog-posts.ts` — image-model copy
  now names ra2 as the default image service.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `RA2_BACKEND_URL` | `http://127.0.0.1:8792` | omniserve-native base URL for `ra2` and `ra2-edit` |
| `RA2_BACKEND_SECRET` | unset | sent as `Authorization: Bearer <secret>` and `X-API-Key` |
| `RA2_PRICE_USD` | zimage price | USD price for `ra2`; `ra2-edit` always mirrors `ra2` |
| `RA2_DEFAULT` | unset | set to `0` to fall back to `zimage` as the default service |

## Verification

```
cd server && TEST_DATABASE_URL=... go build ./... && go test ./...
cd frontend && npx tsc --noEmit && bun run lint
```

Smoke-tested against a mock backend: default `/api/service` call (no `service`
field) hits `/v1/images/generations` with the full contract and returns
`engine: "ra2"`; `ra2-edit` hits `/v1/images/edits` with `image_base64` and is
rejected with 400 when the image is missing; `RA2_DEFAULT=0` restores zimage;
gallery and home page generate via ra2 with the selector switching services.
