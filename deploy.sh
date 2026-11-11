#!/bin/bash
# Deploy CuteDSL site static frontend to appstatic.app.nz/cutedsl
# Multi-tenant R2 bucket: appstatic (shared with app.nz, deepsite, etc.)
set -e

DEPLOY_LOCK_FILE="${DEPLOY_LOCK_FILE:-/tmp/cutedsl-site-deploy.lock}"
exec 9>"$DEPLOY_LOCK_FILE"
if ! flock -n 9; then
    echo "ERROR: another CuteDSL deployment is already running"
    exit 1
fi

echo "=== CuteDSL Site Deploy ==="
echo ""

# R2 Configuration (Cloudflare R2 - S3 compatible)
# Keep deployment overrides project-scoped. Generic R2_BUCKET/BUCKET_PATH
# variables are commonly exported by other sites on this host and can silently
# send CuteDSL assets to the wrong bucket.
R2_ENDPOINT="${CUTEDSL_R2_ENDPOINT:-https://f76d25b8b86cfa5638f43016510d8f77.r2.cloudflarestorage.com}"
R2_BUCKET="${CUTEDSL_R2_BUCKET:-appstatic}"
BUCKET_PATH="${CUTEDSL_BUCKET_PATH:-cutedsl}"
STATIC_PATH="${CUTEDSL_STATIC_PATH:-static}"
STATIC_BASE_URL="${CUTEDSL_STATIC_BASE_URL:-https://appstatic.app.nz/$BUCKET_PATH/$STATIC_PATH}"
DEPLOY_ROOT="${CUTEDSL_DEPLOY_ROOT:-/opt/cutedsl-site}"
AWS=(aws --endpoint-url "$R2_ENDPOINT")
SYNC_OPTS=(--size-only)
LOCAL_INSTALL=()
LOCAL_RSYNC_OPTS=()

# The export embeds STATIC_BASE_URL, while uploads below use the fixed R2
# object prefix BUCKET_PATH/STATIC_PATH. Refuse a split-brain configuration
# before building or deleting any old objects.
python3 scripts/validate_static_deploy_config.py \
    --static-base-url "$STATIC_BASE_URL" \
    --bucket-path "$BUCKET_PATH" \
    --static-path "$STATIC_PATH"

# Validate local install privileges before publishing remote route documents.
# Production is root-owned on this host even when deploys run as the
# administrator account, so use non-interactive sudo when it is available.
if [ -d "$DEPLOY_ROOT" ] && { [ ! -w "$DEPLOY_ROOT/frontend/out" ] || [ ! -w "$DEPLOY_ROOT/server" ]; }; then
    if sudo -n true 2>/dev/null; then
        LOCAL_INSTALL=(sudo -n)
        LOCAL_RSYNC_OPTS=(--chown=root:root)
    else
        echo "ERROR: $DEPLOY_ROOT is not writable and non-interactive sudo is unavailable"
        exit 1
    fi
fi

# Step 1: Build frontend (static export for R2)
echo "[1/4] Building Next.js frontend (static export)..."
cd frontend
rm -rf out
build_ok=0
for attempt in 1 2 3; do
    if NEXT_OUTPUT=export NEXT_PUBLIC_STATIC_BASE_URL="$STATIC_BASE_URL" bun run build && [ -d out ]; then
        build_ok=1
        break
    fi
    echo "  ⚠ Frontend build attempt $attempt failed; retrying..."
    rm -rf out
done
if [ "$build_ok" -ne 1 ]; then
    echo "ERROR: Frontend static export failed after 3 attempts"
    exit 1
fi
cd ..
echo "  ✓ Frontend built"

# Determine output directory
OUT_DIR="frontend/out"
if [ ! -d "$OUT_DIR" ]; then
    echo "ERROR: No static export found. Expected $OUT_DIR"
    exit 1
fi
echo "  Using output: $OUT_DIR"
echo "  Static asset base: $STATIC_BASE_URL"

# Step 2: Sync static assets to R2
echo ""
echo "[2/4] Syncing to s3://$R2_BUCKET/$BUCKET_PATH/ ..."

