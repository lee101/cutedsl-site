package main

import (
	"crypto/sha1"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/valyala/fasthttp"
)

// Service pricing in USD (converted to $CUTE at current rate)
var servicePricesUSD = map[string]float64{
	"zimage":        0.04,  // per generation
	"chronos2":      0.02,  // per forecast
	"tts":           0.005, // per 100 chars
	"stt":           0.02,  // per minute
	"gemma4":        0.01,  // per request
	"caption":       0.01,  // per image
	"lora_training": 10.00,
	"ltx_video":     0.30,  // per ~6s 1080p video via fal.ai
	"flux_image":    0.04,  // per image via fal.ai or netwrck
	"nsfw_detect":   0.001, // per image classification
}

var zimageDefaultSteps = 8
var zimageHighStepPriceUSD = 0.10

// First-party services run on our hardware — priced at ATH rate to reward early holders.
// If you bought $CUTEDSL at $0.001 and ATH is $0.01, you pay 10x fewer tokens.
var firstPartyServices = map[string]bool{
	"zimage": true, "chronos2": true, "tts": true,
	"stt": true, "gemma4": true, "caption": true, "lora_training": true,
	"nsfw_detect": true,
}

// FAL API key for third-party proxied services
var falAPIKey string

// Reusable HTTP client with connection pooling
var backendClient = &http.Client{
	Timeout: 180 * time.Second,
	Transport: &http.Transport{
		MaxIdleConns:        100,
		MaxIdleConnsPerHost: 20,
		MaxConnsPerHost:     50,
		IdleConnTimeout:     90 * time.Second,
	},
}

// Service backend URLs
var serviceBackends = map[string]string{}

func initServices() {
	// CuteDSL inference server serves zimage, chronos2, tts, stt, caption, gemma4
	inferenceURL := getEnv("INFERENCE_BACKEND_URL", "http://localhost:8100")

	serviceBackends["zimage"] = getEnv("ZIMAGE_BACKEND_URL", inferenceURL)
	serviceBackends["chronos2"] = getEnv("CHRONOS_BACKEND_URL", inferenceURL)
	serviceBackends["tts"] = getEnv("TTS_BACKEND_URL", inferenceURL)
	serviceBackends["stt"] = getEnv("STT_BACKEND_URL", inferenceURL)
	serviceBackends["gemma4"] = getEnv("GEMMA4_BACKEND_URL", inferenceURL)
	serviceBackends["caption"] = getEnv("CAPTION_BACKEND_URL", inferenceURL)
	serviceBackends["lora_training"] = getEnv("LORA_TRAINING_BACKEND_URL", inferenceURL)
	serviceBackends["ltx_video"] = "https://fal.run"
	serviceBackends["flux_image"] = "https://fal.run"

	falAPIKey = getEnv("FAL_KEY", getEnv("FAL_API_KEY", ""))
	if falAPIKey != "" {
		log.Printf("FAL API key configured for ltx_video and flux_image services")
	}

	// Load custom prices from env
	envPriceMap := map[string]string{
		"zimage":        "ZIMAGE_PRICE_USD",
		"chronos2":      "CHRONOS_PRICE_USD",
		"tts":           "TTS_PRICE_USD_PER_100CHARS",
		"stt":           "STT_PRICE_USD_PER_MINUTE",
		"gemma4":        "GEMMA4_PRICE_USD",
		"caption":       "CAPTION_PRICE_USD",
		"lora_training": "LORA_TRAINING_PRICE_USD",
		"ltx_video":     "LTX_VIDEO_PRICE_USD",
		"flux_image":    "FLUX_IMAGE_PRICE_USD",
		"nsfw_detect":   "NSFW_DETECT_PRICE_USD",
	}
	for svc, envKey := range envPriceMap {
		if p := os.Getenv(envKey); p != "" {
			servicePricesUSD[svc] = parseFloat(p)
		}
	}
	if p := os.Getenv("ZIMAGE_20_40_STEPS_PRICE_USD"); p != "" {
		zimageHighStepPriceUSD = parseFloat(p)
	}
	if steps := os.Getenv("ZIMAGE_DEFAULT_STEPS"); steps != "" {
		if parsed := parseInt(steps); parsed > 0 {
			zimageDefaultSteps = parsed
		}
	}

	log.Printf("Service pricing loaded: %v", servicePricesUSD)
	log.Printf("Z-Image default steps: %d, 20+ step price: $%.4f", zimageDefaultSteps, zimageHighStepPriceUSD)
	log.Printf("Service backends: %v", serviceBackends)

	// Initialize diffusionz C engine for direct GPU inference (optional)
	initDiffusionzEngine()
}

