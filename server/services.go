package main

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/valyala/fasthttp"
)

// Service pricing in USD (converted to $CUTE at current rate)
var servicePricesUSD = map[string]float64{
	"zimage":        1.00, // per generation
	"chronos2":      0.50, // per forecast
	"tts":           0.10, // per 100 chars
	"stt":           0.20, // per minute
	"lora_training": 50.00,
}

// Service backend URLs
var serviceBackends = map[string]string{}

func initServices() {
	serviceBackends["zimage"] = getEnv("ZIMAGE_BACKEND_URL", "http://localhost:8000")
	serviceBackends["chronos2"] = getEnv("CHRONOS_BACKEND_URL", "http://localhost:8001")
	serviceBackends["tts"] = getEnv("TTS_BACKEND_URL", "http://localhost:8002")
	serviceBackends["stt"] = getEnv("STT_BACKEND_URL", "http://localhost:8003")

	// Load custom prices from env
	if p := os.Getenv("ZIMAGE_PRICE_USD"); p != "" {
		servicePricesUSD["zimage"] = parseFloat(p)
	}
	if p := os.Getenv("CHRONOS_PRICE_USD"); p != "" {
		servicePricesUSD["chronos2"] = parseFloat(p)
	}
	if p := os.Getenv("TTS_PRICE_USD_PER_100CHARS"); p != "" {
		servicePricesUSD["tts"] = parseFloat(p)
	}
	if p := os.Getenv("STT_PRICE_USD_PER_MINUTE"); p != "" {
		servicePricesUSD["stt"] = parseFloat(p)
	}
	if p := os.Getenv("LORA_TRAINING_PRICE_USD"); p != "" {
		servicePricesUSD["lora_training"] = parseFloat(p)
	}

	log.Printf("Service pricing loaded: %v", servicePricesUSD)
}

// getServicePriceCUTE returns the current $CUTE cost for a service
func getServicePriceCUTE(service string) float64 {
	usdPrice, ok := servicePricesUSD[service]
	if !ok {
		return 0
	}
	cutePrice := getCUTEPriceUSD()
	if cutePrice <= 0 {
		return 0
	}
	return usdPrice / cutePrice
}

// handleGetPricing returns current pricing for all services
func handleGetPricing(ctx *fasthttp.RequestCtx) {
	cutePrice := getCUTEPriceUSD()

	units := map[string]string{
		"zimage":        "per generation",
		"chronos2":      "per forecast",
		"tts":           "per 100 characters",
		"stt":           "per minute",
		"lora_training": "per training job",
	}

	var pricing []ServicePricing
	for service, usdPrice := range servicePricesUSD {
		cuteCost := float64(0)
		if cutePrice > 0 {
			cuteCost = usdPrice / cutePrice
		}
		pricing = append(pricing, ServicePricing{
			Service:   service,
			PriceUSD:  usdPrice,
			PriceCute: cuteCost,
			CutePrice: cutePrice,
			Unit:      units[service],
		})
	}

	jsonResponse(ctx, 200, map[string]interface{}{
		"pricing":        pricing,
		"cute_price_usd": cutePrice,
		"sol_price_usd":  getSOLPriceUSD(),
	})
}

// handleServiceRequest processes an AI service request, deducts credits, and proxies to backend
func handleServiceRequest(ctx *fasthttp.RequestCtx) {
	var req ServiceUsageRequest
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil {
		jsonError(ctx, 400, "invalid json")
		return
	}

	if req.WalletAddress == "" {
		jsonError(ctx, 401, "wallet_address required")
		return
	}

	if req.Service == "" {
		jsonError(ctx, 400, "service required (zimage, chronos2, tts, stt)")
		return
	}

	// Validate service exists
	_, ok := servicePricesUSD[req.Service]
	if !ok {
		jsonError(ctx, 400, "unknown service: "+req.Service)
		return
	}

	// Get user
	user, err := dbConn.GetUserByWallet(req.WalletAddress)
	if err != nil {
		jsonError(ctx, 401, "wallet not registered - deposit $CUTE first")
		return
	}

	// Calculate cost in $CUTE
	cuteCost := getServicePriceCUTE(req.Service)
	if cuteCost <= 0 {
		jsonError(ctx, 503, "pricing unavailable")
		return
	}

	// For TTS, scale by text length
	if req.Service == "tts" && req.Text != "" {
		chars := float64(len(req.Text))
		cuteCost = cuteCost * (chars / 100.0)
		if cuteCost < getServicePriceCUTE("tts")*0.1 {
			cuteCost = getServicePriceCUTE("tts") * 0.1 // Minimum charge
		}
	}

	// Deduct credits
	newBalance, err := dbConn.DeductUserCredits(user.ID, cuteCost)
	if err != nil {
		if strings.Contains(err.Error(), "insufficient") {
			jsonError(ctx, 402, fmt.Sprintf("insufficient credits: need %.2f $CUTE, have %.2f", cuteCost, user.Credits))
			return
		}
		jsonError(ctx, 500, "failed to deduct credits")
		return
	}

	// Log billing event
	cutePrice := getCUTEPriceUSD()
	usdEquiv := cuteCost * cutePrice
	go dbConn.CreateBillingEvent(&BillingEvent{
		UserID:       user.ID,
		EventType:    req.Service,
		Amount:       -cuteCost,
		CuteAmount:   cuteCost,
		USDAmount:    usdEquiv,
		Description:  fmt.Sprintf("%s usage (%.2f $CUTE @ $%.6f)", req.Service, cuteCost, cutePrice),
		CreditsAfter: newBalance,
	})

	log.Printf("Service %s: user=%s cost=%.2f CUTE ($%.4f) balance=%.2f",
		req.Service, req.WalletAddress, cuteCost, usdEquiv, newBalance)

	// Proxy to backend service
	backendURL, ok := serviceBackends[req.Service]
	if !ok {
		jsonError(ctx, 503, "service backend not configured")
		return
	}

	result, err := proxyToBackend(req, backendURL)
	if err != nil {
		log.Printf("Backend proxy error for %s: %v", req.Service, err)
		// Refund on backend failure
		refundBalance, refundErr := dbConn.AddUserCredits(user.ID, cuteCost)
		if refundErr == nil {
			go dbConn.CreateBillingEvent(&BillingEvent{
				UserID:       user.ID,
				EventType:    "refund",
				Amount:       cuteCost,
				CuteAmount:   cuteCost,
				USDAmount:    usdEquiv,
				Description:  fmt.Sprintf("Refund: %s backend error", req.Service),
				CreditsAfter: refundBalance,
			})
		}
		jsonError(ctx, 502, "service temporarily unavailable")
		return
	}

	// Return backend response with billing info
	jsonResponse(ctx, 200, map[string]interface{}{
		"result":         json.RawMessage(result),
		"credits_used":   cuteCost,
		"credits_remain": newBalance,
		"usd_equivalent": usdEquiv,
	})
}

