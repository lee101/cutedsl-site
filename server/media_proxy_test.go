package main

import "testing"

func TestAllowedMediaProxyURL(t *testing.T) {
	allowed := []string{
		"https://manifoldgenstatic.manifoldgen.com/gallery/account/videos/clip.webm",
		"https://appstatic.app.nz/cutedsl/static/images/art.webp",
		"https://cutedsl.cc/images/full/art.webp",
	}
	for _, candidate := range allowed {
		if _, err := allowedMediaProxyURL(candidate); err != nil {
			t.Errorf("allowedMediaProxyURL(%q): %v", candidate, err)
		}
	}
	blocked := []string{
		"http://manifoldgenstatic.manifoldgen.com/video.webm",
		"https://manifoldgenstatic.manifoldgen.com.evil.test/video.webm",
		"https://127.0.0.1/internal",
		"https://user:pass@cutedsl.cc/image.webp",
		"https://cutedsl.cc:8443/image.webp",
		"https://cutedsl.cc/",
		"https://cutedsl.cc/image.webp?redirect=https://127.0.0.1",
	}
	for _, candidate := range blocked {
		if _, err := allowedMediaProxyURL(candidate); err == nil {
			t.Errorf("allowedMediaProxyURL(%q) unexpectedly succeeded", candidate)
		}
	}
}
