//go:build !diffusionz

package main

import "fmt"

var (
	diffusionzAvailable bool = false
)

func initDiffusionzEngine() {
	// No-op: diffusionz not compiled in
}

func generateImageC(prompt string, width, height, steps, seed int, guidance float64) ([]byte, error) {
	return nil, fmt.Errorf("diffusionz not available: build with -tags diffusionz")
}

func styleTransferC(prompt string, inputImage []byte, strength float64) ([]byte, error) {
	return nil, fmt.Errorf("diffusionz not available: build with -tags diffusionz")
}

func embedPromptC(text string) ([]float32, error) {
	return nil, fmt.Errorf("diffusionz not available: build with -tags diffusionz")
}