// proxyToBackend forwards the request to the appropriate AI service backend
func proxyToBackend(req ServiceUsageRequest, backendURL string) ([]byte, error) {
	var endpoint string
	var body io.Reader

	switch req.Service {
	case "zimage":
		endpoint = fmt.Sprintf("%s/create_and_upload_image?prompt=%s", backendURL,
			strings.ReplaceAll(req.Prompt, " ", "%20"))
		if req.Width > 0 {
			endpoint += fmt.Sprintf("&width=%d", req.Width)
		}
		if req.Height > 0 {
			endpoint += fmt.Sprintf("&height=%d", req.Height)
		}

	case "chronos2":
		endpoint = fmt.Sprintf("%s/forecast", backendURL)
		jsonBody, _ := json.Marshal(map[string]interface{}{
			"prompt": req.Prompt,
		})
		body = strings.NewReader(string(jsonBody))

	case "tts":
		endpoint = fmt.Sprintf("%s/synthesize", backendURL)
		jsonBody, _ := json.Marshal(map[string]interface{}{
			"text": req.Text,
		})
		body = strings.NewReader(string(jsonBody))

	case "stt":
		endpoint = fmt.Sprintf("%s/transcribe", backendURL)
		jsonBody, _ := json.Marshal(map[string]interface{}{
			"audio_url": req.AudioURL,
		})
		body = strings.NewReader(string(jsonBody))

	default:
		return nil, fmt.Errorf("unknown service: %s", req.Service)
	}

	httpReq, err := http.NewRequest("POST", endpoint, body)
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 120 * time.Second}
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("backend returned %d: %s", resp.StatusCode, string(respBody))
	}

	return respBody, nil
}

// handleGetBalance returns wallet balance and credit info
func handleGetBalance(ctx *fasthttp.RequestCtx) {
	wallet := string(ctx.QueryArgs().Peek("wallet"))
	if wallet == "" {
		jsonError(ctx, 400, "wallet query param required")
		return
	}

	user, err := dbConn.GetUserByWallet(wallet)
	if err != nil {
		// Return zero balance for unknown wallets
		jsonResponse(ctx, 200, WalletBalanceResponse{
			WalletAddress: wallet,
			Credits:       0,
			CreditsUSD:    0,
			CutePrice:     getCUTEPriceUSD(),
		})
		return
	}

	cutePrice := getCUTEPriceUSD()
	jsonResponse(ctx, 200, WalletBalanceResponse{
		WalletAddress:  user.WalletAddress,
		Credits:        user.Credits,
		CreditsUSD:     user.Credits * cutePrice,
		CutePrice:      cutePrice,
		TotalDeposited: user.TotalDeposited,
	})
}

// handleGetBillingHistory returns billing events for a wallet
func handleGetBillingHistory(ctx *fasthttp.RequestCtx) {
	wallet := string(ctx.QueryArgs().Peek("wallet"))
	if wallet == "" {
		jsonError(ctx, 400, "wallet query param required")
		return
	}

	user, err := dbConn.GetUserByWallet(wallet)
	if err != nil {
		jsonResponse(ctx, 200, map[string]interface{}{"events": []interface{}{}})
		return
	}

	events, err := dbConn.GetUserBillingHistory(user.ID, 50)
	if err != nil {
		jsonError(ctx, 500, "failed to get billing history")
		return
	}

	jsonResponse(ctx, 200, map[string]interface{}{"events": events})
}
