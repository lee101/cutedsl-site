package main

import (
	"strings"
	"testing"
)

func TestTHEventPayload(t *testing.T) {
	p := thEventPayload(thEvent{Name: "purchase", UserID: "u1", EventID: "stripe:cs_1", Props: map[string]interface{}{"plan": "monthly"}})
	if p["site_id"] != thWriteKey {
		t.Fatalf("site_id = %v", p["site_id"])
	}
	ev := p["events"].([]interface{})[0].(map[string]interface{})
	if ev["client_id"] != "u1" || ev["user_id"] != "u1" || ev["event_id"] != "stripe:cs_1" {
		t.Fatalf("event = %v", ev)
	}
	if _, ok := ev["session_id"]; ok {
		t.Fatal("empty session_id should be omitted")
	}
}

func TestStripeAnalyticsMetadata(t *testing.T) {
	md := map[string]string{}
	stripeCheckoutRequest{THClientID: " c1 ", THSessionID: strings.Repeat("x", 200), THSurface: "account"}.addAnalyticsMetadata(md)
	if md["th_cid"] != "c1" || md["th_surface"] != "account" {
		t.Fatalf("metadata = %v", md)
	}
	if _, ok := md["th_sid"]; ok {
		t.Fatal("oversized th_sid should be dropped")
	}
}

func TestSSRPagesIncludeTHSnippet(t *testing.T) {
	for _, tpl := range []string{promptPageTemplate.Tree.Root.String(), tagPageTemplate.Tree.Root.String(), tagsIndexTemplate.Tree.Root.String()} {
		if !strings.Contains(tpl, "twohelixes.com/static/th.js") || !strings.Contains(tpl, thWriteKey) {
			t.Fatal("SSR template missing th.js snippet")
		}
	}
}