// getServicePriceCUTE returns the current $CUTE cost for a service.
// First-party services use ATH pricing — rewarding early token holders with
// permanently lower rates. Third-party proxy services use current market price.
func getServicePriceCUTE(service string) float64 {
	usdPrice, ok := servicePricesUSD[service]
	if !ok {
		return 0
	}

	var pricePerToken float64
	if firstPartyServices[service] {
		// ATH pricing: divide by ATH price, so if token pumps, you need fewer tokens
		pricePerToken = getCUTEPriceATH()
	} else {
		pricePerToken = getCUTEPriceUSD()
	}

	if pricePerToken <= 0 {
		return 0
	}
	return usdPrice / pricePerToken
}

func getRequestServicePriceUSD(req ServiceUsageRequest) float64 {
	usdPrice, ok := servicePricesUSD[req.Service]
	if !ok {
		return 0
	}
	if req.Service == "zimage" && getZImageSteps(req) >= 20 {
		return zimageHighStepPriceUSD
	}
	return usdPrice
}

func getRequestServicePriceCUTE(req ServiceUsageRequest) float64 {
	usdPrice := getRequestServicePriceUSD(req)
	if usdPrice <= 0 {
		return 0
	}

	var pricePerToken float64
	if firstPartyServices[req.Service] {
		pricePerToken = getCUTEPriceATH()
	} else {
		pricePerToken = getCUTEPriceUSD()
	}
	if pricePerToken <= 0 {
		return 0
	}
	return usdPrice / pricePerToken
}

func getZImageSteps(req ServiceUsageRequest) int {
	if req.NumSteps > 0 {
		return req.NumSteps
	}
	return zimageDefaultSteps
}

// handleGetPricing returns current pricing for all services
func handleGetPricing(ctx *fasthttp.RequestCtx) {
	cutePrice := getCUTEPriceUSD()

	units := map[string]string{
		"zimage":        fmt.Sprintf("per generation (base); $%.2f for 20+ steps", zimageHighStepPriceUSD),
		"chronos2":      "per forecast",
		"tts":           "per 100 characters",
		"stt":           "per minute",
		"gemma4":        "per request",
		"caption":       "per image",
		"lora_training": "per training job",
		"ltx_video":     "per ~6s video",
		"flux_image":    "per image",
	}

	var pricing []ServicePricing
	for service, usdPrice := range servicePricesUSD {
		cuteCost := getServicePriceCUTE(service)
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
		"cute_price_ath": getCUTEPriceATH(),
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

	if req.Service == "" {
		req.Service = "zimage"
	}

	// Validate service exists
	_, ok := servicePricesUSD[req.Service]
	if !ok {
		jsonError(ctx, 400, "unknown service: "+req.Service)
		return
	}

	// Authenticate: API key (Authorization header) or wallet_address in body
	var user *User
	var err error
	authHeader := string(ctx.Request.Header.Peek("Authorization"))
	if strings.HasPrefix(authHeader, "Bearer ") {
		apiKey := strings.TrimPrefix(authHeader, "Bearer ")
		user, err = dbConn.GetUserByAPIKey(apiKey)
		if err != nil {
			jsonError(ctx, 401, "invalid API key")
			return
		}
	} else if req.WalletAddress != "" {
		user, err = dbConn.GetUserByWallet(req.WalletAddress)
		if err != nil {
			jsonError(ctx, 401, "wallet not registered - deposit $CUTEDSL first")
			return
		}
	} else {
		jsonError(ctx, 401, "authorization required: use Authorization header with API key or wallet_address in body")
		return
	}

	// Calculate cost in $CUTE
	cuteCost := getRequestServicePriceCUTE(req)
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

	newBalance := user.Credits
	billableCost := cuteCost
	if user.UnlimitedAPI {
		billableCost = 0
	} else {
		// Deduct credits
		newBalance, err = dbConn.DeductUserCredits(user.ID, cuteCost)
		if err != nil {
			if strings.Contains(err.Error(), "insufficient") {
				jsonError(ctx, 402, fmt.Sprintf("insufficient credits: need %.2f $CUTEDSL, have %.2f", cuteCost, user.Credits))
				return
			}
			jsonError(ctx, 500, "failed to deduct credits")
			return
		}
	}

	// Log billing event (for lora_training we log only in settle to avoid
	// double-booking — the deduction above is a hold).
	cutePrice := getCUTEPriceUSD()
	usdEquiv := cuteCost * cutePrice
	if req.Service != "lora_training" && !user.UnlimitedAPI {
		go dbConn.CreateBillingEvent(&BillingEvent{
			UserID:       user.ID,
			EventType:    req.Service,
			Amount:       -cuteCost,
			CuteAmount:   cuteCost,
			USDAmount:    usdEquiv,
			Description:  fmt.Sprintf("%s usage (%.2f $CUTEDSL @ $%.6f)", req.Service, cuteCost, cutePrice),
			CreditsAfter: newBalance,
		})
	}

	log.Printf("Service %s: user=%s cost=%.2f CUTEDSL ($%.4f) balance=%.2f",
		req.Service, user.WalletAddress, billableCost, billableCost*cutePrice, newBalance)

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
		if !user.UnlimitedAPI {
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
		}
		jsonError(ctx, 502, "service temporarily unavailable")
		return
	}

	// LoRA training is async — deduction above is a HOLD. A background
	// watcher polls the inference job and either finalizes (keep deducted +
	// log billing event) or refunds on training failure.
	if req.Service == "lora_training" && !user.UnlimitedAPI {
		var r struct {
			JobID string `json:"job_id"`
		}
		if jerr := json.Unmarshal(result, &r); jerr == nil && r.JobID != "" {
			go settleLoraTrainingJob(user.ID, r.JobID, cuteCost, cutePrice)
		}
	}

	if !user.UnlimitedAPI {
		maybeTriggerAutoTopup(user.ID)
	}

	result, savedImage := persistGeneratedZImage(req, user, result)

	// Return backend response with billing info
	response := map[string]interface{}{
		"result":          json.RawMessage(result),
		"credits_used":    billableCost,
		"credits_remain":  newBalance,
		"usd_equivalent":  billableCost * cutePrice,
		"unlimited_api":   user.UnlimitedAPI,
		"metered_credits": cuteCost,
	}
	if savedImage != nil {
		response["saved_image"] = savedImage
	}
	jsonResponse(ctx, 200, response)
}

