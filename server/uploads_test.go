package main

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestValidateLoraTrainingURLsAllowsOnlyUploadedR2Assets(t *testing.T) {
	oldHost, oldPrefix := r2PublicHost, r2PathPrefix
	r2PublicHost, r2PathPrefix = "appstatic.app.nz", "cutedsl/uploads"
	t.Cleanup(func() { r2PublicHost, r2PathPrefix = oldHost, oldPrefix })

	body, _ := json.Marshal(map[string]any{
		"image_urls": []string{"https://appstatic.app.nz/cutedsl/uploads/user/data/tile.webp"},
	})
	if err := validateLoraTrainingURLs(body); err != nil {
		t.Fatalf("valid upload rejected: %v", err)
	}

	for _, rawURL := range []string{
		"http://appstatic.app.nz/cutedsl/uploads/user/data/tile.webp",
		"https://127.0.0.1/cutedsl/uploads/user/data/tile.webp",
		"https://appstatic.app.nz/private/tile.webp",
		"https://appstatic.app.nz.evil.example/cutedsl/uploads/user/data/tile.webp",
	} {
		body, _ := json.Marshal(map[string]any{"image_urls": []string{rawURL}})
		if err := validateLoraTrainingURLs(body); err == nil || !strings.Contains(err.Error(), "uploaded dataset assets") {
			t.Fatalf("unsafe URL %q err=%v", rawURL, err)
		}
	}
}

func TestValidateLoraTrainingURLsBoundsDatasetSize(t *testing.T) {
	oldHost, oldPrefix := r2PublicHost, r2PathPrefix
	r2PublicHost, r2PathPrefix = "appstatic.app.nz", "cutedsl/uploads"
	t.Cleanup(func() { r2PublicHost, r2PathPrefix = oldHost, oldPrefix })

	urls := make([]string, 101)
	for i := range urls {
		urls[i] = "https://appstatic.app.nz/cutedsl/uploads/user/data/tile.webp"
	}
	body, _ := json.Marshal(map[string]any{"image_urls": urls})
	if err := validateLoraTrainingURLs(body); err == nil || !strings.Contains(err.Error(), "1-100") {
		t.Fatalf("oversized dataset err=%v", err)
	}
}
