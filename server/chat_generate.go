package main

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/valyala/fasthttp"
)

const chatMaxPromptChars = 8000
const chatMaxOutputTokens = 1000

var chatModelPricesUSD = map[string]float64{}

func init() {
	for _, e := range chatCatalog {
		chatModelPricesUSD[e.ID] = e.PriceUSD
	}
}

func handleChatModels(ctx *fasthttp.RequestCtx) {
	ctx.SetContentType("application/json")
	ctx.Response.Header.Set("Cache-Control", "public, max-age=300")
	b, _ := json.Marshal(map[string]interface{}{"models": chatCatalog})
	ctx.SetBody(b)
}

func proxyOpenPathsChat(req ServiceUsageRequest) ([]byte, error) {
	model := strings.TrimSpace(strings.ToLower(req.Model))
	if model == "" {
		model = "openpaths/auto-cheap"
	}
	if _, ok := chatModelPricesUSD[model]; !ok {
		return nil, fmt.Errorf("unsupported chat model %q", model)
	}
	prompt := strings.TrimSpace(req.Prompt)
	if prompt == "" {
		return nil, fmt.Errorf("chat prompt is required")
	}
	if len(prompt) > chatMaxPromptChars {
		return nil, fmt.Errorf("prompt exceeds %d characters", chatMaxPromptChars)
	}
	if openPathsAPIKey == "" {
		return nil, fmt.Errorf("chat_generate requires OpenPaths to be configured")
	}
	msgs := []map[string]string{}
	if sys := strings.TrimSpace(req.Input); sys != "" && len(sys) <= 2000 {
		msgs = append(msgs, map[string]string{"role": "system", "content": sys})
	}
	msgs = append(msgs, map[string]string{"role": "user", "content": prompt})
	body, _ := json.Marshal(map[string]interface{}{"model": model, "messages": msgs, "max_tokens": chatMaxOutputTokens})
	out, _, err := callOpenPathsVideo("POST", openPathsBaseURL+"/v1/chat/completions", body)
	if err != nil {
		return nil, err
	}
	var parsed struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if json.Unmarshal(out, &parsed) != nil || len(parsed.Choices) == 0 {
		return out, nil
	}
	return json.Marshal(map[string]interface{}{"model": model, "text": parsed.Choices[0].Message.Content})
}
