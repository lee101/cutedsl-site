package main

import (
	"os"
	"strings"
	"testing"
)

func TestLiveOpenPaths(t *testing.T) {
	key := os.Getenv("LIVE_OPENPATHS_KEY")
	if key == "" {
		t.Skip("LIVE_OPENPATHS_KEY not set")
	}
	openPathsAPIKey, openPathsBaseURL = key, "http://127.0.0.1:8092"
	out, err := proxyOpenPathsChat(ServiceUsageRequest{Model: "openpaths/auto-cheap", Prompt: "say ok"})
	if err != nil || !strings.Contains(string(out), `"text"`) {
		t.Fatalf("chat %s %v", out, err)
	}
	out, err = proxyOpenPathsImage(ServiceUsageRequest{Model: "klein", Prompt: "a red fox"})
	if err != nil || !strings.Contains(string(out), "image_url") {
		t.Fatalf("image %s %v", out, err)
	}
	out, err = proxyOpenPathsVideo(ServiceUsageRequest{Model: "p-video", Prompt: "a fox running through snow", Duration: 5})
	if err != nil || !strings.Contains(string(out), "video_url") {
		t.Fatalf("video %s %v", out, err)
	}
	t.Logf("video: %s", out)
}
