#!/bin/bash
# Deploy CuteDSL site static frontend to appstatic.app.nz/cutedsl
# Multi-tenant R2 bucket: appstatic (shared with app.nz, deepsite, etc.)
set -e

echo "=== CuteDSL Site Deploy ==="
echo ""

# R2 Configuration (Cloudflare R2 - S3 compatible)
R2_ENDPOINT="${R2_ENDPOINT:-https://f76d25b8b86cfa5638f43016510d8f77.r2.cloudflarestorage.com}"
R2_BUCKET="${R2_BUCKET:-appstatic}"
BUCKET_PATH="cutedsl"
SYNC_OPTS="--endpoint-url $R2_ENDPOINT --size-only"

# Step 1: Build frontend (static export for R2)
echo "[1/4] Building Next.js frontend (static export)..."
cd frontend
NEXT_OUTPUT=export bun run build
cd ..
echo "  ✓ Frontend built"

# Determine output directory
if [ -d "frontend/out" ]; then
    OUT_DIR="frontend/out"
elif [ -d "frontend/.next/static" ]; then
    OUT_DIR="frontend/.next"
else
    echo "ERROR: No build output found. Expected frontend/out or frontend/.next"
    exit 1
fi
echo "  Using output: $OUT_DIR"

# Step 2: Sync static assets to R2
echo ""
echo "[2/4] Syncing to s3://$R2_BUCKET/$BUCKET_PATH/ ..."

if [ "$OUT_DIR" = "frontend/out" ]; then
    # Static export mode - sync everything
    aws s3 sync "$OUT_DIR" "s3://$R2_BUCKET/$BUCKET_PATH/" $SYNC_OPTS \
        --exclude '*.map' \
        --cache-control "public, max-age=31536000, immutable"
    aws s3api put-object \
        --endpoint-url "$R2_ENDPOINT" \
        --bucket "$R2_BUCKET" \
        --key "$BUCKET_PATH/" \
        --body "$OUT_DIR/index.html" \
        --content-type "text/html; charset=utf-8" \
        --cache-control "public, max-age=3600" >/dev/null
    echo "  ✓ Static export synced"
else
    # Next.js standalone - sync static assets only
    aws s3 sync "$OUT_DIR/static" "s3://$R2_BUCKET/$BUCKET_PATH/_next/static/" $SYNC_OPTS \
        --cache-control "public, max-age=31536000, immutable"

    # Sync public assets
    if [ -d "frontend/public" ]; then
        aws s3 sync "frontend/public" "s3://$R2_BUCKET/$BUCKET_PATH/" $SYNC_OPTS \
            --cache-control "public, max-age=3600"
    fi
    echo "  ✓ Static assets synced"
fi

# Step 3: Build Go server (optional - for API backend)
echo ""
echo "[3/4] Building Go server..."
cd server
go build -o cutedsl-server .
SERVER_SIZE=$(du -h cutedsl-server | cut -f1)
echo "  ✓ Server built ($SERVER_SIZE)"
cd ..

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
    "https://appstatic.app.nz/cutedsl/404.html"
    "https://appstatic.app.nz/cutedsl/blog/"
    "https://appstatic.app.nz/cutedsl/evals/"
    "https://appstatic.app.nz/cutedsl/search/"
    "https://appstatic.app.nz/cutedsl/sitemap.xml"
    "https://appstatic.app.nz/cutedsl/robots.txt"
    "https://appstatic.app.nz/cutedsl/images/hero.webp"
    "https://appstatic.app.nz/cutedsl/images/og-image.webp"
    "https://appstatic.app.nz/cutedsl/images/og-blog.webp"
    "https://appstatic.app.nz/cutedsl/images/logo.webp"
    "https://appstatic.app.nz/cutedsl/images/logo.png"
    "https://appstatic.app.nz/cutedsl/images/favicon.ico"
    "https://appstatic.app.nz/cutedsl/images/apple-touch-icon.png"
    "https://appstatic.app.nz/cutedsl/images/avatar.webp"
    "https://appstatic.app.nz/cutedsl/images/training.webp"
    "https://appstatic.app.nz/cutedsl/images/token-bg.webp"
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
echo "  Bucket:    s3://$R2_BUCKET/$BUCKET_PATH/"
echo ""
echo "  Next steps:"
echo "    - Verify: curl -I https://appstatic.app.nz/cutedsl/"
echo "    - Server: Upload cutedsl-server binary and restart"
echo "    - Inference: Ensure inference server running on :8100"
