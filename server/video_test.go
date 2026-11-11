package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestProxyOpenPathsVideoSync(t *testing.T) {
	oldKey, oldBase := openPathsAPIKey, openPathsBaseURL
	defer func() { openPathsAPIKey, openPathsBaseURL = oldKey, oldBase }()

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/videos/generations" || r.Method != http.MethodPost {
			t.Fatalf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		if got := r.Header.Get("Authorization"); got != "Bearer test-openpaths-key" {
			t.Fatalf("authorization = %q", got)
		}
		var body map[string]interface{}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body["model"] != "auto-video" || body["image_url"] != "https://cdn.example/still.webp" || body["aspect_ratio"] != "9:16" {
			t.Fatalf("unexpected OpenPaths payload: %#v", body)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"video_url":"https://cdn.example/generated.mp4","output_format":"mp4"}`))
	}))
	defer upstream.Close()

	openPathsAPIKey = "test-openpaths-key"
	openPathsBaseURL = upstream.URL
	result, err := proxyOpenPathsVideo(ServiceUsageRequest{
		Service: "video_generate", Prompt: "subtle camera motion", Model: "auto-video",
		ImageURL: "https://cdn.example/still.webp", AspectRatio: "9:16", Duration: 5,
	})
	if err != nil {
		t.Fatal(err)
	}
	var response openPathsVideoResponse
	if err := json.Unmarshal(result, &response); err != nil {
		t.Fatal(err)
	}
	if response.VideoURL != "https://cdn.example/generated.mp4" {
		t.Fatalf("video_url = %q", response.VideoURL)
	}
}

func TestProxyOpenPathsVideoReturnsQueuedJobWithoutPolling(t *testing.T) {
	oldKey, oldBase := openPathsAPIKey, openPathsBaseURL
	defer func() { openPathsAPIKey, openPathsBaseURL = oldKey, oldBase }()

	requests := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests++
		if r.Method != http.MethodPost || r.URL.Path != "/v1/videos/generations" {
			t.Fatalf("unexpected poll inside paid request: %s %s", r.Method, r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusAccepted)
		_, _ = w.Write([]byte(`{"id":"provider-job-123"}`))
	}))
	defer upstream.Close()

	openPathsAPIKey = "test-openpaths-key"
	openPathsBaseURL = upstream.URL
	result, err := proxyOpenPathsVideo(ServiceUsageRequest{
		Service: "video_generate", Prompt: "camera move", Model: "auto-video",
	})
	if err != nil {
		t.Fatal(err)
	}
	var queued openPathsVideoResponse
	if err := json.Unmarshal(result, &queued); err != nil {
		t.Fatal(err)
	}
	if queued.ID != "provider-job-123" || queued.Status != "queued" {
		t.Fatalf("unexpected queued response: %#v", queued)
	}
	if requests != 1 {
		t.Fatalf("requests = %d, want one POST and no polling", requests)
	}
}

func TestVideoModelValidationAndPricing(t *testing.T) {
	if got := normalizeVideoModel(""); got != "auto-video" {
		t.Fatalf("default model = %q", got)
	}
	if got := getRequestServicePriceUSD(ServiceUsageRequest{Service: "video_generate", Model: "ltx-video"}); got != 0.08 {
		t.Fatalf("ltx-video price = %v", got)
	}
	oldKey := openPathsAPIKey
	openPathsAPIKey = "configured"
	defer func() { openPathsAPIKey = oldKey }()
	if _, err := proxyOpenPathsVideo(ServiceUsageRequest{Service: "video_generate", Model: "not-a-real-model", Prompt: "test"}); err == nil {
		t.Fatal("expected unsupported video model error")
	}
	if _, err := proxyOpenPathsVideo(ServiceUsageRequest{Service: "video_generate", Model: "ltx-2.3-image-to-video", Prompt: "test"}); err == nil {
		t.Fatal("expected missing image_url error")
	}
}

func TestH3DownstreamMarkupUsesIntegerMicros(t *testing.T) {
	if got := h3DownstreamMicros(125_000); got != 150_000 {
		t.Fatalf("marked-up micros = %d, want 150000", got)
	}
	if got := h3DownstreamMicros(1); got != 2 {
		t.Fatalf("small marked-up micros = %d, want 2", got)
	}
	if got := h3DownstreamMicros(0); got != 0 {
		t.Fatalf("zero marked-up micros = %d", got)
	}
}

func TestNormalizeH3VideoRequestPreservesFalseSettings(t *testing.T) {
	no := false
	req := ServiceUsageRequest{
		Service: "h3_video", Prompt: " loop a waterfall ", ImageURL: "https://cdn.example/start.webp",
		Loop: true, IncludeAudio: &no, Structured: &no,
	}
	if err := normalizeH3VideoRequest(&req); err != nil {
		t.Fatal(err)
	}
	input := appNZH3Input(req)
	if input["first_frame"] != req.ImageURL || input["duration"] != 5 || input["steps"] != 20 {
		t.Fatalf("unexpected normalized input: %#v", input)
	}
	if input["include_audio"] != false || input["structured_prompt"] != false {
		t.Fatalf("explicit false settings lost: %#v", input)
	}
	if err := normalizeH3VideoRequest(&ServiceUsageRequest{Prompt: "test", Loop: true}); err == nil {
		t.Fatal("expected loop without a first frame to fail")
	}
}

func TestCallAppNZH3UsesBearerAndSurfacesLicenseGate(t *testing.T) {
	requests := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests++
		if r.Header.Get("Authorization") != "Bearer app-test-key" {
			t.Fatalf("authorization = %q", r.Header.Get("Authorization"))
		}
		w.Header().Set("Content-Type", "application/json")
		if requests == 1 {
			w.WriteHeader(http.StatusCreated)
			_, _ = w.Write([]byte(`{"success":true,"prediction":{"id":"pred-1","status":"starting"}}`))
			return
		}
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"success":false,"error":"H3 launch is awaiting explicit MiniMax license acceptance"}`))
	}))
	defer upstream.Close()
	t.Setenv("APPNZ_BASE_URL", upstream.URL)
	t.Setenv("APPNZ_API_KEY", "app-test-key")

	envelope, status, err := callAppNZH3(http.MethodPost, "/api/cogs/run", map[string]interface{}{"template": "minimax-h3"})
	if err != nil || status != http.StatusCreated || envelope.Prediction.ID != "pred-1" {
		t.Fatalf("submit status=%d envelope=%#v err=%v", status, envelope, err)
	}
	_, status, err = callAppNZH3(http.MethodPost, "/api/cogs/run", map[string]interface{}{"template": "minimax-h3"})
	if status != http.StatusBadRequest || err == nil || !strings.Contains(err.Error(), "license acceptance") {
		t.Fatalf("license status=%d err=%v", status, err)
	}
}

