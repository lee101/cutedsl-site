package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

// ra2MockBackend records the translated request and replies with the
// omniserve-native contract shape.
type ra2MockBackend struct {
	path   string
	auth   string
	apiKey string
	tier   string
	body   ra2Request
	status int
	reply  string
}

func newRA2Mock(t *testing.T, mock *ra2MockBackend) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mock.path = r.URL.Path
		mock.auth = r.Header.Get("Authorization")
		mock.apiKey = r.Header.Get("X-API-Key")
		mock.tier = r.Header.Get("X-Omniserve-Tier")
		if err := json.NewDecoder(r.Body).Decode(&mock.body); err != nil {
			t.Errorf("mock backend could not decode request: %v", err)
		}
		if mock.status != 0 {
			w.WriteHeader(mock.status)
			_, _ = w.Write([]byte(mock.reply))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		if mock.reply == "" {
			mock.reply = `{"data":[{"b64_json":"QUJD","seed":7,"inference_time_ms":1234,"format":"webp"}],"model":"ra2","format":"webp"}`
		}
		_, _ = w.Write([]byte(mock.reply))
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestRA2TranslationDefaults(t *testing.T) {
	mock := &ra2MockBackend{}
	srv := newRA2Mock(t, mock)

	out, err := proxyToRA2(ServiceUsageRequest{Service: "ra2", Prompt: "a cute cat"}, srv.URL, "s3cret")
	if err != nil {
		t.Fatalf("proxyToRA2: %v", err)
	}

	if mock.path != "/v1/images/generations" {
		t.Fatalf("expected /v1/images/generations, got %s", mock.path)
	}
	if mock.auth != "Bearer s3cret" {
		t.Fatalf("expected bearer secret, got %q", mock.auth)
	}
	if mock.apiKey != "s3cret" {
		t.Fatalf("expected X-API-Key secret, got %q", mock.apiKey)
	}
	if mock.tier != "paid" {
		t.Fatalf("expected X-Omniserve-Tier paid, got %q", mock.tier)
	}

	want := ra2Request{
		Prompt: "a cute cat", Width: 1024, Height: 1024, Steps: 20,
		GuidanceScale: 1.0, OutputFormat: "webp", N: 1, Teleport: true,
	}
	if mock.body != want {
		t.Fatalf("unexpected translated request:\n got %+v\nwant %+v", mock.body, want)
	}

	var got map[string]interface{}
	if err := json.Unmarshal(out, &got); err != nil {
		t.Fatalf("decode normalised response: %v", err)
	}
	if got["engine"] != "ra2" || got["format"] != "webp" {
		t.Fatalf("expected engine=ra2 format=webp, got %v", got)
	}
}

func TestRA2TranslationExplicitFields(t *testing.T) {
	mock := &ra2MockBackend{}
	srv := newRA2Mock(t, mock)

	_, err := proxyToRA2(ServiceUsageRequest{
		Service:        "ra2",
		Prompt:         "cinematic dragon",
		NegativePrompt: "blurry, watermark",
		Width:          1000,
		Height:         700,
		NumSteps:       30,
		Seed:           42,
		Guidance:       1.5,
	}, srv.URL, "")
	if err != nil {
		t.Fatalf("proxyToRA2: %v", err)
	}

	want := ra2Request{
		Prompt: "cinematic dragon", NegativePrompt: "blurry, watermark",
		Width: 992, Height: 672, Steps: 30, Seed: 42, GuidanceScale: 1.5,
		OutputFormat: "webp", N: 1, Teleport: true,
	}
	if mock.body != want {
		t.Fatalf("unexpected translated request:\n got %+v\nwant %+v", mock.body, want)
	}
	// Secret unset must not send auth headers.
	if mock.auth != "" || mock.apiKey != "" {
		t.Fatalf("expected no auth headers, got %q / %q", mock.auth, mock.apiKey)
	}
}

func TestRA2EditTranslation(t *testing.T) {
	mock := &ra2MockBackend{}
	srv := newRA2Mock(t, mock)

	_, err := proxyToRA2(ServiceUsageRequest{
		Service:     "ra2-edit",
		Prompt:      "watercolor style",
		ImageBase64: "c291cmNl",
		Width:       512,
		Height:      512,
	}, srv.URL, "")
	if err != nil {
		t.Fatalf("proxyToRA2: %v", err)
	}

	if mock.path != "/v1/images/edits" {
		t.Fatalf("expected /v1/images/edits, got %s", mock.path)
	}
	if mock.body.ImageBase64 != "c291cmNl" {
		t.Fatalf("expected image_base64 to be forwarded, got %q", mock.body.ImageBase64)
	}
	if mock.body.Width != 512 || mock.body.Height != 512 {
		t.Fatalf("expected 512x512, got %dx%d", mock.body.Width, mock.body.Height)
	}
}

func TestRA2ResponseNormalisation(t *testing.T) {
	mock := &ra2MockBackend{
		reply: `{"data":[{"b64_json":"aW1n","seed":99,"inference_time_ms":4321,"format":"webp"}],"model":"ra2-art","format":"webp"}`,
	}
	srv := newRA2Mock(t, mock)

	out, err := proxyToRA2(ServiceUsageRequest{Service: "ra2", Prompt: "x", Width: 768, Height: 512}, srv.URL, "")
	if err != nil {
		t.Fatalf("proxyToRA2: %v", err)
	}

	var got map[string]interface{}
	if err := json.Unmarshal(out, &got); err != nil {
		t.Fatalf("decode normalised response: %v", err)
	}
	if got["image_base64"] != "aW1n" {
		t.Fatalf("expected image_base64 from b64_json, got %v", got["image_base64"])
	}
	if got["width"].(float64) != 768 || got["height"].(float64) != 512 {
		t.Fatalf("expected 768x512, got %vx%v", got["width"], got["height"])
	}
	if got["format"] != "webp" || got["engine"] != "ra2" {
		t.Fatalf("expected format=webp engine=ra2, got %v", got)
	}
	if got["seed"].(float64) != 99 || got["inference_time_ms"].(float64) != 4321 {
		t.Fatalf("expected seed/time passthrough, got %v", got)
	}
	if got["model"] != "ra2-art" {
		t.Fatalf("expected model passthrough, got %v", got["model"])
	}
}

func TestRA2BackendError(t *testing.T) {
	mock := &ra2MockBackend{status: 500, reply: "engine exploded"}
	srv := newRA2Mock(t, mock)

	if _, err := proxyToRA2(ServiceUsageRequest{Service: "ra2", Prompt: "x"}, srv.URL, ""); err == nil {
		t.Fatal("expected error on 500 backend response")
	}
}

func TestRA2EmptyImageResponse(t *testing.T) {
	mock := &ra2MockBackend{reply: `{"data":[],"format":"webp"}`}
	srv := newRA2Mock(t, mock)

	if _, err := proxyToRA2(ServiceUsageRequest{Service: "ra2", Prompt: "x"}, srv.URL, ""); err == nil {
		t.Fatal("expected error when backend returns no image")
	}
}

func TestRA2RegisteredServices(t *testing.T) {
	for _, svc := range []string{"ra2", "ra2-edit"} {
		if _, ok := servicePricesUSD[svc]; !ok {
			t.Fatalf("service %s missing from pricing", svc)
		}
		if !firstPartyServices[svc] {
			t.Fatalf("service %s should be first-party", svc)
		}
		if serviceBackends[svc] == "" {
			t.Fatalf("service %s has no backend configured", svc)
		}
	}
	// ra2-edit is always priced with ra2.
	if servicePricesUSD["ra2-edit"] != servicePricesUSD["ra2"] {
		t.Fatalf("expected ra2-edit price %v to match ra2 %v", servicePricesUSD["ra2-edit"], servicePricesUSD["ra2"])
	}
}

func TestDefaultServiceName(t *testing.T) {
	if got := defaultServiceName(); got != "ra2" {
		t.Fatalf("expected ra2 default, got %s", got)
	}
	t.Setenv("RA2_DEFAULT", "0")
	if got := defaultServiceName(); got != "zimage" {
		t.Fatalf("expected zimage when RA2_DEFAULT=0, got %s", got)
	}
}
