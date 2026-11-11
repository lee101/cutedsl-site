# Shared gallery storage permissions

After provisioning or changing the API service identity, run:

```bash
sudo bash deploy/configure-image-storage.sh /sdb-disk/cutedsl-images svc-cutedsl
```

This grants the deprivileged Go API access to the gallery directories and
adds an inherited named-user ACL. Inheritance keeps new monitor fallback
images readable by the API even with the monitor's security umask of 0077.
It does not change existing image ownership or recursively rewrite files.
Existing private files need a targeted read ACL for the API user.

The November 2 canary failed because the API could not write to the
administrator-owned originals directory, then the monitor indexed its own
0600 fallback file which the API could not read. The resulting public image
request returned 404 despite successful inference and database indexing.

## Repair verification (2026-11-02)

- Applied directory ACLs and a targeted read ACL to the failed canary file;
  purged only its cached Cloudflare 404. No binary or service restart needed.
- Original canary `3ce08e88-4351-4671-888e-4bf64f8ad14e` now returns WebP 200.
- Fresh public service generation `f766ef40-45d4-48c2-b80e-19b8ebb1410d`
  persisted via the API, returned WebP 200, and appeared in `/api/images`.
- Headless Chromium decoded both 512x512 images. All nine production route
  checks passed; all 22 observed JS/CSS URLs returned 200 with correct types.
- Local Go health, public Go health, and inference readiness returned OK.
- Permission and monitor regression tests: 22 passed.
- `go test ./...` passed with `LORA_TRAINING_BACKEND_URL=http://127.0.0.1:1`
  to isolate the suite's unavailable-training-backend expectation. Without
  that override the existing training-status test receives live upstream 403.
- Direct static-origin browsing also exposes relative API/RSC requests at
  appstatic.app.nz that return 404; it is an asset origin, not the application
  host. Production cutedsl.cc browser checks passed without these errors.
