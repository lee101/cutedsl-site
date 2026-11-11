package main

import (
	"strings"
	"testing"

	"github.com/valyala/fasthttp"
)

func TestServeImageFallsBackToStaticOrigin(t *testing.T) {
	t.Setenv("IMAGES_DIR", t.TempDir())
	t.Setenv("CUTEDSL_IMAGES_R2_BASE_URL", "https://appstatic.app.nz/cutedsl/gallery/")

	ctx := &fasthttp.RequestCtx{}
	serveImage(ctx, "/images/thumbs/missing.webp")
	if got := ctx.Response.StatusCode(); got != fasthttp.StatusFound {
		t.Fatalf("missing gallery image status = %d, want 302", got)
	}
	if got := string(ctx.Response.Header.Peek("Location")); got != "https://appstatic.app.nz/cutedsl/gallery/thumbs/missing.webp" {
		t.Fatalf("redirect location = %q", got)
	}
	if cache := string(ctx.Response.Header.Peek("Cache-Control")); !strings.Contains(cache, "immutable") {
		t.Fatalf("redirect cache policy = %q", cache)
	}

	ctx = &fasthttp.RequestCtx{}
	serveImage(ctx, "/images/other/missing.webp")
	if got := ctx.Response.StatusCode(); got != fasthttp.StatusNotFound {
		t.Fatalf("unrelated missing image status = %d, want 404", got)
	}
}
