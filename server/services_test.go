package main

import (
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestProxyTextGeneratorSpeech(t *testing.T) {
	const audio = "wav-bytes"
	prevKey := textGeneratorAPIKey
	textGeneratorAPIKey = "tg-secret"
	t.Cleanup(func() { textGeneratorAPIKey = prevKey })

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/generate_speech" {
			t.Fatalf("path = %q, want /api/v1/generate_speech", r.URL.Path)
		}
		if r.Method != http.MethodPost {
			t.Fatalf("method = %q, want POST", r.Method)
		}
		if got := r.Header.Get("secret"); got != "tg-secret" {
			t.Fatalf("secret header = %q, want tg-secret", got)
		}

		var payload map[string]interface{}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatalf("decode payload: %v", err)
		}
		if payload["text"] != "hello speech" {
			t.Fatalf("text = %v, want hello speech", payload["text"])
		}
		if payload["voice"] != "F2" {
			t.Fatalf("voice = %v, want F2", payload["voice"])
		}
		if payload["language"] != "fr" {
			t.Fatalf("language = %v, want fr", payload["language"])
		}
		if payload["speed"] != 1.25 {
			t.Fatalf("speed = %v, want 1.25", payload["speed"])
		}
		if payload["steps"] != float64(6) {
			t.Fatalf("steps = %v, want 6", payload["steps"])
		}

		w.Header().Set("Content-Type", "audio/wav")
		_, _ = w.Write([]byte(audio))
	}))
	defer upstream.Close()

	body, err := proxyTextGeneratorSpeech(ServiceUsageRequest{
		Service:  "tts",
		Input:    "hello speech",
		Voice:    "F2",
		Language: "fr",
		Speed:    1.25,
		Steps:    6,
	}, upstream.URL)
	if err != nil {
		t.Fatalf("proxyTextGeneratorSpeech error: %v", err)
	}

	var result map[string]interface{}
	if err := json.Unmarshal(body, &result); err != nil {
		t.Fatalf("unmarshal result: %v", err)
	}
	if result["audio_base64"] != base64.StdEncoding.EncodeToString([]byte(audio)) {
		t.Fatalf("audio_base64 = %v", result["audio_base64"])
	}
	if result["format"] != "wav" {
		t.Fatalf("format = %v, want wav", result["format"])
	}
	if result["characters"] != float64(len("hello speech")) {
		t.Fatalf("characters = %v, want %d", result["characters"], len("hello speech"))
	}
}

func TestProxyTextGeneratorSpeechDefaults(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var payload map[string]interface{}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatalf("decode payload: %v", err)
		}
		if payload["text"] != "fallback text" {
			t.Fatalf("text = %v, want fallback text", payload["text"])
		}
		if payload["voice"] != "M1" {
			t.Fatalf("voice = %v, want M1", payload["voice"])
		}
		if payload["language"] != "en" {
			t.Fatalf("language = %v, want en", payload["language"])
		}
		if payload["speed"] != float64(1) {
			t.Fatalf("speed = %v, want 1", payload["speed"])
		}
		if payload["steps"] != float64(4) {
			t.Fatalf("steps = %v, want 4", payload["steps"])
		}
		w.Header().Set("Content-Type", "audio/mpeg")
		_, _ = w.Write([]byte("mp3-bytes"))
	}))
	defer upstream.Close()

	body, err := proxyTextGeneratorSpeech(ServiceUsageRequest{Service: "tts", Text: "fallback text"}, upstream.URL)
	if err != nil {
		t.Fatalf("proxyTextGeneratorSpeech error: %v", err)
	}
	var result map[string]interface{}
	if err := json.Unmarshal(body, &result); err != nil {
		t.Fatalf("unmarshal result: %v", err)
	}
	if result["format"] != "mp3" {
		t.Fatalf("format = %v, want mp3", result["format"])
	}
}
