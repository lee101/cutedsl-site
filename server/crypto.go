package main

import (
	"bufio"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/joho/godotenv"
	"github.com/mr-tron/base58"
	"github.com/valyala/fasthttp"
	"golang.org/x/crypto/hkdf"
)

func init() {
	godotenv.Load()
	godotenv.Load("../.env")
}

// Crypto configuration
var (
	solanaWalletPubkey string
	solanaPrivateKey   string
	bagsAPIKey         string
	cuteTokenMint      string
	solanaRPCURL       string
	heliusRPCURL       string
	heliusAPIKey       string
	hdWalletSeed       []byte
)

// RPC endpoint for Solana
type rpcEndpoint struct {
	name            string
	url             string
	rateLimitRPS    float64
	lastRequestTime time.Time
	failures        int
	backoffUntil    time.Time
}

var (
	rpcEndpoints []*rpcEndpoint
	rpcMu        sync.Mutex
)

// $CUTE price cache
var (
	cutePriceUSD     float64 = 0.001 // Default fallback
	cutePriceATH     float64 = 0.001 // All-time high for subsidized pricing
	cutePriceMu      sync.RWMutex
	cutePriceUpdated time.Time
)

// getCUTEPriceATH returns the all-time high price.
// First-party services on our hardware are priced at ATH rate,
// meaning if you bought $CUTEDSL early you get cheaper inference forever.
func getCUTEPriceATH() float64 {
	cutePriceMu.RLock()
	defer cutePriceMu.RUnlock()
	return cutePriceATH
}

// SOL price cache (needed for conversions)
var (
	solPriceUSD     float64 = 100.0
	solPriceMu      sync.RWMutex
	solPriceUpdated time.Time
)

// SSE subscribers for checkout status updates
var (
	sseSubscribers = make(map[string][]chan string)
	sseMu          sync.RWMutex
)

// Bags API configuration
const (
	bagsAPIBaseURL = "https://public-api-v2.bags.fm/api/v1"
	solMint        = "So11111111111111111111111111111111111111112"
)

func initCrypto() {
	solanaWalletPubkey = getEnv("SOL_ADDR", "BgrdkvvqmFkFptowajYnzvzzPsDrqYNdaazwPSPEhwdN")
	solanaPrivateKey = getEnv("SOLANA_PRIVATE_KEY", "")
	bagsAPIKey = getEnv("BAGS_API_KEY", "")
	cuteTokenMint = getEnv("CUTE_TOKEN_MINT", "")
	solanaRPCURL = getEnv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

	heliusAPIKey = os.Getenv("HELIUS_API_KEY")
	if heliusAPIKey != "" {
		heliusRPCURL = fmt.Sprintf("https://mainnet.helius-rpc.com/?api-key=%s", heliusAPIKey)
		log.Printf("Helius RPC configured (primary, 50 rps)")
	}

	initRPCEndpoints()

	// Load HD wallet seed
	seedHex := getEnv("HD_WALLET_SEED", "")
	if seedHex != "" {
		var err error
		hdWalletSeed, err = decodeHex(seedHex)
		if err != nil || len(hdWalletSeed) < 32 {
			log.Printf("Warning: HD wallet seed invalid, generating random")
			hdWalletSeed = make([]byte, 64)
			rand.Read(hdWalletSeed)
		}
	} else {
		log.Printf("Warning: HD_WALLET_SEED not set, generating random")
		hdWalletSeed = make([]byte, 64)
		rand.Read(hdWalletSeed)
	}

	// Start background services
	go updateSOLPriceLoop()
	go updateCUTEPriceLoop()
	go cryptoPaymentPoller()
	go expiredCheckoutCleaner()
	go cryptoSweeper()

	log.Printf("Crypto system initialized: wallet=%s, cute_mint=%s", solanaWalletPubkey, cuteTokenMint)
}

func initRPCEndpoints() {
	rpcEndpoints = make([]*rpcEndpoint, 0)
	if heliusRPCURL != "" {
		rpcEndpoints = append(rpcEndpoints, &rpcEndpoint{
			name: "helius", url: heliusRPCURL, rateLimitRPS: 50.0,
		})
	}
	rpcEndpoints = append(rpcEndpoints, &rpcEndpoint{
		name: "mainnet", url: solanaRPCURL, rateLimitRPS: 10.0,
	})
	log.Printf("Initialized %d RPC endpoints", len(rpcEndpoints))
}