func TestVideoCatalogWired(t *testing.T) {
	if len(videoCatalog) < 30 {
		t.Fatalf("catalog too small: %d", len(videoCatalog))
	}
	for _, e := range videoCatalog {
		if !allowedVideoModels[e.ID] || videoModelPricesUSD[e.ID] <= 0 {
			t.Fatalf("%s not wired", e.ID)
		}
	}
	if !videoModelNeedsImage("kling-4.0-image-to-video") || videoModelNeedsImage("kling-4.0-text-to-video") {
		t.Fatal("i2v detection wrong")
	}
}

func TestImageCatalogPricing(t *testing.T) {
	if len(imageCatalog) < 18 {
		t.Fatalf("image catalog small: %d", len(imageCatalog))
	}
	if p := getRequestServicePriceUSD(ServiceUsageRequest{Service: "image_generate", Model: "gpt-image-2"}); p < 0.2 {
		t.Fatalf("price %v", p)
	}
}

func TestChatCatalogPricing(t *testing.T) {
	if len(chatCatalog) < 25 {
		t.Fatalf("chat catalog small: %d", len(chatCatalog))
	}
	if getRequestServicePriceUSD(ServiceUsageRequest{Service: "chat_generate", Model: "claude-fable-5"}) <= getRequestServicePriceUSD(ServiceUsageRequest{Service: "chat_generate", Model: "gpt-4o-mini"}) {
		t.Fatal("chat pricing not model dependent")
	}
}

func TestOpenPathsServicesHaveBackends(t *testing.T) {
	for _, s := range []string{"video_generate", "image_generate", "chat_generate"} {
		if serviceBackends[s] == "" {
			t.Fatalf("%s has no backend", s)
		}
	}
}
