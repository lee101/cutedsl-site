package main

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/valyala/fasthttp"
)

var imageModelPricesUSD = map[string]float64{}

func init() {
	for _, e := range imageCatalog {
		imageModelPricesUSD[e.ID] = e.PriceUSD
	}
}

func handleImageModels(ctx *fasthttp.RequestCtx) {
	ctx.SetContentType("application/json")
	ctx.Response.Header.Set("Cache-Control", "public, max-age=300")
	b, _ := json.Marshal(map[string]interface{}{"models": imageCatalog})
	ctx.SetBody(b)
}

func proxyOpenPathsImage(req ServiceUsageRequest) ([]byte, error) {
	model := strings.TrimSpace(strings.ToLower(req.Model))
	if model == "" {
		model = "flux-schnell"
	}
	if _, ok := imageModelPricesUSD[model]; !ok {
		return nil, fmt.Errorf("unsupported image model %q", model)
	}
	if strings.TrimSpace(req.Prompt) == "" {
		return nil, fmt.Errorf("image prompt is required")
	}
	if openPathsAPIKey == "" {
		return nil, fmt.Errorf("image_generate requires OpenPaths to be configured")
	}
	payload := map[string]interface{}{"model": model, "prompt": strings.TrimSpace(req.Prompt), "n": 1}
	if req.Size != "" {
		payload["size"] = req.Size
	} else if req.Width > 0 && req.Height > 0 {
		payload["size"] = fmt.Sprintf("%dx%d", req.Width, req.Height)
	}
	body, _ := json.Marshal(payload)
	out, _, err := callOpenPathsVideo("POST", openPathsBaseURL+"/v1/images/generations", body)
	if err != nil {
		return nil, err
	}
	var parsed struct {
		Data []struct {
			URL     string `json:"url"`
			B64JSON string `json:"b64_json"`
		} `json:"data"`
	}
	if json.Unmarshal(out, &parsed) != nil || len(parsed.Data) == 0 {
		return out, nil
	}
	res := map[string]interface{}{"model": model}
	if parsed.Data[0].URL != "" {
		res["image_url"] = parsed.Data[0].URL
	} else if parsed.Data[0].B64JSON != "" {
		res["image_base64"] = parsed.Data[0].B64JSON
	}
	return json.Marshal(res)
}