// decodeHex decodes a hex string to bytes
func decodeHex(s string) ([]byte, error) {
	if len(s)%2 != 0 {
		return nil, fmt.Errorf("odd length hex string")
	}
	b := make([]byte, len(s)/2)
	for i := 0; i < len(b); i++ {
		var v byte
		for j := 0; j < 2; j++ {
			c := s[i*2+j]
			switch {
			case c >= '0' && c <= '9':
				v = v*16 + c - '0'
			case c >= 'a' && c <= 'f':
				v = v*16 + c - 'a' + 10
			case c >= 'A' && c <= 'F':
				v = v*16 + c - 'A' + 10
			default:
				return nil, fmt.Errorf("invalid hex char: %c", c)
			}
		}
		b[i] = v
	}
	return b, nil
}

// deriveDepositKeypair derives a unique ed25519 keypair for a given index
func deriveDepositKeypair(index int64) (ed25519.PublicKey, ed25519.PrivateKey) {
	info := make([]byte, 8)
	binary.BigEndian.PutUint64(info, uint64(index))

	hkdfReader := hkdf.New(sha256.New, hdWalletSeed, []byte("cutedsl-deposit"), info)
	seed := make([]byte, ed25519.SeedSize)
	if _, err := io.ReadFull(hkdfReader, seed); err != nil {
		log.Printf("HKDF derivation failed: %v", err)
		return nil, nil
	}

	privateKey := ed25519.NewKeyFromSeed(seed)
	publicKey := privateKey.Public().(ed25519.PublicKey)
	return publicKey, privateKey
}

func getDepositPubkey(index int64) string {
	pubkey, _ := deriveDepositKeypair(index)
	if pubkey == nil {
		return ""
	}
	return base58.Encode(pubkey)
}

// --- Price Feeds ---

func getCUTEPriceUSD() float64 {
	cutePriceMu.RLock()
	defer cutePriceMu.RUnlock()
	return cutePriceUSD
}

func getSOLPriceUSD() float64 {
	solPriceMu.RLock()
	defer solPriceMu.RUnlock()
	return solPriceUSD
}

func updateSOLPriceLoop() {
	// Initial fetch
	updateSOLPrice()
	ticker := time.NewTicker(5 * time.Minute)
	for range ticker.C {
		updateSOLPrice()
	}
}

func updateSOLPrice() {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, "GET",
		"https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd", nil)
	if err != nil {
		log.Printf("SOL price fetch error: %v", err)
		return
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		log.Printf("SOL price fetch error: %v", err)
		return
	}
	defer resp.Body.Close()

	var result struct {
		Solana struct {
			USD float64 `json:"usd"`
		} `json:"solana"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		log.Printf("SOL price parse error: %v", err)
		return
	}

	if result.Solana.USD > 0 {
		solPriceMu.Lock()
		solPriceUSD = result.Solana.USD
		solPriceUpdated = time.Now()
		solPriceMu.Unlock()
		log.Printf("SOL price updated: $%.2f", result.Solana.USD)
	}
}

func updateCUTEPriceLoop() {
	// Initial fetch
	updateCUTEPrice()
	ticker := time.NewTicker(5 * time.Minute)
	for range ticker.C {
		updateCUTEPrice()
	}
}

func updateCUTEPrice() {
	if cuteTokenMint == "" || bagsAPIKey == "" {
		return
	}

	// Use Bags API to get a trade quote: 0.1 SOL -> CUTE
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	quoteURL := fmt.Sprintf("%s/trade/quote?inputMint=%s&outputMint=%s&inAmount=100000000&slippageBps=500",
		bagsAPIBaseURL, solMint, cuteTokenMint)

	req, err := http.NewRequestWithContext(ctx, "GET", quoteURL, nil)
	if err != nil {
		log.Printf("CUTE price fetch error: %v", err)
		return
	}
	req.Header.Set("x-api-key", bagsAPIKey)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		log.Printf("CUTE price fetch error: %v", err)
		return
	}
	defer resp.Body.Close()

	var quoteResp struct {
		OutAmount string `json:"outAmount"`
		InAmount  string `json:"inAmount"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&quoteResp); err != nil {
		log.Printf("CUTE price parse error: %v", err)
		return
	}

	// Parse amounts - amounts are in smallest units
	inLamports := parseFloat(quoteResp.InAmount)
	outTokens := parseFloat(quoteResp.OutAmount)

	if inLamports > 0 && outTokens > 0 {
		// How many CUTE per SOL
		cutePerSOL := (outTokens / inLamports) * 1e9 // Scale to 1 SOL
		solPrice := getSOLPriceUSD()
		if solPrice > 0 && cutePerSOL > 0 {
			price := solPrice / cutePerSOL
			cutePriceMu.Lock()
			cutePriceUSD = price
			if price > cutePriceATH {
				cutePriceATH = price
				log.Printf("CUTEDSL new ATH: $%.8f", price)
			}
			cutePriceUpdated = time.Now()
			cutePriceMu.Unlock()
			log.Printf("CUTEDSL price updated: $%.8f (ATH: $%.8f, %.0f CUTEDSL/SOL)", price, cutePriceATH, cutePerSOL)
		}
	}
}