# Static export mode: keep route documents at /cutedsl and hashed/static
# assets under /cutedsl/static so public asset URLs are predictable.
#
# Do not delete older _next assets here. Route HTML is served by both R2 and
# the local Go origin, so those two origins cannot switch builds atomically.
# Next.js assets are content-hashed and immutable; retaining prior builds keeps
# in-flight and cached HTML valid while every HTML origin converges.
if [ -d "$OUT_DIR/_next" ]; then
    "${AWS[@]}" s3 sync "$OUT_DIR/_next" "s3://$R2_BUCKET/$BUCKET_PATH/$STATIC_PATH/_next/" "${SYNC_OPTS[@]}" \
        --exclude '*.map' \
        --cache-control "public, max-age=31536000, immutable"
fi

if [ -d "$OUT_DIR/images" ]; then
    "${AWS[@]}" s3 sync "$OUT_DIR/images" "s3://$R2_BUCKET/$BUCKET_PATH/$STATIC_PATH/images/" "${SYNC_OPTS[@]}" \
        --cache-control "public, max-age=31536000, immutable"
fi

if [ -d "$OUT_DIR/videos" ]; then
    "${AWS[@]}" s3 sync "$OUT_DIR/videos" "s3://$R2_BUCKET/$BUCKET_PATH/$STATIC_PATH/videos/" "${SYNC_OPTS[@]}" \
        --cache-control "public, max-age=31536000, immutable"
fi

# Do not publish route HTML until every hashed asset is present. A missing
# chunk turns a successful 200 response into a client-side ChunkLoadError.
asset_drift=$("${AWS[@]}" s3 sync "$OUT_DIR/_next" "s3://$R2_BUCKET/$BUCKET_PATH/$STATIC_PATH/_next/" "${SYNC_OPTS[@]}" \
    --exclude '*.map' \
    --cache-control "public, max-age=31536000, immutable" \
    --dryrun)
if [ -n "$asset_drift" ]; then
    echo "ERROR: static asset upload did not converge; refusing to publish route HTML"
    echo "$asset_drift" | head -20
    exit 1
fi

# Route documents are mutable and can change build references without changing
# byte length. Use the default timestamp-and-size comparison here; --size-only
# can leave old HTML pointing at a different set of chunks.
"${AWS[@]}" s3 sync "$OUT_DIR" "s3://$R2_BUCKET/$BUCKET_PATH/" \
    --exclude '*.map' \
    --exclude '_next/*' \
    --exclude 'images/*' \
    --exclude 'videos/*' \
    --cache-control "public, max-age=3600"

# Remove stale root-level asset directories from the older layout.
"${AWS[@]}" s3 rm "s3://$R2_BUCKET/$BUCKET_PATH/_next/" --recursive --only-show-errors || true
"${AWS[@]}" s3 rm "s3://$R2_BUCKET/$BUCKET_PATH/images/" --recursive --only-show-errors || true

"${AWS[@]}" s3api put-object \
    --bucket "$R2_BUCKET" \
    --key "$BUCKET_PATH/" \
    --body "$OUT_DIR/index.html" \
    --content-type "text/html; charset=utf-8" \
    --cache-control "public, max-age=3600" >/dev/null
echo "  ✓ Static export synced"

# Step 3: Build Go server (optional - for API backend)
echo ""
echo "[3/4] Building Go server..."
cd server
go build -o cutedsl-server .
SERVER_SIZE=$(du -h cutedsl-server | cut -f1)
echo "  ✓ Server built ($SERVER_SIZE)"
cd ..

if [ -d "$DEPLOY_ROOT" ]; then
    echo "  Installing frontend to $DEPLOY_ROOT/frontend/out ..."
    "${LOCAL_INSTALL[@]}" mkdir -p "$DEPLOY_ROOT/frontend/out"
    "${LOCAL_INSTALL[@]}" rsync -a "${LOCAL_RSYNC_OPTS[@]}" "$OUT_DIR/" "$DEPLOY_ROOT/frontend/out/"
    "${LOCAL_INSTALL[@]}" find "$DEPLOY_ROOT/frontend/out" \( -name '*.fasthttp.gz' -o -name '*.fasthttp.br' \) -delete
    echo "  ✓ Frontend installed locally"

    "${LOCAL_INSTALL[@]}" install -m 755 server/cutedsl-server "$DEPLOY_ROOT/server/cutedsl-server"
    echo "  ✓ Server binary installed locally"
