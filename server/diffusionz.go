//go:build cgo && diffusionz

package main

/*
#cgo CFLAGS: -I/nvme0n1-disk/code/diffusionz/csrc/include
#cgo LDFLAGS: -L/nvme0n1-disk/code/diffusionz/csrc/build -ldiffusionz_bridge -Wl,-rpath,/nvme0n1-disk/code/diffusionz/csrc/build
#cgo LDFLAGS: -L/home/administrator/.local/share/uv/python/cpython-3.13.9-linux-x86_64-gnu/lib -lpython3.13 -Wl,-rpath,/home/administrator/.local/share/uv/python/cpython-3.13.9-linux-x86_64-gnu/lib -ldl -lm
#include "diffusionz_c_api.h"
#include <stdlib.h>
*/
import "C"

import (
	"fmt"
	"log"
	"os"
	"strings"
	"unsafe"
)

var (
	diffusionzEngine    *C.diffusionz_engine_t
	diffusionzAvailable bool
)

const diffusionzErrBufSize = 4096
const diffusionzEmbedDim = 768 // CLIP embedding dimension

func initDiffusionzEngine() {
	modelRoot := os.Getenv("DIFFUSIONZ_MODEL_ROOT")
	if modelRoot == "" {
		log.Printf("DIFFUSIONZ_MODEL_ROOT not set, diffusionz engine disabled")
		return
	}

	device := os.Getenv("DIFFUSIONZ_DEVICE")
	if device == "" {
		device = "cuda"
	}

	errBuf := make([]byte, diffusionzErrBufSize)
	cModelRoot := C.CString(modelRoot)
	cDevice := C.CString(device)
	defer C.free(unsafe.Pointer(cModelRoot))
	defer C.free(unsafe.Pointer(cDevice))

	engine := C.diffusionz_engine_create(
		cModelRoot,
		cDevice,
		(*C.char)(unsafe.Pointer(&errBuf[0])),
		C.size_t(len(errBuf)),
	)
	if engine == nil {
		errMsg := strings.TrimRight(string(errBuf), "\x00")
		log.Printf("Failed to create diffusionz engine: %s", errMsg)
		return
	}

	diffusionzEngine = engine
	diffusionzAvailable = true
	log.Printf("Diffusionz engine initialized (model_root=%s, device=%s)", modelRoot, device)
}

// generateImageC generates an image via the diffusionz C API and returns WebP bytes.
func generateImageC(prompt string, width, height, steps, seed int, guidance float64) ([]byte, error) {
	if diffusionzEngine == nil {
		return nil, fmt.Errorf("diffusionz engine not initialized")
	}

	cPrompt := C.CString(prompt)
	defer C.free(unsafe.Pointer(cPrompt))

	req := C.diffusionz_request_t{
		prompt:         cPrompt,
		width:          C.int32_t(width),
		height:         C.int32_t(height),
		steps:          C.int32_t(steps),
		seed:           C.int32_t(seed),
		guidance_scale: C.float(guidance),
	}

	var output C.diffusionz_image_t
	errBuf := make([]byte, diffusionzErrBufSize)

	rc := C.diffusionz_generate(
		diffusionzEngine,
		&req,
		&output,
		(*C.char)(unsafe.Pointer(&errBuf[0])),
		C.size_t(len(errBuf)),
	)
	if rc != 0 {
		errMsg := strings.TrimRight(string(errBuf), "\x00")
		return nil, fmt.Errorf("diffusionz_generate failed: %s", errMsg)
	}
	defer C.diffusionz_image_free(&output)

	if output.data == nil || output.size == 0 {
		return nil, fmt.Errorf("diffusionz_generate returned empty image")
	}

	// Copy output bytes to Go-managed memory
	size := int(output.size)
	result := make([]byte, size)
	copy(result, unsafe.Slice((*byte)(unsafe.Pointer(output.data)), size))

	return result, nil
}

// styleTransferC performs style transfer via the diffusionz C API.
func styleTransferC(prompt string, inputImage []byte, strength float64) ([]byte, error) {
	if diffusionzEngine == nil {
		return nil, fmt.Errorf("diffusionz engine not initialized")
	}

	cPrompt := C.CString(prompt)
	defer C.free(unsafe.Pointer(cPrompt))

	req := C.diffusionz_request_t{
		prompt:   cPrompt,
		strength: C.float(strength),
	}

	var output C.diffusionz_image_t
	errBuf := make([]byte, diffusionzErrBufSize)

	rc := C.diffusionz_style_transfer(
		diffusionzEngine,
		&req,
		(*C.uint8_t)(unsafe.Pointer(&inputImage[0])),
		C.size_t(len(inputImage)),
		&output,
		(*C.char)(unsafe.Pointer(&errBuf[0])),
		C.size_t(len(errBuf)),
	)
	if rc != 0 {
		errMsg := strings.TrimRight(string(errBuf), "\x00")
		return nil, fmt.Errorf("diffusionz_style_transfer failed: %s", errMsg)
	}
	defer C.diffusionz_image_free(&output)

	if output.data == nil || output.size == 0 {
		return nil, fmt.Errorf("diffusionz_style_transfer returned empty image")
	}

	size := int(output.size)
	result := make([]byte, size)
	copy(result, unsafe.Slice((*byte)(unsafe.Pointer(output.data)), size))

	return result, nil
}

// embedPromptC embeds a text prompt via the diffusionz C API.
func embedPromptC(text string) ([]float32, error) {
	if diffusionzEngine == nil {
		return nil, fmt.Errorf("diffusionz engine not initialized")
	}

	cText := C.CString(text)
	defer C.free(unsafe.Pointer(cText))

	embedding := make([]float32, diffusionzEmbedDim)
	errBuf := make([]byte, diffusionzErrBufSize)

	rc := C.diffusionz_embed_prompt(
		diffusionzEngine,
		cText,
		(*C.float)(unsafe.Pointer(&embedding[0])),
		C.size_t(len(embedding)),
		(*C.char)(unsafe.Pointer(&errBuf[0])),
		C.size_t(len(errBuf)),
	)
	if rc != 0 {
		errMsg := strings.TrimRight(string(errBuf), "\x00")
		return nil, fmt.Errorf("diffusionz_embed_prompt failed: %s", errMsg)
	}

	return embedding, nil
}