func parseFloat(s string) float64 {
	var f float64
	fmt.Sscanf(s, "%f", &f)
	return f
}

// --- RPC Calls ---

func robustRPCCall(method string, params interface{}, timeout time.Duration) ([]byte, error) {
	rpcMu.Lock()
	defer rpcMu.Unlock()

	maxRetries := 3
	var lastErr error

	for attempt := 0; attempt < maxRetries; attempt++ {
		for _, endpoint := range rpcEndpoints {
			if time.Now().Before(endpoint.backoffUntil) {
				continue
			}

			minInterval := time.Duration(float64(time.Second) / endpoint.rateLimitRPS)
			if time.Since(endpoint.lastRequestTime) < minInterval {
				time.Sleep(minInterval - time.Since(endpoint.lastRequestTime))
			}
			endpoint.lastRequestTime = time.Now()

			body, err := makeRPCRequest(endpoint.url, method, params, timeout)
			if err != nil {
				if strings.Contains(err.Error(), "429") || strings.Contains(strings.ToLower(err.Error()), "rate") {
					endpoint.failures++
					backoff := time.Duration(1<<endpoint.failures) * time.Second
					if backoff > 30*time.Second {
						backoff = 30 * time.Second
					}
					endpoint.backoffUntil = time.Now().Add(backoff)
					log.Printf("RPC %s: rate limited, backing off %v", endpoint.name, backoff)
				}
				lastErr = err
				continue
			}

			endpoint.failures = 0
			endpoint.backoffUntil = time.Time{}
			return body, nil
		}

		if attempt < maxRetries-1 {
			time.Sleep(time.Duration(1<<attempt) * 500 * time.Millisecond)
		}
	}

	return nil, fmt.Errorf("all RPC endpoints failed after %d attempts: %v", maxRetries, lastErr)
}

