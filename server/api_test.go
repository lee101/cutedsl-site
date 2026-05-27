package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/valyala/fasthttp"
)

var testServerAddr string

// TestMain starts a real server with a test database before all tests
func TestMain(m *testing.M) {
	// Use test database (SQLite-style DSN for test isolation)
	testDSN := os.Getenv("TEST_DATABASE_URL")
	if testDSN == "" {
		testDSN = "postgres://cutedsl:cutedsl_pass_2026@localhost:5432/cutedsl_test?sslmode=disable"
	}

	var err error
	dbConn, err = NewDB(testDSN)
	if err != nil {
		fmt.Fprintf(os.Stderr, "SKIP: cannot connect to test database: %v\n", err)
		fmt.Fprintf(os.Stderr, "Set TEST_DATABASE_URL or run: createdb cutedsl_test\n")
		os.Exit(0)
	}

	devMode = true
	frontendURL = "http://localhost:3000"
	os.Setenv("ZIMAGE_PRICE_USD", "0.04")
	os.Setenv("CHRONOS_PRICE_USD", "0.02")
	os.Setenv("TTS_PRICE_USD_PER_100CHARS", "0.005")
	os.Setenv("STT_PRICE_USD_PER_MINUTE", "0.02")
	os.Setenv("GEMMA4_PRICE_USD", "0.01")
	os.Setenv("CAPTION_PRICE_USD", "0.01")
	os.Setenv("LORA_TRAINING_PRICE_USD", "5")
	os.Setenv("LTX_VIDEO_PRICE_USD", "0.30")
	os.Setenv("FLUX_IMAGE_PRICE_USD", "0.04")
	os.Setenv("NSFW_DETECT_PRICE_USD", "0.001")
	initServices()

	// Find a free port
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		fmt.Fprintf(os.Stderr, "cannot listen: %v\n", err)
		os.Exit(1)
	}
	testServerAddr = listener.Addr().String()
	listener.Close()

	// Start server in background
	go func() {
		if err := fasthttp.ListenAndServe(testServerAddr, requestHandler); err != nil {
			fmt.Fprintf(os.Stderr, "server error: %v\n", err)
		}
	}()

	// Wait for server to be ready
	for i := 0; i < 50; i++ {
		conn, err := net.DialTimeout("tcp", testServerAddr, 100*time.Millisecond)
		if err == nil {
			conn.Close()
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	code := m.Run()

	dbConn.Close()
	os.Exit(code)
}

func baseURL() string {
	return "http://" + testServerAddr
}

func doGet(t *testing.T, path string) (int, map[string]interface{}) {
	t.Helper()
	resp, err := http.Get(baseURL() + path)
	if err != nil {
		t.Fatalf("GET %s: %v", path, err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	var result map[string]interface{}
	json.Unmarshal(body, &result)
	return resp.StatusCode, result
}

func doPost(t *testing.T, path string, payload interface{}, headers ...string) (int, map[string]interface{}) {
	t.Helper()
	jsonBody, _ := json.Marshal(payload)
	req, err := http.NewRequest("POST", baseURL()+path, strings.NewReader(string(jsonBody)))
	if err != nil {
		t.Fatalf("POST %s: %v", path, err)
	}
	req.Header.Set("Content-Type", "application/json")
	for i := 0; i+1 < len(headers); i += 2 {
		req.Header.Set(headers[i], headers[i+1])
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("POST %s: %v", path, err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	var result map[string]interface{}
	json.Unmarshal(body, &result)
	return resp.StatusCode, result
}

func doGetRaw(t *testing.T, path string) (int, []byte) {
	t.Helper()
	resp, err := http.Get(baseURL() + path)
	if err != nil {
		t.Fatalf("GET %s: %v", path, err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, body
}

// ---- Health ----

func TestHealthEndpoint(t *testing.T) {
	status, body := doGet(t, "/api/health")
	if status != 200 {
		t.Fatalf("expected 200, got %d", status)
	}
	if body["status"] != "ok" {
		t.Fatalf("expected status ok, got %v", body["status"])
	}
	if body["service"] != "cutedsl" {
		t.Fatalf("expected service cutedsl, got %v", body["service"])
	}
}

func TestFrontendErrorEndpointLogsBrowserContext(t *testing.T) {
	logPath := filepath.Join(t.TempDir(), "frontend-errors.jsonl")
	t.Setenv("FRONTEND_ERROR_LOG_PATH", logPath)

	status, body := doPost(t, "/api/frontend-error", map[string]interface{}{
		"level":     "error",
		"message":   "Synthetic frontend failure",
		"name":      "TypeError",
		"stack":     "TypeError: Synthetic frontend failure\n    at Home (app/page.tsx:1:1)",
		"source":    "https://cutedsl.cc/_next/static/chunks/app.js",
		"lineno":    12,
		"colno":     34,
		"url":       "https://cutedsl.cc/?test=true",
		"referrer":  "https://appstatic.app.nz/cutedsl/",
		"userAgent": "Mozilla/5.0 Test Browser",
		"language":  "en-US",
		"timezone":  "UTC",
		"viewport": map[string]int{
			"width":  1280,
			"height": 720,
		},
		"screen": map[string]int{
			"width":  1920,
			"height": 1080,
		},
		"connection": map[string]interface{}{
			"effectiveType": "4g",
			"rtt":           40,
		},
		"sessionId":   "session-test",
		"fingerprint": "synthetic|app.js|12|34",
	})
	if status != 202 {
		t.Fatalf("expected 202, got %d: %v", status, body)
	}
	if body["request_id"] == "" {
		t.Fatalf("expected request_id in response: %v", body)
	}

	raw, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read frontend error log: %v", err)
	}
	var event map[string]interface{}
	if err := json.Unmarshal(raw, &event); err != nil {
		t.Fatalf("decode frontend error event: %v\n%s", err, string(raw))
	}
	if event["level"] != "error" || event["message"] != "Synthetic frontend failure" {
		t.Fatalf("unexpected event: %v", event)
	}
	if event["user_agent"] != "Mozilla/5.0 Test Browser" {
		t.Fatalf("missing browser context: %v", event)
	}
	if event["session_id"] != "session-test" {
		t.Fatalf("missing session id: %v", event)
	}
}

func TestFrontendErrorEndpointRejectsNonErrors(t *testing.T) {
	status, _ := doPost(t, "/api/frontend-error", map[string]interface{}{
		"level":   "info",
		"message": "not an error",
	})
	if status != 400 {
		t.Fatalf("expected 400 for non-error frontend event, got %d", status)
	}
}

// ---- Wallet Auth ----

func TestWalletAuth_Register(t *testing.T) {
	wallet := fmt.Sprintf("TestWallet_%d", time.Now().UnixNano())

	status, body := doPost(t, "/api/auth/wallet", map[string]string{
		"wallet_address": wallet,
	})
	if status != 200 {
		t.Fatalf("expected 200, got %d: %v", status, body)
	}
	if body["created"] != true {
		t.Fatalf("expected created=true, got %v", body["created"])
	}
	apiKey, ok := body["api_key"].(string)
	if !ok || !strings.HasPrefix(apiKey, "cutedsl_") {
		t.Fatalf("expected api_key with cutedsl_ prefix, got %v", body["api_key"])
	}

	// Second call should return created=false
	status2, body2 := doPost(t, "/api/auth/wallet", map[string]string{
		"wallet_address": wallet,
	})
	if status2 != 200 {
		t.Fatalf("expected 200, got %d", status2)
	}
	if body2["created"] != false {
		t.Fatalf("expected created=false on second call, got %v", body2["created"])
	}
	// API key should be the same
	if body2["api_key"] != apiKey {
		t.Fatalf("api_key changed between calls: %v vs %v", apiKey, body2["api_key"])
	}
}

func TestWalletAuth_MissingAddress(t *testing.T) {
	status, _ := doPost(t, "/api/auth/wallet", map[string]string{})
	if status != 400 {
		t.Fatalf("expected 400 for missing wallet, got %d", status)
	}
}

func TestWalletAuth_InvalidJSON(t *testing.T) {
	req, _ := http.NewRequest("POST", baseURL()+"/api/auth/wallet", strings.NewReader("not json"))
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 400 {
		t.Fatalf("expected 400, got %d", resp.StatusCode)
	}
}

// ---- Balance ----

func TestBalance_UnknownWallet(t *testing.T) {
	status, body := doGet(t, "/api/balance?wallet=UnknownWallet12345678901234567890")
	if status != 200 {
		t.Fatalf("expected 200, got %d", status)
	}
	credits := body["credits"].(float64)
	if credits != 0 {
		t.Fatalf("expected 0 credits for unknown wallet, got %f", credits)
	}
}

func TestBalance_RegisteredWallet(t *testing.T) {
	wallet := fmt.Sprintf("BalTest_%d", time.Now().UnixNano())
	doPost(t, "/api/auth/wallet", map[string]string{"wallet_address": wallet})

	status, body := doGet(t, "/api/balance?wallet="+wallet)
	if status != 200 {
		t.Fatalf("expected 200, got %d", status)
	}
	if body["wallet_address"] != wallet {
		t.Fatalf("expected wallet %s, got %v", wallet, body["wallet_address"])
	}
}

func TestBalance_MissingParam(t *testing.T) {
	status, _ := doGet(t, "/api/balance")
	if status != 400 {
		t.Fatalf("expected 400, got %d", status)
	}
}

// ---- Pricing ----

func TestPricing(t *testing.T) {
	status, body := doGet(t, "/api/pricing")
	if status != 200 {
		t.Fatalf("expected 200, got %d", status)
	}
	pricing, ok := body["pricing"].([]interface{})
	if !ok {
		t.Fatalf("expected pricing array, got %T", body["pricing"])
	}
	if len(pricing) == 0 {
		t.Fatal("expected non-empty pricing array")
	}

	// Check that all expected services are present
	services := map[string]bool{}
	prices := map[string]float64{}
	for _, p := range pricing {
		pm := p.(map[string]interface{})
		service := pm["service"].(string)
		services[service] = true
		prices[service], _ = pm["price_usd"].(float64)
	}
	for _, expected := range []string{"zimage", "chronos2", "tts", "stt", "gemma4", "caption", "lora_training"} {
		if !services[expected] {
			t.Errorf("missing service in pricing: %s", expected)
		}
	}
	if prices["zimage"] != 0.04 {
		t.Fatalf("expected zimage price_usd 0.04, got %v", prices["zimage"])
	}
}

func TestImageSearchSkipTotal(t *testing.T) {
	img := &GeneratedImage{
		ID:       "test-skip-total-image",
		Prompt:   "benchmark fairy gallery image",
		Width:    1024,
		Height:   1024,
		FilePath: "test/skip-total.webp",
		Model:    "zimage",
		Steps:    8,
	}
	if err := dbConn.InsertGeneratedImage(img); err != nil {
		t.Fatalf("insert image: %v", err)
	}

	status, body := doGet(t, "/api/images?page=1&per_page=1&skip_total=true")
	if status != 200 {
		t.Fatalf("expected 200, got %d: %#v", status, body)
	}
	if body["total"].(float64) != 0 {
		t.Fatalf("skip_total should avoid COUNT(*) and return total 0, got %#v", body["total"])
	}
	images, ok := body["images"].([]interface{})
	if !ok || len(images) != 1 {
		t.Fatalf("expected one image, got %#v", body["images"])
	}
}

func TestZImageRequestPricingTiers(t *testing.T) {
	prevDefaultSteps := zimageDefaultSteps
	prevHighStepPrice := zimageHighStepPriceUSD
	prevBasePrice := servicePricesUSD["zimage"]
	t.Cleanup(func() {
		zimageDefaultSteps = prevDefaultSteps
		zimageHighStepPriceUSD = prevHighStepPrice
		servicePricesUSD["zimage"] = prevBasePrice
	})

	zimageDefaultSteps = 8
	zimageHighStepPriceUSD = 0.10
	servicePricesUSD["zimage"] = 0.04

	cases := []struct {
		name  string
		steps int
		want  float64
	}{
		{name: "default", steps: 0, want: 0.04},
		{name: "below high tier", steps: 19, want: 0.04},
		{name: "twenty steps", steps: 20, want: 0.10},
		{name: "forty steps", steps: 40, want: 0.10},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := getRequestServicePriceUSD(ServiceUsageRequest{
				Service:  "zimage",
				NumSteps: tc.steps,
			})
			if got != tc.want {
				t.Fatalf("expected zimage USD price %.2f, got %.2f", tc.want, got)
			}
		})
	}
}

// ---- CUTE Price ----

func TestCutePrice(t *testing.T) {
	status, body := doGet(t, "/api/cute-price")
	if status != 200 {
		t.Fatalf("expected 200, got %d", status)
	}
	// Should have price fields even if 0
	if _, ok := body["cute_price_usd"]; !ok {
		t.Fatal("expected cute_price_usd field")
	}
}

// ---- Service Request ----

func TestService_MissingAuth(t *testing.T) {
	status, body := doPost(t, "/api/service", map[string]string{
		"prompt": "test",
	})
	if status != 401 {
		t.Fatalf("expected 401 for missing auth, got %d: %v", status, body)
	}
}

func TestService_UnknownService(t *testing.T) {
	wallet := fmt.Sprintf("SvcTest_%d", time.Now().UnixNano())
	doPost(t, "/api/auth/wallet", map[string]string{"wallet_address": wallet})

	status, body := doPost(t, "/api/service", map[string]interface{}{
		"wallet_address": wallet,
		"service":        "nonexistent",
	})
	if status != 400 {
		t.Fatalf("expected 400 for unknown service, got %d: %v", status, body)
	}
}

func TestService_InsufficientCredits(t *testing.T) {
	wallet := fmt.Sprintf("NoCred_%d", time.Now().UnixNano())
	doPost(t, "/api/auth/wallet", map[string]string{"wallet_address": wallet})

	status, body := doPost(t, "/api/service", map[string]interface{}{
		"wallet_address": wallet,
		"service":        "zimage",
		"prompt":         "test",
	})
	// Should fail with 402 (insufficient) or 503 (pricing unavailable if CUTE price is 0)
	if status != 402 && status != 503 {
		t.Fatalf("expected 402 or 503, got %d: %v", status, body)
	}
}

func TestService_APIKeyAuth(t *testing.T) {
	wallet := fmt.Sprintf("APIKeyTest_%d", time.Now().UnixNano())
	_, authBody := doPost(t, "/api/auth/wallet", map[string]string{"wallet_address": wallet})
	apiKey := authBody["api_key"].(string)

	// Use API key in Authorization header (no wallet_address in body)
	status, body := doPost(t, "/api/service", map[string]interface{}{
		"service": "zimage",
		"prompt":  "test",
	}, "Authorization", "Bearer "+apiKey)

	// Should get 402 (insufficient credits) or 503 (pricing unavailable), not 401
	if status == 401 {
		t.Fatalf("API key auth failed: got 401: %v", body)
	}
}

func TestService_InvalidAPIKey(t *testing.T) {
	status, body := doPost(t, "/api/service", map[string]interface{}{
		"service": "zimage",
		"prompt":  "test",
	}, "Authorization", "Bearer cutedsl_invalid_key_12345")

	if status != 401 {
		t.Fatalf("expected 401 for invalid API key, got %d: %v", status, body)
	}
}

func TestService_DefaultsToZImage(t *testing.T) {
	wallet := fmt.Sprintf("NoSvc_%d", time.Now().UnixNano())
	doPost(t, "/api/auth/wallet", map[string]string{"wallet_address": wallet})

	status, body := doPost(t, "/api/service", map[string]interface{}{
		"wallet_address": wallet,
		"prompt":         "test",
	})
	if status != 402 && status != 503 {
		t.Fatalf("expected default zimage billing path to return 402 or 503, got %d: %v", status, body)
	}
}

// ---- Billing History ----

func TestBillingHistory_UnknownWallet(t *testing.T) {
	status, body := doGet(t, "/api/billing-history?wallet=Unknown99999999999999999999999")
	if status != 200 {
		t.Fatalf("expected 200, got %d", status)
	}
	events := body["events"].([]interface{})
	if len(events) != 0 {
		t.Fatalf("expected empty events for unknown wallet, got %d", len(events))
	}
}

func TestBillingHistory_MissingParam(t *testing.T) {
	status, _ := doGet(t, "/api/billing-history")
	if status != 400 {
		t.Fatalf("expected 400, got %d", status)
	}
}

func TestBillingHistory_RegisteredWallet(t *testing.T) {
	wallet := fmt.Sprintf("BillHist_%d", time.Now().UnixNano())
	doPost(t, "/api/auth/wallet", map[string]string{"wallet_address": wallet})

	status, body := doGet(t, "/api/billing-history?wallet="+wallet)
	if status != 200 {
		t.Fatalf("expected 200, got %d", status)
	}
	events, ok := body["events"].([]interface{})
	if !ok {
		// events may be nil for empty list
		return
	}
	if len(events) != 0 {
		t.Fatalf("expected 0 events for new wallet, got %d", len(events))
	}
}

// ---- Training Status ----

func TestTrainStatus_NotFound(t *testing.T) {
	status, _ := doGet(t, "/api/train/nonexistent-job-id")
	// Should get 502 (backend unavailable since inference isn't running) or 404
	if status != 502 && status != 404 {
		t.Fatalf("expected 502 or 404, got %d", status)
	}
}

// ---- Crypto Checkout ----

func TestCryptoCheckout_MissingFields(t *testing.T) {
	status, body := doPost(t, "/api/crypto-checkout", map[string]interface{}{})
	// 400 for validation error, or 503 if crypto not configured in test env
	if status != 400 && status != 503 {
		t.Fatalf("expected 400 or 503, got %d: %v", status, body)
	}
}

func TestCryptoCheckout_UnregisteredWallet(t *testing.T) {
	status, body := doPost(t, "/api/crypto-checkout", map[string]interface{}{
		"wallet_address": "UnregisteredCheckout999999999999999",
		"method":         "cute",
		"amount":         10.0,
	})
	// Should fail - wallet not registered, or pricing unavailable
	if status == 200 {
		t.Fatalf("expected error for unregistered wallet, got 200: %v", body)
	}
}

func TestSwapSendTransactionValidation(t *testing.T) {
	status, _ := doPost(t, "/api/swap/send_transaction", map[string]interface{}{})
	if status != 400 {
		t.Fatalf("expected 400 for missing signed transaction, got %d", status)
	}

	status, _ = doPost(t, "/api/swap/send_transaction", map[string]interface{}{
		"signed_transaction": "not-base64",
	})
	if status != 400 {
		t.Fatalf("expected 400 for invalid signed transaction, got %d", status)
	}
}

// ---- 404 ----

func TestNotFound(t *testing.T) {
	status, body := doGet(t, "/api/nonexistent")
	if status != 404 {
		t.Fatalf("expected 404, got %d: %v", status, body)
	}
}

// ---- CORS ----

func TestCORSHeaders(t *testing.T) {
	req, _ := http.NewRequest("OPTIONS", baseURL()+"/api/health", nil)
	req.Header.Set("Origin", "http://localhost:3000")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 204 {
		t.Fatalf("expected 204 for OPTIONS, got %d", resp.StatusCode)
	}
	allow := resp.Header.Get("Access-Control-Allow-Origin")
	if allow != "http://localhost:3000" {
		t.Fatalf("expected CORS origin http://localhost:3000, got %s", allow)
	}
	methods := resp.Header.Get("Access-Control-Allow-Methods")
	if methods == "" {
		t.Fatal("expected Access-Control-Allow-Methods header")
	}
}

// ---- Full Auth Flow ----

func TestFullAuthFlow(t *testing.T) {
	wallet := fmt.Sprintf("FullFlow_%d", time.Now().UnixNano())

	// 1. Register
	status, authBody := doPost(t, "/api/auth/wallet", map[string]string{
		"wallet_address": wallet,
	})
	if status != 200 {
		t.Fatalf("register failed: %d", status)
	}
	apiKey := authBody["api_key"].(string)
	if !strings.HasPrefix(apiKey, "cutedsl_") {
		t.Fatalf("bad api key format: %s", apiKey)
	}

	// 2. Check balance
	status, balBody := doGet(t, "/api/balance?wallet="+wallet)
	if status != 200 {
		t.Fatalf("balance failed: %d", status)
	}
	if balBody["credits"].(float64) != 0 {
		t.Fatalf("expected 0 credits, got %v", balBody["credits"])
	}

	// 3. Check billing history (empty)
	status, histBody := doGet(t, "/api/billing-history?wallet="+wallet)
	if status != 200 {
		t.Fatalf("billing history failed: %d", status)
	}
	if events, ok := histBody["events"].([]interface{}); ok && len(events) != 0 {
		t.Fatalf("expected 0 billing events, got %d", len(events))
	}

	// 4. Try service with API key auth (should fail with insufficient credits, not 401)
	status, svcBody := doPost(t, "/api/service", map[string]interface{}{
		"service": "gemma4",
		"messages": []map[string]string{
			{"role": "user", "content": "hi"},
		},
	}, "Authorization", "Bearer "+apiKey)

	if status == 401 {
		t.Fatalf("API key auth should work, got 401: %v", svcBody)
	}
	// 402 or 503 are both acceptable (no credits or pricing unavailable)
	if status != 402 && status != 503 {
		t.Logf("service returned %d (expected 402/503 - CUTE price may be 0): %v", status, svcBody)
	}

	// 5. Get pricing
	status, priceBody := doGet(t, "/api/pricing")
	if status != 200 {
		t.Fatalf("pricing failed: %d", status)
	}
	if priceBody["pricing"] == nil {
		t.Fatal("missing pricing in response")
	}
}

// ---- Content Type ----

func TestAPIResponsesAreJSON(t *testing.T) {
	paths := []string{
		"/api/health",
		"/api/pricing",
		"/api/balance?wallet=TestContentType",
	}
	for _, path := range paths {
		resp, err := http.Get(baseURL() + path)
		if err != nil {
			t.Fatalf("GET %s: %v", path, err)
		}
		ct := resp.Header.Get("Content-Type")
		resp.Body.Close()
		if !strings.Contains(ct, "application/json") {
			t.Errorf("GET %s: expected application/json, got %s", path, ct)
		}
	}
}