func persistGeneratedZImage(req ServiceUsageRequest, user *User, result []byte) ([]byte, *GeneratedImage) {
	if req.Service != "zimage" || req.Prompt == "" || user == nil {
		return result, nil
	}

	var payload map[string]interface{}
	if err := json.Unmarshal(result, &payload); err != nil {
		return result, nil
	}
	imageB64, _ := payload["image_base64"].(string)
	if imageB64 == "" {
		return result, nil
	}
	imageBytes, err := base64.StdEncoding.DecodeString(imageB64)
	if err != nil || len(imageBytes) == 0 {
		log.Printf("zimage persist decode failed: %v", err)
		return result, nil
	}

	imageID := newUUID()
	hash := sha1.Sum([]byte(req.Prompt))
	fileName := fmt.Sprintf("%s_%s.webp", hex.EncodeToString(hash[:])[:16], imageID[:8])
	relPath := filepath.ToSlash(filepath.Join("originals", fileName))
	imageDir := getEnv("IMAGES_DIR", "/sdb-disk/cutedsl-images")
	fullPath := filepath.Join(imageDir, relPath)
	if err := os.MkdirAll(filepath.Dir(fullPath), 0755); err != nil {
		log.Printf("zimage persist mkdir failed: %v", err)
		return result, nil
	}
	if err := os.WriteFile(fullPath, imageBytes, 0644); err != nil {
		log.Printf("zimage persist write failed: %v", err)
		return result, nil
	}

	width := intFromPayload(payload, "width", req.Width)
	if width <= 0 {
		width = 1024
	}
	height := intFromPayload(payload, "height", req.Height)
	if height <= 0 {
		height = 1024
	}
	seed := int64(intFromPayload(payload, "seed", req.Seed))
	steps := getZImageSteps(req)
	img := &GeneratedImage{
		ID:              imageID,
		Prompt:          req.Prompt,
		Width:           width,
		Height:          height,
		FilePath:        relPath,
		ThumbPath:       relPath,
		MedPath:         relPath,
		FileSize:        int64(len(imageBytes)),
		Model:           "zimage",
		Seed:            seed,
		Steps:           steps,
		CreatedByUserID: user.ID,
		CreatedAt:       time.Now(),
	}
	if err := dbConn.InsertGeneratedImage(img); err != nil {
		log.Printf("zimage persist db insert failed: %v", err)
		return result, nil
	}

	payload["gallery_image"] = img
	updated, err := json.Marshal(payload)
	if err != nil {
		return result, img
	}
	return updated, img
}