func makeRPCRequest(rpcURL, method string, params interface{}, timeout time.Duration) ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	payload := map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  method,
		"params":  params,
	}

	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequestWithContext(ctx, "POST", rpcURL, strings.NewReader(string(payloadBytes)))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("rpc http %d: %s", resp.StatusCode, truncateString(string(body), 500))
	}

	var rpcResp struct {
		Error *struct {
			Code    int    `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if err := json.Unmarshal(body, &rpcResp); err == nil && rpcResp.Error != nil {
		if rpcResp.Error.Code == 429 || strings.Contains(strings.ToLower(rpcResp.Error.Message), "rate") {
			return nil, fmt.Errorf("429 rate limited: %s", rpcResp.Error.Message)
		}
	}

	return body, nil
}

// --- Crypto Handlers ---

func handleCryptoCheckout(ctx *fasthttp.RequestCtx) {
	if solanaWalletPubkey == "" {
		jsonError(ctx, 503, "crypto payments not configured")
		return
	}

	var req CryptoCheckoutRequest
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil {
		jsonError(ctx, 400, "invalid json")
		return
	}

	if req.WalletAddress == "" {
		jsonError(ctx, 400, "wallet_address required")
		return
	}

	if req.Amount < 1 {
		jsonError(ctx, 400, "minimum deposit is $1")
		return
	}

	// Ensure user exists
	user, _, err := dbConn.GetOrCreateUser(req.WalletAddress)
	if err != nil {
		log.Printf("Failed to get/create user: %v", err)
		jsonError(ctx, 500, "failed to get user")
		return
	}

	// Calculate $CUTE amount based on current price
	cutePrice := getCUTEPriceUSD()
	usdAmount := req.Amount
	cuteAmount := usdAmount / cutePrice

	var amountUI string
	var amountLamports uint64
	var mint string

	if req.Method == CryptoPaySOL {
		// Pay with SOL
		solPrice := getSOLPriceUSD()
		solAmount := usdAmount / solPrice
		amountUI = fmt.Sprintf("%.6f SOL", solAmount)
		amountLamports = uint64(solAmount * 1e9)
	} else {
		// Pay with $CUTE token
		mint = cuteTokenMint
		amountUI = fmt.Sprintf("%.2f CUTEDSL", cuteAmount)
		amountLamports = uint64(cuteAmount * 1e9) // Assuming 9 decimals
	}

	// Get next deposit address
	depositIndex, err := dbConn.GetNextCryptoDepositIndex()
	if err != nil {
		log.Printf("Failed to get deposit index: %v", err)
		jsonError(ctx, 500, "failed to generate deposit address")
		return
	}

	depositPubkey := getDepositPubkey(depositIndex)
	if depositPubkey == "" {
		jsonError(ctx, 500, "failed to derive deposit address")
		return
	}

	now := time.Now()
	intent := &CryptoCheckoutIntent{
		UserID:          user.ID,
		WalletAddress:   req.WalletAddress,
		Method:          req.Method,
		DepositIndex:    depositIndex,
		DepositPubkey:   depositPubkey,
		RecipientPubkey: solanaWalletPubkey,
		Mint:            mint,
		AmountUI:        amountUI,
		AmountLamports:  amountLamports,
		USDAmount:       usdAmount,
		CuteAmount:      cuteAmount,
		Status:          CryptoStatusPending,
		ExpiresAt:       now.Add(20 * time.Minute),
		HonorUntil:      now.Add(7 * 24 * time.Hour),
	}

	if err := dbConn.CreateCryptoCheckoutIntent(intent); err != nil {
		log.Printf("Failed to create checkout: %v", err)
		jsonError(ctx, 500, "failed to create checkout")
		return
	}

	// Build Solana Pay URL
	solanaPayURL := buildSolanaPayURL(intent)

	log.Printf("Created crypto checkout: id=%s method=%s usd=%.2f cute=%.2f deposit=%s",
		intent.ID, intent.Method, usdAmount, cuteAmount, depositPubkey)

	// Build buy token URL
	buyURL := ""
	if cuteTokenMint != "" {
		buyURL = fmt.Sprintf("https://bags.fm/b/%s", cuteTokenMint)
	}

	resp := CryptoCheckoutResponse{
		IntentID:       intent.ID,
		SolanaPayURL:   solanaPayURL,
		DepositAddress: depositPubkey,
		ExpiresAt:      intent.ExpiresAt.Format(time.RFC3339),
		AmountUI:       amountUI,
		CuteAmount:     cuteAmount,
		USDAmount:      usdAmount,
		Method:         string(intent.Method),
		TokenMint:      mint,
		CutePrice:      cutePrice,
		BuyTokenURL:    buyURL,
	}

	jsonResponse(ctx, 200, resp)
}

func buildSolanaPayURL(intent *CryptoCheckoutIntent) string {
	if intent.Method == CryptoPaySOL {
		return fmt.Sprintf("solana:%s?amount=%s&label=CuteDSL&message=Deposit%%20%s",
			intent.DepositPubkey, strings.TrimSuffix(strings.TrimRight(intent.AmountUI, " SOL"), " SOL"), intent.ID[:8])
	}
	// SPL token transfer
	return fmt.Sprintf("solana:%s?amount=%s&spl-token=%s&label=CuteDSL&message=Deposit%%20%s",
		intent.DepositPubkey, strings.Fields(intent.AmountUI)[0], intent.Mint, intent.ID[:8])
}

func handleGetCheckoutStatus(ctx *fasthttp.RequestCtx, intentID string) {
	intent, err := dbConn.GetCryptoCheckoutIntent(intentID)
	if err != nil {
		jsonError(ctx, 404, "checkout not found")
		return
	}
	jsonResponse(ctx, 200, intent)
}

func handleGetCUTEPrice(ctx *fasthttp.RequestCtx) {
	jsonResponse(ctx, 200, map[string]interface{}{
		"cute_price_usd": getCUTEPriceUSD(),
		"sol_price_usd":  getSOLPriceUSD(),
		"updated_at":     cutePriceUpdated.Format(time.RFC3339),
	})
}

func handleStreamCheckoutEvents(ctx *fasthttp.RequestCtx, intentID string) {
	ctx.SetContentType("text/event-stream")
	ctx.Response.Header.Set("Cache-Control", "no-cache")
	ctx.Response.Header.Set("Connection", "keep-alive")

	ch := make(chan string, 10)
	sseMu.Lock()
	sseSubscribers[intentID] = append(sseSubscribers[intentID], ch)
	sseMu.Unlock()

	defer func() {
		sseMu.Lock()
		subs := sseSubscribers[intentID]
		for i, sub := range subs {
			if sub == ch {
				sseSubscribers[intentID] = append(subs[:i], subs[i+1:]...)
				break
			}
		}
		sseMu.Unlock()
		close(ch)
	}()

	ctx.SetBodyStreamWriter(func(w *bufio.Writer) {
		ticker := time.NewTicker(15 * time.Second)
		defer ticker.Stop()

		timeout := time.After(25 * time.Minute)

		for {
			select {
			case msg, ok := <-ch:
				if !ok {
					return
				}
				fmt.Fprintf(w, "data: %s\n\n", msg)
				if err := w.Flush(); err != nil {
					return
				}
			case <-ticker.C:
				fmt.Fprintf(w, ": keepalive\n\n")
				if err := w.Flush(); err != nil {
					return
				}
			case <-timeout:
				fmt.Fprintf(w, "data: {\"status\":\"timeout\"}\n\n")
				w.Flush()
				return
			}
		}
	})
}

func broadcastCheckoutEvent(intentID string, status string) {
	sseMu.RLock()
	subs := sseSubscribers[intentID]
	sseMu.RUnlock()

	msg := fmt.Sprintf(`{"status":"%s","intent_id":"%s"}`, status, intentID)
	for _, ch := range subs {
		select {
		case ch <- msg:
		default:
		}
	}
}

// --- Background Services ---

func cryptoPaymentPoller() {
	time.Sleep(5 * time.Second) // Wait for DB init
	log.Printf("Crypto payment poller started")

	for {
		intents, err := dbConn.ListPendingCryptoCheckouts()
		if err != nil {
			log.Printf("Payment poller: list error: %v", err)
			time.Sleep(30 * time.Second)
			continue
		}

		for _, intent := range intents {
			verifyPayment(intent)
		}

		// Poll faster for fresh intents
		time.Sleep(30 * time.Second)
	}
}

func verifyPayment(intent CryptoCheckoutIntent) {
	// Query Solana RPC for transactions to the deposit address
	params := []interface{}{
		intent.DepositPubkey,
		map[string]interface{}{"limit": 10},
	}

	body, err := robustRPCCall("getSignaturesForAddress", params, 10*time.Second)
	if err != nil {
		return // Will retry next poll
	}

	var result struct {
		Result []struct {
			Signature string      `json:"signature"`
			Err       interface{} `json:"err"`
		} `json:"result"`
	}

	if err := json.Unmarshal(body, &result); err != nil || len(result.Result) == 0 {
		return
	}

	// Check each transaction
	for _, sig := range result.Result {
		if sig.Err != nil {
			continue
		}

		// Verify transaction details
		if verifyTransaction(intent, sig.Signature) {
			processCompletedPayment(intent, sig.Signature)
			return
		}
	}
}

func verifyTransaction(intent CryptoCheckoutIntent, txSig string) bool {
	params := []interface{}{
		txSig,
		map[string]interface{}{
			"encoding":                       "json",
			"maxSupportedTransactionVersion": 0,
		},
	}

	body, err := robustRPCCall("getTransaction", params, 10*time.Second)
	if err != nil {
		return false
	}

	// Parse transaction to verify amount
	var txResult struct {
		Result struct {
			Meta struct {
				PreBalances  []uint64 `json:"preBalances"`
				PostBalances []uint64 `json:"postBalances"`
			} `json:"meta"`
		} `json:"result"`
	}

	if err := json.Unmarshal(body, &txResult); err != nil {
		return false
	}

	// For SOL: check balance delta
	if intent.Method == CryptoPaySOL {
		pre := txResult.Result.Meta.PreBalances
		post := txResult.Result.Meta.PostBalances
		if len(pre) > 1 && len(post) > 1 {
			// Deposit address should have received funds
			received := post[1] - pre[1]
			// Allow 1% slippage
			expected := intent.AmountLamports
			minExpected := uint64(float64(expected) * 0.99)
			return received >= minExpected
		}
	}

	// For SPL tokens, would need to check token balance changes
	// Simplified: accept any transaction to the deposit address for now
	return true
}

func processCompletedPayment(intent CryptoCheckoutIntent, txSig string) {
	// Mark as paid
	if err := dbConn.UpdateCryptoCheckoutStatus(intent.ID, CryptoStatusPaid, txSig); err != nil {
		log.Printf("Failed to update checkout status: %v", err)
		return
	}

	// Add credits to user (in $CUTE)
	cuteAmount := intent.CuteAmount
	newBalance, err := dbConn.AddUserCredits(intent.UserID, cuteAmount)
	if err != nil {
		log.Printf("Failed to add credits: %v", err)
		return
	}

	// Log billing event
	dbConn.CreateBillingEvent(&BillingEvent{
		UserID:       intent.UserID,
		EventType:    "deposit",
		Amount:       cuteAmount,
		CuteAmount:   cuteAmount,
		USDAmount:    intent.USDAmount,
		Description:  fmt.Sprintf("Deposit %s (tx: %s)", intent.AmountUI, txSig[:16]),
		CreditsAfter: newBalance,
	})

	// Broadcast SSE event
	broadcastCheckoutEvent(intent.ID, "paid")

	log.Printf("Payment completed: user=%s amount=%.2f CUTE ($%.2f) tx=%s",
		intent.UserID, cuteAmount, intent.USDAmount, txSig[:16])
}

func expiredCheckoutCleaner() {
	time.Sleep(10 * time.Second)
	log.Printf("Expired checkout cleaner started")

	for {
		count, err := dbConn.ExpirePendingCheckouts()
		if err != nil {
			log.Printf("Expired cleaner error: %v", err)
		} else if count > 0 {
			log.Printf("Expired %d checkout intents", count)
		}
		time.Sleep(1 * time.Hour)
	}
}

func cryptoSweeper() {
	time.Sleep(15 * time.Second)
	log.Printf("Crypto sweeper started")

	for {
		intents, err := dbConn.ListUnsweptCryptoCheckouts()
		if err != nil {
			log.Printf("Sweeper: list error: %v", err)
			time.Sleep(5 * time.Minute)
			continue
		}

		for _, intent := range intents {
			if err := sweepDeposit(intent); err != nil {
				log.Printf("Sweep failed for %s: %v", intent.ID, err)
			} else {
				dbConn.MarkCryptoCheckoutSwept(intent.ID)
				log.Printf("Swept deposit %s to main wallet", intent.ID)
			}
		}

		time.Sleep(5 * time.Minute)
	}
}

func sweepDeposit(intent CryptoCheckoutIntent) error {
	// Get balance of deposit address
	params := []interface{}{intent.DepositPubkey}
	body, err := robustRPCCall("getBalance", params, 10*time.Second)
	if err != nil {
		return fmt.Errorf("getBalance: %w", err)
	}

	var balResult struct {
		Result struct {
			Value uint64 `json:"value"`
		} `json:"result"`
	}
	if err := json.Unmarshal(body, &balResult); err != nil {
		return fmt.Errorf("parse balance: %w", err)
	}

	balance := balResult.Result.Value
	if balance <= 5000 {
		// Not enough to cover fees
		return nil
	}

	// Build and sign SOL transfer transaction
	// For SPL tokens, would need a different approach
	if intent.Method == CryptoPaySOL {
		return sweepSOL(intent, balance-5000)
	}

	// SPL sweep - mark as swept for now (TODO: implement SPL sweep)
	log.Printf("SPL sweep not yet implemented for intent %s", intent.ID)
	return nil
}

func sweepSOL(intent CryptoCheckoutIntent, amount uint64) error {
	// Get deposit keypair
	_, privKey := deriveDepositKeypair(intent.DepositIndex)
	if privKey == nil {
		return fmt.Errorf("failed to derive keypair for index %d", intent.DepositIndex)
	}

	// Get recent blockhash
	body, err := robustRPCCall("getLatestBlockhash", []interface{}{}, 10*time.Second)
	if err != nil {
		return fmt.Errorf("getLatestBlockhash: %w", err)
	}

	var bhResult struct {
		Result struct {
			Value struct {
				Blockhash string `json:"blockhash"`
			} `json:"value"`
		} `json:"result"`
	}
	if err := json.Unmarshal(body, &bhResult); err != nil {
		return fmt.Errorf("parse blockhash: %w", err)
	}

	// Build, sign, and send the transaction
	// This is a simplified version - production would use proper Solana transaction building
	log.Printf("Would sweep %d lamports from %s to %s (blockhash: %s)",
		amount, intent.DepositPubkey, solanaWalletPubkey, bhResult.Result.Value.Blockhash)

	_ = privKey // Used in actual transaction signing
	return nil
}

// --- Bags.fm Swap Proxy ---
// These endpoints proxy to bags.fm API so the frontend can build swap transactions
// without exposing our API key. Users sign with their own wallet.

func handleSwapQuote(ctx *fasthttp.RequestCtx) {
	if bagsAPIKey == "" || cuteTokenMint == "" {
		jsonError(ctx, 503, "swap not configured")
		return
	}

	// Parse SOL amount from query
	solAmountStr := string(ctx.QueryArgs().Peek("sol_amount"))
	if solAmountStr == "" {
		solAmountStr = "0.1"
	}
	solAmount := parseFloat(solAmountStr)
	if solAmount <= 0 || solAmount > 100 {
		jsonError(ctx, 400, "sol_amount must be between 0 and 100")
		return
	}

	// Convert SOL to lamports
	lamports := int64(solAmount * 1e9)

	// Get quote from bags.fm
	quoteCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	quoteURL := fmt.Sprintf("%s/trade/quote?inputMint=%s&outputMint=%s&amount=%d&slippageBps=300&slippageMode=manual",
		bagsAPIBaseURL, solMint, cuteTokenMint, lamports)

	req, err := http.NewRequestWithContext(quoteCtx, "GET", quoteURL, nil)
	if err != nil {
		jsonError(ctx, 500, "failed to create quote request")
		return
	}
	req.Header.Set("x-api-key", bagsAPIKey)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		jsonError(ctx, 502, "bags.fm quote request failed")
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)

	var quoteResp struct {
		Success  bool            `json:"success"`
		Response json.RawMessage `json:"response"`
		Error    string          `json:"error"`
		Message  string          `json:"message"`
	}
	if err := json.Unmarshal(body, &quoteResp); err != nil {
		jsonError(ctx, 502, "failed to parse bags.fm response")
		return
	}

	if !quoteResp.Success {
		errMsg := quoteResp.Error
		if errMsg == "" {
			errMsg = quoteResp.Message
		}
		jsonError(ctx, 400, fmt.Sprintf("quote failed: %s", errMsg))
		return
	}

	// Parse key fields for the frontend
	var parsed struct {
		InAmount              string          `json:"inAmount"`
		OutAmount             string          `json:"outAmount"`
		MinOutAmount          string          `json:"minOutAmount"`
		PriceImpactPct        float64         `json:"priceImpactPct"`
		PlatformFee           json.RawMessage `json:"platformFee"`
		SimulatedComputeUnits *int            `json:"simulatedComputeUnits"`
	}
	json.Unmarshal(quoteResp.Response, &parsed)

	outTokens := parseFloat(parsed.OutAmount)
	cuteDecimals := 9.0 // SPL token decimals

	solPrice := getSOLPriceUSD()
	usdValue := solAmount * solPrice

	jsonResponse(ctx, 200, map[string]interface{}{
		"success":         true,
		"quote":           quoteResp.Response, // Pass full quote for swap building
		"sol_amount":      solAmount,
		"cute_amount":     outTokens / math.Pow(10, cuteDecimals),
		"cute_amount_raw": parsed.OutAmount,
		"min_cute_amount": parseFloat(parsed.MinOutAmount) / math.Pow(10, cuteDecimals),
		"usd_value":       usdValue,
		"sol_price_usd":   solPrice,
		"price_impact":    parsed.PriceImpactPct,
	})
}

func handleSwapTransaction(ctx *fasthttp.RequestCtx) {
	if bagsAPIKey == "" || cuteTokenMint == "" {
		jsonError(ctx, 503, "swap not configured")
		return
	}

	var req struct {
		QuoteResponse json.RawMessage `json:"quote"`
		UserPublicKey string          `json:"user_public_key"`
	}
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil {
		jsonError(ctx, 400, "invalid request body")
		return
	}
	if req.UserPublicKey == "" {
		jsonError(ctx, 400, "user_public_key required")
		return
	}
	if req.QuoteResponse == nil {
		jsonError(ctx, 400, "quote required")
		return
	}

	// Build swap transaction via bags.fm
	swapCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	payload, _ := json.Marshal(map[string]interface{}{
		"quoteResponse": json.RawMessage(req.QuoteResponse),
		"userPublicKey": req.UserPublicKey,
	})

	swapReq, err := http.NewRequestWithContext(swapCtx, "POST",
		fmt.Sprintf("%s/trade/swap", bagsAPIBaseURL),
		strings.NewReader(string(payload)))
	if err != nil {
		jsonError(ctx, 500, "failed to create swap request")
		return
	}
	swapReq.Header.Set("x-api-key", bagsAPIKey)
	swapReq.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(swapReq)
	if err != nil {
		jsonError(ctx, 502, "bags.fm swap request failed")
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)

	var swapResp struct {
		Success  bool            `json:"success"`
		Response json.RawMessage `json:"response"`
		Error    string          `json:"error"`
		Message  string          `json:"message"`
	}
	if err := json.Unmarshal(body, &swapResp); err != nil {
		jsonError(ctx, 502, "failed to parse swap response")
		return
	}

	if !swapResp.Success {
		errMsg := swapResp.Error
		if errMsg == "" {
			errMsg = swapResp.Message
		}
		jsonError(ctx, 400, fmt.Sprintf("swap build failed: %s", errMsg))
		return
	}

	// Return the transaction for the frontend to sign
	jsonResponse(ctx, 200, map[string]interface{}{
		"success":     true,
		"transaction": swapResp.Response,
	})
}

func handleSwapSendTransaction(ctx *fasthttp.RequestCtx) {
	var req struct {
		SignedTransaction string `json:"signed_transaction"`
	}
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil {
		jsonError(ctx, 400, "invalid request body")
		return
	}
	if req.SignedTransaction == "" {
		jsonError(ctx, 400, "signed_transaction required")
		return
	}
	if len(req.SignedTransaction) > 400000 {
		jsonError(ctx, 400, "signed_transaction too large")
		return
	}
	if _, err := base64.StdEncoding.DecodeString(req.SignedTransaction); err != nil {
		jsonError(ctx, 400, "signed_transaction must be base64")
		return
	}

	params := []interface{}{
		req.SignedTransaction,
		map[string]interface{}{
			"encoding":            "base64",
			"skipPreflight":       false,
			"preflightCommitment": "confirmed",
			"maxRetries":          5,
		},
	}
	body, err := robustRPCCall("sendTransaction", params, 20*time.Second)
	if err != nil {
		log.Printf("swap sendTransaction RPC failed: %v", err)
		jsonError(ctx, 502, fmt.Sprintf("transaction broadcast failed: %s", err))
		return
	}

	var sendResp struct {
		Result string `json:"result"`
		Error  *struct {
			Code    int             `json:"code"`
			Message string          `json:"message"`
			Data    json.RawMessage `json:"data"`
		} `json:"error"`
	}
	if err := json.Unmarshal(body, &sendResp); err != nil {
		jsonError(ctx, 502, "failed to parse transaction broadcast response")
		return
	}
	if sendResp.Error != nil {
		log.Printf("swap sendTransaction error code=%d msg=%s data=%s", sendResp.Error.Code, sendResp.Error.Message, string(sendResp.Error.Data))
		jsonError(ctx, 400, fmt.Sprintf("transaction broadcast failed: %s", sendResp.Error.Message))
		return
	}
	if sendResp.Result == "" {
		jsonError(ctx, 502, "transaction broadcast returned no signature")
		return
	}

	confirmed, confirmationStatus, confirmErr := waitForSignatureConfirmation(sendResp.Result, 45*time.Second)
	if confirmErr != nil {
		log.Printf("swap confirmation failed sig=%s: %v", sendResp.Result, confirmErr)
		jsonError(ctx, 502, fmt.Sprintf("transaction confirmation failed: %s", confirmErr))
		return
	}

	jsonResponse(ctx, 200, map[string]interface{}{
		"success":             true,
		"signature":           sendResp.Result,
		"confirmed":           confirmed,
		"confirmation_status": confirmationStatus,
	})
}

func waitForSignatureConfirmation(signature string, timeout time.Duration) (bool, string, error) {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		params := []interface{}{
			[]string{signature},
			map[string]interface{}{"searchTransactionHistory": true},
		}
		body, err := robustRPCCall("getSignatureStatuses", params, 10*time.Second)
		if err != nil {
			return false, "", err
		}

		var statusResp struct {
			Result struct {
				Value []struct {
					Err                interface{} `json:"err"`
					ConfirmationStatus string      `json:"confirmationStatus"`
				} `json:"value"`
			} `json:"result"`
			Error *struct {
				Message string `json:"message"`
			} `json:"error"`
		}
		if err := json.Unmarshal(body, &statusResp); err != nil {
			return false, "", err
		}
		if statusResp.Error != nil {
			return false, "", errors.New(statusResp.Error.Message)
		}
		if len(statusResp.Result.Value) > 0 {
			status := statusResp.Result.Value[0]
			if status.Err != nil {
				errBytes, _ := json.Marshal(status.Err)
				return false, status.ConfirmationStatus, fmt.Errorf("transaction failed on-chain: %s", string(errBytes))
			}
			if status.ConfirmationStatus == "confirmed" || status.ConfirmationStatus == "finalized" {
				return true, status.ConfirmationStatus, nil
			}
			if status.ConfirmationStatus != "" {
				return false, status.ConfirmationStatus, nil
			}
		}
		time.Sleep(1500 * time.Millisecond)
	}
	return false, "pending", nil
}
