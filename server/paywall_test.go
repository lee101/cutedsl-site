package main

import (
	"encoding/json"
	"testing"

	"github.com/valyala/fasthttp"
)

func decodePaywall(t *testing.T, ctx *fasthttp.RequestCtx) map[string]string {
	t.Helper()
	var body struct {
		Error map[string]string `json:"error"`
	}
	if err := json.Unmarshal(ctx.Response.Body(), &body); err != nil {
		t.Fatalf("body not json: %v %s", err, ctx.Response.Body())
	}
	if got := string(ctx.Response.Header.Peek("X-Subscribe-URL")); got != subscribeURL() {
		t.Fatalf("X-Subscribe-URL=%q", got)
	}
	if body.Error["subscribe_url"] != subscribeURL() {
		t.Fatalf("subscribe_url=%q", body.Error["subscribe_url"])
	}
	return body.Error
}

func TestPaywallErrorContract(t *testing.T) {
	ctx := &fasthttp.RequestCtx{}
	paywallError(ctx, 402, "pay")
	if ctx.Response.StatusCode() != 402 {
		t.Fatalf("status %d", ctx.Response.StatusCode())
	}
	e := decodePaywall(t, ctx)
	if e["code"] != "subscription_required" || e["message"] != "pay" {
		t.Fatalf("bad error %v", e)
	}
}

func TestServiceUnauthenticatedReturnsContract401(t *testing.T) {
	ctx := &fasthttp.RequestCtx{}
	ctx.Request.SetBodyString(`{"service":"ra2-edit","prompt":"x","image_base64":"aGk="}`)
	handleServiceRequest(ctx)
	if ctx.Response.StatusCode() != 401 {
		t.Fatalf("status %d", ctx.Response.StatusCode())
	}
	if e := decodePaywall(t, ctx); e["code"] != "authentication_required" {
		t.Fatalf("bad code %v", e)
	}
}

func TestCheckUpstreamPaywall(t *testing.T) {
	if checkUpstreamPaywall(500, nil) != nil || checkUpstreamPaywall(200, nil) != nil {
		t.Fatal("non-paywall status mapped")
	}
	pe, ok := asUpstreamPaywall(checkUpstreamPaywall(401, []byte(`{"error":"invalid key"}`)))
	if !ok || pe.Status != 401 || pe.Message != "invalid key" {
		t.Fatalf("got %+v", pe)
	}
	pe, _ = asUpstreamPaywall(checkUpstreamPaywall(402, []byte("nope")))
	if pe.Message == "" {
		t.Fatal("empty default message")
	}
}

func TestUnlimitedImageServices(t *testing.T) {
	for _, s := range []string{"zimage", "ra2", "ra2-edit"} {
		if !isUnlimitedImageService(s) {
			t.Fatalf("%s should be unlimited for subscribers", s)
		}
	}
	if isUnlimitedImageService("video_generate") {
		t.Fatal("video must stay metered")
	}
}
