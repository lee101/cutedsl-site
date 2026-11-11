package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestOpenPathsProxiesAgainstMock(t *testing.T) {
	var gotPaths []string
	var gotBodies []map[string]interface{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer testkey" {
			w.WriteHeader(401)
			return
		}
		b, _ := io.ReadAll(r.Body)
		var m map[string]interface{}
		json.Unmarshal(b, &m)
		gotPaths = append(gotPaths, r.URL.Path)
		gotBodies = append(gotBodies, m)
		switch r.URL.Path {
		case "/v1/chat/completions":
			w.Write([]byte(`{"choices":[{"message":{"content":"ok"}}]}`))
		case "/v1/images/generations":
			w.Write([]byte(`{"data":[{"url":"https://x/y.png"}]}`))
		case "/v1/videos/generations":
			w.WriteHeader(202)
			w.Write([]byte(`{"id":"vid_1","status":"queued"}`))
		}
	}))
	defer srv.Close()
	oldKey, oldBase := openPathsAPIKey, openPathsBaseURL
	openPathsAPIKey, openPathsBaseURL = "testkey", srv.URL
	defer func() { openPathsAPIKey, openPathsBaseURL = oldKey, oldBase }()

	out, err := proxyOpenPathsChat(ServiceUsageRequest{Service: "chat_generate", Model: "gpt-4o-mini", Prompt: "hi"})
	if err != nil || !strings.Contains(string(out), `"text":"ok"`) {
		t.Fatalf("chat: %s %v", out, err)
	}
	out, err = proxyOpenPathsImage(ServiceUsageRequest{Service: "image_generate", Model: "klein", Prompt: "cat", Width: 1024, Height: 576})
	if err != nil || !strings.Contains(string(out), `"image_url":"https://x/y.png"`) {
		t.Fatalf("image: %s %v", out, err)
	}
	out, err = proxyOpenPathsVideo(ServiceUsageRequest{Service: "video_generate", Model: "kling-4.0-image-to-video", Prompt: "pan", ImageURL: "https://x/i.png"})
	if err != nil || !strings.Contains(string(out), "vid_1") {
		t.Fatalf("video: %s %v", out, err)
	}
	out, err = proxyOpenPathsVideo(ServiceUsageRequest{Service: "video_generate", Model: "h3-control-video", Prompt: "anime", VideoURL: "https://x/v.mp4"})
	if err != nil || gotBodies[3]["video_url"] != "https://x/v.mp4" {
		t.Fatalf("v2v: %s %v %v", out, err, gotBodies)
	}
	if _, err = proxyOpenPathsVideo(ServiceUsageRequest{Service: "video_generate", Model: "h3-control-video", Prompt: "x"}); err == nil {
		t.Fatal("v2v without video_url must fail")
	}
	if _, err = proxyOpenPathsVideo(ServiceUsageRequest{Service: "video_generate", Model: "kling-4.0-image-to-video", Prompt: "x"}); err == nil {
		t.Fatal("i2v without image must fail")
	}
	if len(gotPaths) != 4 {
		t.Fatalf("paths %v", gotPaths)
	}
}