func intFromPayload(payload map[string]interface{}, key string, fallback int) int {
	switch v := payload[key].(type) {
	case float64:
		return int(v)
	case int:
		return v
	case json.Number:
		i, _ := v.Int64()
		return int(i)
	default:
		return fallback
	}
}

// settleLoraTrainingJob polls the inference server for a training job and
// finalizes billing: if the job completes we log a permanent billing event;
// if it fails, we refund the credits and log a refund event.
// Runs as a goroutine; blocks up to ~2 hours before giving up (keeping charge).
func settleLoraTrainingJob(userID, jobID string, cuteCost, cutePrice float64) {
	backendURL := serviceBackends["lora_training"]
	endpoint := fmt.Sprintf("%s/train/%s", backendURL, jobID)
	usdEquiv := cuteCost * cutePrice

	start := time.Now()
	for time.Since(start) < 2*time.Hour {
		time.Sleep(5 * time.Second)
		resp, err := backendClient.Get(endpoint)
		if err != nil {
			continue
		}
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if resp.StatusCode != 200 {
			continue
		}

		var job struct {
			Status     string  `json:"status"`
			OutputPath string  `json:"output_path"`
			ErrorMsg   string  `json:"error"`
			Loss       float64 `json:"loss"`
		}
		if err := json.Unmarshal(body, &job); err != nil {
			continue
		}

		switch job.Status {
		case "completed":
			// Finalize: the credits were already held. Log the billing event now.
			// Use a no-op add of 0 to fetch current balance.
			balAfter, _ := dbConn.AddUserCredits(userID, 0)
			dbConn.CreateBillingEvent(&BillingEvent{
				UserID:       userID,
				EventType:    "lora_training",
				Amount:       -cuteCost,
				CuteAmount:   cuteCost,
				USDAmount:    usdEquiv,
				Description:  fmt.Sprintf("LoRA training completed (job=%s, loss=%.4f, output=%s)", jobID, job.Loss, job.OutputPath),
				CreditsAfter: balAfter,
			})
			log.Printf("Lora job %s settled: completed, charged %.2f CUTEDSL ($%.4f)", jobID, cuteCost, usdEquiv)
			return

		case "failed":
			// Refund the hold
			refundBalance, rerr := dbConn.AddUserCredits(userID, cuteCost)
			if rerr == nil {
				dbConn.CreateBillingEvent(&BillingEvent{
					UserID:       userID,
					EventType:    "refund",
					Amount:       cuteCost,
					CuteAmount:   cuteCost,
					USDAmount:    usdEquiv,
					Description:  fmt.Sprintf("Refund: LoRA training failed (job=%s): %s", jobID, truncateString(job.ErrorMsg, 200)),
					CreditsAfter: refundBalance,
				})
			}
			log.Printf("Lora job %s settled: failed, refunded %.2f CUTEDSL. Error: %s", jobID, cuteCost, job.ErrorMsg)
			return
		}
	}

	log.Printf("Lora job %s: gave up polling after 2h, charge stands", jobID)
}

func truncateString(s string, n int) string {
	if len(s) > n {
		return s[:n] + "..."
	}
	return s
}