else
    echo "  ⚠ Skipping local install ($DEPLOY_ROOT not found)"
fi

# Frontend error telemetry is appended by the de-privileged service user, and
# /nvme0n1-disk/tmp is not writable by that account, so the JSONL sink lives in
# a service-owned directory behind the stable path the monitors already read.
TELEMETRY_DIR="/nvme0n1-disk/tmp/cutedsl-logs"
TELEMETRY_LOG="$TELEMETRY_DIR/frontend-errors.jsonl"
TELEMETRY_LINK="/nvme0n1-disk/tmp/cutedsl-frontend-errors.jsonl"
if sudo -n true 2>/dev/null; then
    sudo -n install -d -o svc-cutedsl -g svc-cutedsl -m 755 "$TELEMETRY_DIR"
    sudo -n touch "$TELEMETRY_LOG"
    sudo -n chown svc-cutedsl:svc-cutedsl "$TELEMETRY_LOG"
    sudo -n chmod 644 "$TELEMETRY_LOG"
    if [ -f "$TELEMETRY_LINK" ] && [ ! -L "$TELEMETRY_LINK" ]; then
        sudo -n sh -c "cat '$TELEMETRY_LINK' >> '$TELEMETRY_LOG' && rm -f '$TELEMETRY_LINK'"
    fi
    sudo -n ln -sfn "$TELEMETRY_LOG" "$TELEMETRY_LINK"
    echo "  ✓ Frontend error telemetry sink ready"
else
    echo "  ⚠ Skipping telemetry sink bootstrap (no non-interactive sudo)"
fi

# Step 4: Cache invalidation
echo ""
echo "[4/4] Clearing Cloudflare caches..."

CF_API_KEY="${CLOUDFLARE_API_KEY}"
CF_EMAIL="${CLOUDFLARE_EMAIL:-leepenkman@gmail.com}"
# appstatic.app.nz is served under the app.nz zone
CF_ZONE_APPNZ="${CLOUDFLARE_ZONE_APP_NZ}"
# cutedsl.cc zone (if configured separately)
CF_ZONE_CUTEDSL_CC="${CLOUDFLARE_ZONE_CUTEDSL_CC}"

cf_curl_headers() {
    # Scoped API tokens (40+ chars) use Bearer auth; legacy Global API keys use email+key.
    if [ "${#CF_API_KEY}" -ge 40 ]; then
        printf '%s\n' "-H" "Authorization: Bearer ${CF_API_KEY}"
    else
        printf '%s\n' "-H" "X-Auth-Email: ${CF_EMAIL}" "-H" "X-Auth-Key: ${CF_API_KEY}"
    fi
}

