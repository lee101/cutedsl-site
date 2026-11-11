package main

import (
	"strings"
	"testing"

	"github.com/valyala/fasthttp"
)

func TestPublicGalleryCachePolicy(t *testing.T) {
	ctx := &fasthttp.RequestCtx{}
	setPublicGalleryCache(ctx)
	cache := string(ctx.Response.Header.Peek("Cache-Control"))
	if !strings.Contains(cache, "max-age=60") || !strings.Contains(cache, "stale-while-revalidate=3600") {
		t.Fatalf("unexpected public cache policy: %q", cache)
	}
	if got := string(ctx.Response.Header.Peek("Vary")); got != "Accept-Encoding" {
		t.Fatalf("Vary = %q", got)
	}
}