// proxyToBackend forwards the request to the appropriate AI service backend
func proxyToBackend(req ServiceUsageRequest, backendURL string) ([]byte, error) {
	var endpoint string
	var body io.Reader
	var method = "POST"

	switch req.Service {
	case "zimage":
		// Fast path: use diffusionz C engine for direct GPU inference
		if diffusionzAvailable {
			width := req.Width
			if width <= 0 {
				width = 1024
			}
			height := req.Height
			if height <= 0 {
				height = 1024
			}
			steps := req.NumSteps
			if steps <= 0 {
				steps = zimageDefaultSteps
			}
			guidance := req.Guidance
			if guidance <= 0 {
				guidance = 3.5
			}
			seed := req.Seed // 0 means random in the C engine

			imgBytes, err := generateImageC(req.Prompt, width, height, steps, seed, guidance)
			if err != nil {
				log.Printf("diffusionz generateImageC failed, falling back to HTTP proxy: %v", err)
			} else {
				// Return a JSON response matching the HTTP backend format
				result, _ := json.Marshal(map[string]interface{}{
					"image_bytes_len": len(imgBytes),
					"width":           width,
					"height":          height,
					"format":          "webp",
					"engine":          "diffusionz",
				})
				return result, nil
			}
		}

		// Fallback: HTTP proxy to backend
		endpoint = fmt.Sprintf("%s/generate_image", backendURL)
		payload := map[string]interface{}{
			"prompt": req.Prompt,
		}
		if req.Width > 0 {
			payload["width"] = req.Width
		}
		if req.Height > 0 {
			payload["height"] = req.Height
		}
		payload["num_inference_steps"] = getZImageSteps(req)
		if req.Guidance > 0 {
			payload["guidance_scale"] = req.Guidance
		}
		if req.Seed > 0 {
			payload["seed"] = req.Seed
		}
		jsonBody, _ := json.Marshal(payload)
		body = strings.NewReader(string(jsonBody))

	case "chronos2":
		endpoint = fmt.Sprintf("%s/forecast", backendURL)
		payload := map[string]interface{}{
			"values": req.Values,
		}
		if req.PredictionLength > 0 {
			payload["prediction_length"] = req.PredictionLength
		}
		if len(req.QuantileLevels) > 0 {
			payload["quantile_levels"] = req.QuantileLevels
		}
		jsonBody, _ := json.Marshal(payload)
		body = strings.NewReader(string(jsonBody))

	case "tts":
		endpoint = fmt.Sprintf("%s/synthesize", backendURL)
		payload := map[string]interface{}{
			"text": req.Text,
		}
		if req.Voice != "" {
			payload["voice"] = req.Voice
		}
		if req.Speed > 0 {
			payload["speed"] = req.Speed
		}
		jsonBody, _ := json.Marshal(payload)
		body = strings.NewReader(string(jsonBody))

	case "stt":
		endpoint = fmt.Sprintf("%s/transcribe", backendURL)
		jsonBody, _ := json.Marshal(map[string]interface{}{
			"audio_url": req.AudioURL,
		})
		body = strings.NewReader(string(jsonBody))

	case "gemma4":
		endpoint = fmt.Sprintf("%s/chat", backendURL)
		payload := map[string]interface{}{
			"messages":    req.Messages,
			"max_tokens":  req.MaxTokens,
			"temperature": req.Temperature,
		}
		if req.MaxTokens == 0 {
			payload["max_tokens"] = 1024
		}
		if req.Temperature == 0 {
			payload["temperature"] = 0.7
		}
		jsonBody, _ := json.Marshal(payload)
		body = strings.NewReader(string(jsonBody))

	case "caption":
		endpoint = fmt.Sprintf("%s/caption", backendURL)
		jsonBody, _ := json.Marshal(map[string]interface{}{
			"image_url": req.ImageURL,
		})
		body = strings.NewReader(string(jsonBody))

	case "ltx_video":
		endpoint = "https://fal.run/fal-ai/ltx-2.3/text-to-video"
		payload := map[string]interface{}{
			"prompt":     req.Prompt,
			"duration":   6,
			"resolution": "1080p",
			"fps":        25,
		}
		jsonBody, _ := json.Marshal(payload)
		body = strings.NewReader(string(jsonBody))
		// FAL auth is handled below in the request

	case "flux_image":
		endpoint = "https://fal.run/fal-ai/flux/schnell"
		payload := map[string]interface{}{
			"prompt":              req.Prompt,
			"image_size":          "square_hd",
			"num_inference_steps": 4,
		}
		jsonBody, _ := json.Marshal(payload)
		body = strings.NewReader(string(jsonBody))

	case "lora_training":
		endpoint = fmt.Sprintf("%s/train", backendURL)
		payload := map[string]interface{}{
			"model":        req.Model,
			"dataset_name": req.DatasetName,
		}
		if len(req.TrainValues) > 0 {
			payload["values"] = req.TrainValues
		}
		if req.LoRAR > 0 {
			payload["lora_r"] = req.LoRAR
		}
		if req.LoRAAlpha > 0 {
			payload["lora_alpha"] = req.LoRAAlpha
		}
		if req.LearningRate > 0 {
			payload["learning_rate"] = req.LearningRate
		}
		if req.TrainSteps > 0 {
			payload["num_steps"] = req.TrainSteps
		}
		if req.TrainBatch > 0 {
			payload["batch_size"] = req.TrainBatch
		}
		jsonBody, _ := json.Marshal(payload)
		body = strings.NewReader(string(jsonBody))

	default:
		return nil, fmt.Errorf("unknown service: %s", req.Service)
	}

	httpReq, err := http.NewRequest(method, endpoint, body)
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	// Add FAL API key for fal.ai proxy services
	if (req.Service == "ltx_video" || req.Service == "flux_image") && falAPIKey != "" {
		httpReq.Header.Set("Authorization", "Key "+falAPIKey)
	}

	resp, err := backendClient.Do(httpReq)
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

// handleTrainStatus proxies training job status from inference server
func handleTrainStatus(ctx *fasthttp.RequestCtx, jobID string) {
	backendURL := serviceBackends["lora_training"]
	endpoint := fmt.Sprintf("%s/train/%s", backendURL, jobID)

	resp, err := backendClient.Get(endpoint)
	if err != nil {
		jsonError(ctx, 502, "training backend unavailable")
		return
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		jsonError(ctx, 502, "failed to read training status")
		return
	}

	ctx.SetStatusCode(resp.StatusCode)
	ctx.SetBody(respBody)
}

// handleListTrainingDatasets proxies the dataset listing from inference server.
func handleListTrainingDatasets(ctx *fasthttp.RequestCtx) {
	backendURL := serviceBackends["lora_training"]
	resp, err := backendClient.Get(backendURL + "/train/datasets")
	if err != nil {
		jsonError(ctx, 502, "training backend unavailable")
		return
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	ctx.SetStatusCode(resp.StatusCode)
	ctx.SetBody(body)
}

// handleUploadTrainingDataset accepts multipart upload and forwards to inference.
// Auth: Bearer API key. Does not deduct credits — that happens at /api/service POST when training starts.
func handleUploadTrainingDataset(ctx *fasthttp.RequestCtx) {
	authHeader := string(ctx.Request.Header.Peek("Authorization"))
	if !strings.HasPrefix(authHeader, "Bearer ") {
		jsonError(ctx, 401, "API key required (Authorization: Bearer ...)")
		return
	}
	apiKey := strings.TrimPrefix(authHeader, "Bearer ")
	if _, err := dbConn.GetUserByAPIKey(apiKey); err != nil {
		jsonError(ctx, 401, "invalid API key")
		return
	}

	// Forward multipart body verbatim to inference /train/upload_dataset
	backendURL := serviceBackends["lora_training"]
	endpoint := backendURL + "/train/upload_dataset"

	httpReq, err := http.NewRequest("POST", endpoint, strings.NewReader(string(ctx.PostBody())))
	if err != nil {
		jsonError(ctx, 500, "failed to build upload request")
		return
	}
	contentType := string(ctx.Request.Header.ContentType())
	httpReq.Header.Set("Content-Type", contentType)
	httpReq.ContentLength = int64(len(ctx.PostBody()))

	resp, err := backendClient.Do(httpReq)
	if err != nil {
		jsonError(ctx, 502, "upload backend unavailable")
		return
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	ctx.SetStatusCode(resp.StatusCode)
	ctx.SetBody(body)
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
		WalletAddress:         user.WalletAddress,
		Credits:               user.Credits,
		CreditsUSD:            user.Credits * cutePrice,
		CutePrice:             cutePrice,
		TotalDeposited:        user.TotalDeposited,
		StripeCustomerID:      user.StripeCustomerID,
		AutotopupEnabled:      user.AutotopupEnabled,
		AutotopupThresholdUSD: user.AutotopupThresholdUSD,
		AutotopupAmountUSD:    user.AutotopupAmountUSD,
		HasPaymentMethod:      user.StripePaymentMethodID != "",
		HasPassword:           user.PasswordHash != "",
		UnlimitedAPI:          user.UnlimitedAPI,
		SubscriptionStatus:    user.SubscriptionStatus,
		SubscriptionPlan:      user.SubscriptionPlan,
		StripePriceID:         user.StripePriceID,
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
