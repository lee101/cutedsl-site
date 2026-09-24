package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/valyala/fasthttp"
)

// Paywall contract shared with the omniserve gateway:
// 401 unauthenticated, 402 unsubscribed, body
// {"error":{"code","message","subscribe_url"}} plus X-Subscribe-URL.

func subscribeURL() string {
	return getEnv("CUTEDSL_SUBSCRIBE_URL", "https://cutedsl.cc/account")
}

func paywallError(ctx *fasthttp.RequestCtx, status int, msg string) {
	code := "subscription_required"
	if status == 401 {
		code = "authentication_required"
	}
	url := subscribeURL()
	ctx.Response.Header.Set("X-Subscribe-URL", url)
	jsonResponse(ctx, status, map[string]interface{}{
		"error": map[string]string{"code": code, "message": msg, "subscribe_url": url},
	})
}

// upstreamPaywallError marks a backend 401/402 so it is surfaced to the
// caller per contract instead of as a 502.
type upstreamPaywallError struct {
	Status  int
	Message string
}

func (e *upstreamPaywallError) Error() string {
	return fmt.Sprintf("backend returned %d: %s", e.Status, e.Message)
}

func checkUpstreamPaywall(status int, body []byte) error {
	if status != 401 && status != 402 {
		return nil
	}
	msg := ""
	var parsed struct {
		Error  json.RawMessage `json:"error"`
		Detail string          `json:"detail"`
	}
	if json.Unmarshal(body, &parsed) == nil {
		var obj struct {
			Message string `json:"message"`
		}
		var s string
		if json.Unmarshal(parsed.Error, &obj) == nil && obj.Message != "" {
			msg = obj.Message
		} else if json.Unmarshal(parsed.Error, &s) == nil && s != "" {
			msg = s
		} else {
			msg = parsed.Detail
		}
	}
	if strings.TrimSpace(msg) == "" {
		msg = "Subscribe to CuteDSL to use GPU image services."
	}
	return &upstreamPaywallError{Status: status, Message: msg}
}

func asUpstreamPaywall(err error) (*upstreamPaywallError, bool) {
	var pe *upstreamPaywallError
	if errors.As(err, &pe) {
		return pe, true
	}
	return nil, false
}

func isUnlimitedImageService(service string) bool {
	switch service {
	case "zimage", "ra2", "ra2-edit":
		return true
	}
	return false
}
