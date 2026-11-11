package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestRA2Upstream402IsPaywallNot502(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Subscribe-URL", "https://gateway/subscribe")
		w.WriteHeader(402)
		w.Write([]byte(`{"error":{"code":"subscription_required","message":"subscribe please","subscribe_url":"https://gateway/subscribe"}}`))
	}))
	defer srv.Close()
	_, err := proxyToRA2(ServiceUsageRequest{Service: "ra2-edit", Prompt: "x", ImageBase64: "aGk="}, srv.URL, "")
	pe, ok := asUpstreamPaywall(err)
	if !ok || pe.Status != 402 || pe.Message != "subscribe please" {
		t.Fatalf("got %v", err)
	}
}