purge_urls() {
    local zone_id="$1"
    shift
    local urls=("$@")
    local batch_size=30
    local total=${#urls[@]}
    local -a cf_auth_headers=()
    while IFS= read -r line; do
        [ -n "$line" ] && cf_auth_headers+=("$line")
    done < <(cf_curl_headers)

    for ((i=0; i<total; i+=batch_size)); do
        local batch=("${urls[@]:i:batch_size}")
        local json_files=$(printf '%s\n' "${batch[@]}" | jq -R . | jq -s .)
        local resp
        resp=$(curl -s -X POST "https://api.cloudflare.com/client/v4/zones/${zone_id}/purge_cache" \
            "${cf_auth_headers[@]}" \
            -H "Content-Type: application/json" \
            --data "{\"files\": ${json_files}}")
        local ok=$(echo "$resp" | jq -r '.success // false')
        if [ "$ok" = "true" ]; then
            echo "  ✓ Purged batch $((i/batch_size+1)) (${#batch[@]} URLs)"
        else
            echo "  ✗ Batch $((i/batch_size+1)) failed: $(echo "$resp" | jq -r '.errors[0].message // "unknown"')"
        fi
    done
}

# URLs to purge on appstatic.app.nz (app.nz zone)
APPSTATIC_URLS=(
    "https://appstatic.app.nz/cutedsl/"
    "https://appstatic.app.nz/cutedsl/index.html"
    "https://appstatic.app.nz/cutedsl/blog.html"
    "https://appstatic.app.nz/cutedsl/evals.html"
    "https://appstatic.app.nz/cutedsl/search.html"
    "https://appstatic.app.nz/cutedsl/playground.html"
    "https://appstatic.app.nz/cutedsl/404.html"
    "https://appstatic.app.nz/cutedsl/blog/"
    "https://appstatic.app.nz/cutedsl/evals/"
    "https://appstatic.app.nz/cutedsl/search/"
    "https://appstatic.app.nz/cutedsl/playground/"
    "https://appstatic.app.nz/cutedsl/sitemap.xml"
    "https://appstatic.app.nz/cutedsl/robots.txt"
    "https://appstatic.app.nz/cutedsl/static/images/hero.webp"
    "https://appstatic.app.nz/cutedsl/static/images/og-image.webp"
    "https://appstatic.app.nz/cutedsl/static/images/og-blog.webp"
    "https://appstatic.app.nz/cutedsl/static/images/logo.webp"
    "https://appstatic.app.nz/cutedsl/static/images/logo.png"
    "https://appstatic.app.nz/cutedsl/static/images/favicon.ico"
    "https://appstatic.app.nz/cutedsl/static/images/apple-touch-icon.png"
    "https://appstatic.app.nz/cutedsl/static/images/avatar.webp"
    "https://appstatic.app.nz/cutedsl/static/images/training.webp"
    "https://appstatic.app.nz/cutedsl/static/images/token-bg.webp"
)

# Purge exact build-asset URLs as well. This is normally unnecessary for
# immutable content-hashed files, but it clears cached 404 responses when a
# previously interrupted upload is repaired and the object appears later.
while IFS= read -r asset_path; do
    APPSTATIC_URLS+=("$STATIC_BASE_URL/_next/$asset_path")
done < <(find "$OUT_DIR/_next" -type f ! -name '*.map' -printf '%P\n')

# URLs to purge on cutedsl.cc (if proxied through CF)
CUTEDSL_CC_URLS=(
    "https://cutedsl.cc/"
    "https://cutedsl.cc/blog"
    "https://cutedsl.cc/blog/"
    "https://cutedsl.cc/evals"
    "https://cutedsl.cc/evals/"
    "https://cutedsl.cc/search"
    "https://cutedsl.cc/search/"
    "https://cutedsl.cc/playground"
    "https://cutedsl.cc/playground/"
    "https://cutedsl.cc/sitemap.xml"
    "https://cutedsl.cc/robots.txt"
    "https://www.cutedsl.cc/"
)

if [ -n "$CF_API_KEY" ] && [ -n "$CF_ZONE_APPNZ" ]; then
    echo "  Purging appstatic.app.nz (app.nz zone)..."
    purge_urls "$CF_ZONE_APPNZ" "${APPSTATIC_URLS[@]}"
else
    echo "  ⚠ Skipping appstatic purge (set CLOUDFLARE_API_KEY and CLOUDFLARE_ZONE_APP_NZ)"
fi

if [ -n "$CF_API_KEY" ] && [ -n "$CF_ZONE_CUTEDSL_CC" ]; then
    echo "  Purging cutedsl.cc..."
    purge_urls "$CF_ZONE_CUTEDSL_CC" "${CUTEDSL_CC_URLS[@]}"
else
    echo "  ⚠ Skipping cutedsl.cc purge (set CLOUDFLARE_ZONE_CUTEDSL_CC)"
fi

echo ""
echo "=== Deploy Complete ==="
echo ""
echo "  Frontend:  https://appstatic.app.nz/cutedsl/"
echo "  Static:    $STATIC_BASE_URL/"
echo "  Bucket:    s3://$R2_BUCKET/$BUCKET_PATH/"
echo ""
echo "  Next steps:"
echo "    - Verify: curl -I https://appstatic.app.nz/cutedsl/"
echo "    - Server: Upload cutedsl-server binary and restart"
echo "    - Inference: Ensure inference server running on :8100"
