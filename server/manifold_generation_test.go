package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestNormalizeGenerationRequestDefaultsToAV1(t *testing.T) {
	req := createGenerationRequest{Prompt: "A glass hummingbird crosses a moonlit garden", OutputFormat: "mp4"}
	if err := normalizeGenerationRequest(&req); err != nil {
		t.Fatalf("normalizeGenerationRequest: %v", err)
	}
	if req.OutputFormat != "webm-av1" {
		t.Fatalf("output format = %q, want webm-av1", req.OutputFormat)
	}
	if req.Size != "preview" || req.Duration != 5 || req.NumSteps != 20 || req.AspectRatio != "16:9" {
		t.Fatalf("unexpected defaults: %+v", req)
	}
}

func TestNormalizeGenerationRequestRejectsUnsafeInputs(t *testing.T) {
	tests := []createGenerationRequest{
		{Prompt: "x"},
		{Prompt: "valid prompt", Duration: 61},
		{Prompt: "valid prompt", AspectRatio: "4:3"},
		{Prompt: "valid prompt", FirstFrame: "file:///tmp/frame.png"},
	}
	for _, req := range tests {
		if err := normalizeGenerationRequest(&req); err == nil {
			t.Fatalf("expected validation error for %+v", req)
		}
	}
}

func TestManifoldJSONKeepsCredentialServerSide(t *testing.T) {
	var receivedAuth string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedAuth = r.Header.Get("Authorization")
		body, _ := io.ReadAll(r.Body)
		var payload map[string]interface{}
		if json.Unmarshal(body, &payload) != nil || payload["service"] != "video" {
			t.Fatalf("unexpected payload: %s", body)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusAccepted)
		_, _ = w.Write([]byte(`{"result":{"job_id":"video_test","status":"queued"}}`))
	}))
	defer server.Close()
	t.Setenv("MANIFOLDGEN_ORIGIN", server.URL)
	t.Setenv("MANIFOLDGEN_API_KEY", "server-secret")

	status, body, err := manifoldJSON(http.MethodPost, "/api/service", map[string]interface{}{"service": "video"})
	if err != nil || status != http.StatusAccepted {
		t.Fatalf("manifoldJSON status=%d err=%v body=%s", status, err, body)
	}
	if receivedAuth != "Bearer server-secret" {
		t.Fatalf("authorization header = %q", receivedAuth)
	}
}

func TestFeaturedVideosClampsOversizedUpstreamPages(t *testing.T) {
	var requestedLimit string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestedLimit = r.URL.Query().Get("limit")
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"results":[],"count":0}`))
	}))
	defer server.Close()
	t.Setenv("MANIFOLDGEN_ORIGIN", server.URL)

	if _, err := getManifoldFeaturedVideos(60); err != nil {
		t.Fatalf("getManifoldFeaturedVideos: %v", err)
	}
	if requestedLimit != "18" {
		t.Fatalf("upstream limit = %q, want 18", requestedLimit)
	}
}

func TestGenerationQueueEndToEnd(t *testing.T) {
	upstreamID := fmt.Sprintf("video_e2e_%d", time.Now().UnixNano())
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == http.MethodPost && r.URL.Path == "/api/service":
			w.WriteHeader(http.StatusAccepted)
			_, _ = fmt.Fprintf(w, `{"result":{"job_id":%q,"status":"queued"}}`, upstreamID)
		case r.Method == http.MethodGet && r.URL.Path == "/api/video-jobs/"+upstreamID:
			_, _ = fmt.Fprintf(w, `{"job":{"job_id":%q,"status":"completed","result":{"video_url":"https://cdn.example/e2e.webm","codec":"av1"}}}`, upstreamID)
		case r.Method == http.MethodGet && r.URL.Path == "/api/videos/featured":
			_, _ = w.Write([]byte(`{"results":[],"count":0}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer upstream.Close()
	t.Setenv("MANIFOLDGEN_ORIGIN", upstream.URL)
	t.Setenv("MANIFOLDGEN_API_KEY", "e2e-server-key")
	t.Setenv("MANIFOLDGEN_DAILY_JOB_LIMIT", "10")

	wallet := "GenerationE2E_" + time.Now().Format("150405.000000000")
	status, auth := doPost(t, "/api/auth/wallet", map[string]string{"wallet_address": wallet})
	if status != http.StatusOK {
		t.Fatalf("wallet auth status=%d body=%v", status, auth)
	}
	apiKey, _ := auth["api_key"].(string)
	status, created := doPost(t, "/api/generations", map[string]interface{}{
		"prompt": "A glass whale swims through a flooded library",
	}, "Authorization", "Bearer "+apiKey)
	if status != http.StatusAccepted {
		t.Fatalf("create status=%d body=%v", status, created)
	}
	job, _ := created["job"].(map[string]interface{})
	jobID, _ := job["job_id"].(string)
	if jobID == "" {
		t.Fatalf("missing local job ID: %v", created)
	}

	request, _ := http.NewRequest(http.MethodGet, baseURL()+"/api/generations/"+jobID, nil)
	request.Header.Set("Authorization", "Bearer "+apiKey)
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("poll generation: %v", err)
	}
	var polled map[string]interface{}
	_ = json.NewDecoder(response.Body).Decode(&polled)
	response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("poll status=%d body=%v", response.StatusCode, polled)
	}
	polledJob, _ := polled["job"].(map[string]interface{})
	if polledJob["status"] != "completed" {
		t.Fatalf("polled job not completed: %v", polledJob)
	}

	status, published := doPost(t, "/api/generations/"+jobID+"/publish", map[string]bool{"public": true}, "Authorization", "Bearer "+apiKey)
	if status != http.StatusOK {
		t.Fatalf("publish status=%d body=%v", status, published)
	}
	status, gallery := doGet(t, "/api/videos?limit=10")
	if status != http.StatusOK {
		t.Fatalf("gallery status=%d body=%v", status, gallery)
	}
	videos, _ := gallery["videos"].([]interface{})
	found := false
	for _, item := range videos {
		video, _ := item.(map[string]interface{})
		if video["job_id"] == jobID {
			found = true
		}
	}
	if !found {
		t.Fatalf("published job absent from video gallery: %v", gallery)
	}
}
