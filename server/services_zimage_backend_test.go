package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestProxyZImageOpenAIBackendUsesEmbeddedRouteAndNormalizesResponse(t *testing.T) {
	t.Setenv("ZIMAGE_BACKEND_STYLE", "openai")

	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/images/generations" {
			t.Errorf("path = %q, want embedded image route", r.URL.Path)
			return
		}
		var body map[string]interface{}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
			return
		}
		if body["size"] != "512x384" || body["response_format"] != "b64_json" {
			t.Errorf("unexpected OpenAI image payload: %#v", body)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"format":"webp","data":[{"b64_json":"aW1hZ2U="}]}`))
	}))
	defer backend.Close()

	result, err := proxyToBackend(ServiceUsageRequest{
		Service: "zimage", Prompt: "route regression", Width: 512, Height: 384,
		NumSteps: 8, Seed: 42,
	}, backend.URL)
	if err != nil {
		t.Fatal(err)
	}
	var normalized map[string]interface{}
	if err := json.Unmarshal(result, &normalized); err != nil {
		t.Fatal(err)
	}
	if normalized["image_base64"] != "aW1hZ2U=" || normalized["width"] != float64(512) {
		t.Fatalf("unexpected normalized image response: %#v", normalized)
	}
}

func TestProxyZImageOpenAIBackendRetriesTransientManagedGPUCapacity(t *testing.T) {
	t.Setenv("ZIMAGE_BACKEND_STYLE", "openai")
	t.Setenv("ZIMAGE_BACKEND_CAPACITY_RETRY_GRACE", "1s")
	t.Setenv("ZIMAGE_BACKEND_CAPACITY_RETRY_INTERVAL", "1ms")

	attempts := 0
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attempts++
		if tier := r.Header.Get("X-Omniserve-Tier"); tier != "paid" {
			t.Errorf("X-Omniserve-Tier = %q, want paid", tier)
		}
		w.Header().Set("Content-Type", "application/json")
		if attempts == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = w.Write([]byte(`{"error":{"message":"image generation needs at least 4096 MB free GPU memory; managed GPU capacity is busy","type":"invalid_request_error"}}`))
			return
		}
		_, _ = w.Write([]byte(`{"format":"webp","data":[{"b64_json":"cmVjb3ZlcmVk"}]}`))
	}))
	defer backend.Close()

	result, err := proxyToBackend(ServiceUsageRequest{
		Service: "zimage", Prompt: "capacity recovery regression", Width: 512, Height: 512,
		NumSteps: 8,
	}, backend.URL)
	if err != nil {
		t.Fatal(err)
	}
	if attempts != 2 {
		t.Fatalf("backend attempts = %d, want 2", attempts)
	}
	var normalized map[string]interface{}
	if err := json.Unmarshal(result, &normalized); err != nil {
		t.Fatal(err)
	}
	if normalized["image_base64"] != "cmVjb3ZlcmVk" {
		t.Fatalf("unexpected normalized image response: %#v", normalized)
	}
}
