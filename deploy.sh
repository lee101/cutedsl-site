#!/bin/bash
# Deploy CuteDSL site static frontend to appstatic.app.nz/cutedsl
# Multi-tenant R2 bucket: appstatic (shared with app.nz, deepsite, etc.)
set -e

echo "=== CuteDSL Site Deploy ==="
echo ""

# R2 Configuration (Cloudflare R2 - S3 compatible)
R2_ENDPOINT="${R2_ENDPOINT:-https://f76d25b8b86cfa5638f43016510d8f77.r2.cloudflarestorage.com}"
R2_BUCKET="${R2_BUCKET:-appstatic}"
BUCKET_PATH="${BUCKET_PATH:-cutedsl}"
STATIC_PATH="${STATIC_PATH:-static}"
STATIC_BASE_URL="${STATIC_BASE_URL:-https://appstatic.app.nz/$BUCKET_PATH/$STATIC_PATH}"
DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/cutedsl-site}"
AWS=(aws --endpoint-url "$R2_ENDPOINT")
SYNC_OPTS=(--size-only)

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
if [ -d "$OUT_DIR/_next" ]; then
    "${AWS[@]}" s3 sync "$OUT_DIR/_next" "s3://$R2_BUCKET/$BUCKET_PATH/$STATIC_PATH/_next/" "${SYNC_OPTS[@]}" --delete \
        --exclude '*.map' \
        --cache-control "public, max-age=31536000, immutable"
fi

if [ -d "$OUT_DIR/images" ]; then
    "${AWS[@]}" s3 sync "$OUT_DIR/images" "s3://$R2_BUCKET/$BUCKET_PATH/$STATIC_PATH/images/" "${SYNC_OPTS[@]}" --delete \
        --cache-control "public, max-age=31536000, immutable"
fi

"${AWS[@]}" s3 sync "$OUT_DIR" "s3://$R2_BUCKET/$BUCKET_PATH/" "${SYNC_OPTS[@]}" \
    --exclude '*.map' \
    --exclude '_next/*' \
    --exclude 'images/*' \
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
    mkdir -p "$DEPLOY_ROOT/frontend/out"
    rsync -a --delete "$OUT_DIR/" "$DEPLOY_ROOT/frontend/out/"
    find "$DEPLOY_ROOT/frontend/out" \( -name '*.fasthttp.gz' -o -name '*.fasthttp.br' \) -delete
    echo "  ✓ Frontend installed locally"

    if [ -w "$DEPLOY_ROOT/server" ]; then
        install -m 755 server/cutedsl-server "$DEPLOY_ROOT/server/cutedsl-server"
        echo "  ✓ Server binary installed locally"
    else
        echo "  ⚠ Skipping server binary install ($DEPLOY_ROOT/server is not writable)"
    fi
else
    echo "  ⚠ Skipping local install ($DEPLOY_ROOT not found)"
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

purge_urls() {
    local zone_id="$1"
    shift
    local urls=("$@")
    local batch_size=30
    local total=${#urls[@]}

    for ((i=0; i<total; i+=batch_size)); do
        local batch=("${urls[@]:i:batch_size}")
        local json_files=$(printf '%s\n' "${batch[@]}" | jq -R . | jq -s .)
        local resp
        resp=$(curl -s -X POST "https://api.cloudflare.com/client/v4/zones/${zone_id}/purge_cache" \
            -H "X-Auth-Email: ${CF_EMAIL}" \
            -H "X-Auth-Key: ${CF_API_KEY}" \
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
