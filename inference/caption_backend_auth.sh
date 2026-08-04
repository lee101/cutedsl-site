#!/bin/bash

# Verify the caption partner credential without loading the caption model.  The
# backend validates auth before trying to fetch this deliberately unreachable
# image URL, so an authenticated request returns 400 while stale credentials
# return 401/403.  Supply the header through curl's stdin config so the secret
# never appears in the process command line.
verify_caption_backend_auth() {
    if [ "${CAPTION_BACKEND_AUTH_PREFLIGHT:-1}" != "1" ]; then
        return 0
    fi

    local key="${CAPTION_BACKEND_API_KEY:-${NETWRCK_IMAGE_CAPTION_SECRET:-${TG_API_KEY:-}}}"
    if [ -z "$key" ]; then
        echo "Caption backend auth preflight failed: no scoped credential is configured" >&2
        return 1
    fi

    local backend_url="${TG_BACKEND_URL:-http://localhost:9080}"
    local status
    status=$(
        printf 'header = "secret: %s"\n' "$key" |
            curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
                --max-time "${CAPTION_BACKEND_AUTH_TIMEOUT:-5}" \
                --config - \
                --request POST \
                --data-urlencode 'image_url=http://127.0.0.1:1/cutedsl-caption-auth-preflight' \
                --data-urlencode 'fast_mode=true' \
                "${backend_url%/}/api/v1/image-caption"
    ) || {
        echo "Caption backend auth preflight failed: backend is unavailable" >&2
        return 1
    }

    case "$status" in
        401|403)
            echo "Caption backend auth preflight failed: backend rejected the scoped credential (HTTP $status)" >&2
            return 1
            ;;
        000)
            echo "Caption backend auth preflight failed: backend returned no HTTP response" >&2
            return 1
            ;;
    esac

    return 0
}
