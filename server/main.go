package main

import (
	"crypto/rand"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/joho/godotenv"
	"github.com/valyala/fasthttp"
)

var (
	dbConn      *DB
	devMode     bool
	frontendURL string
)

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getPort() int {
	if p := os.Getenv("PORT"); p != "" {
		if port, err := strconv.Atoi(p); err == nil {
			return port
		}
	}
	return 8080
}

func main() {
	godotenv.Load()
	godotenv.Load("../.env")

	devMode = strings.EqualFold(os.Getenv("DEV"), "true")
	frontendURL = getEnv("FRONTEND_URL", "http://localhost:3000")

	// Initialize database
	dbDSN := getEnv("DATABASE_URL", "postgres://cutedsl:cutedsl_pass_2026@localhost:5432/cutedsl?sslmode=disable")
	var err error
	dbConn, err = NewDB(dbDSN)
	if err != nil {
		log.Fatalf("Failed to initialize database: %v", err)
	}
	defer dbConn.Close()
	log.Printf("Database initialized")

	// Initialize subsystems
	initCrypto()
	initStripe()
	initServices()
	initUploads()
	initEmail()
	initPromptSearch() // Background: loads gobed model + indexes 1.7M prompts

	port := getPort()
	log.Printf("CuteDSL server starting on :%d (dev=%v)", port, devMode)

	if err := fasthttp.ListenAndServe(fmt.Sprintf(":%d", port), requestHandler); err != nil {
		log.Fatalf("Server error: %v", err)
	}
}

func requestHandler(ctx *fasthttp.RequestCtx) {
	path := string(ctx.Path())
	method := string(ctx.Method())

	// CORS headers
	setCORSHeaders(ctx)

	if method == "OPTIONS" {
		ctx.SetStatusCode(204)
		return
	}

	// API routes
	if strings.HasPrefix(path, "/api/") {
		routeAPI(ctx, path, method)
		return
	}

	if path == "/stripe-webhook" && method == "POST" {
		handleStripeWebhook(ctx)
		return
	}

	// Serve generated images from /sdb-disk/cutedsl-images
	if strings.HasPrefix(path, "/images/") {
		serveImage(ctx, path)
		return
	}

	// Dynamic sitemap served from the DB for SEO crawling.
	// Accept GET and HEAD so validators that probe with HEAD still see
	// the correct Content-Type (Google Search Console flags a fetch
	// failure otherwise, since HEAD would fall through to the SPA
	// index.html and return text/html).
	isSitemapMethod := method == "GET" || method == "HEAD"
	if path == "/sitemap.xml" && isSitemapMethod {
		handleSitemapIndex(ctx)
		return
	}
	if path == "/sitemap-pages.xml" && isSitemapMethod {
		handleSitemapPages(ctx)
		return
	}
	if strings.HasPrefix(path, "/sitemap-images-") && strings.HasSuffix(path, ".xml") && isSitemapMethod {
		pageStr := strings.TrimSuffix(strings.TrimPrefix(path, "/sitemap-images-"), ".xml")
		handleSitemapImages(ctx, pageStr)
		return
	}
	if path == "/sitemap-tags.xml" && isSitemapMethod {
		handleSitemapTags(ctx)
		return
	}

	// Server-rendered prompt detail page (SEO). /prompt/<image_id>
	if strings.HasPrefix(path, "/prompt/") && method == "GET" {
		handlePromptHTML(ctx, strings.TrimPrefix(path, "/prompt/"))
		return
	}

	// SEO-friendly image pages. /image/<prompt-slug>-<shortID>
	if strings.HasPrefix(path, "/image/") && method == "GET" {
		handleImageBySlug(ctx, strings.TrimPrefix(path, "/image/"))
		return
	}

	// SEO tag landing pages. /tag/<slug> — server-rendered with semantic-matched images.
	if strings.HasPrefix(path, "/tag/") && method == "GET" {
		handleTagPage(ctx, strings.TrimPrefix(path, "/tag/"))
		return
	}

	// /tags — category index listing every curated tag (one-page SEO hub).
	if path == "/tags" && method == "GET" {
		handleTagsIndex(ctx)
		return
	}

	// Static files / frontend
	serveStatic(ctx, path)
}

func setCORSHeaders(ctx *fasthttp.RequestCtx) {
	origin := string(ctx.Request.Header.Peek("Origin"))
	if origin == "" {
		origin = "*"
	}

	// Allow the frontend origin and common dev origins
	allowedOrigins := []string{
		frontendURL,
		"https://cutedsl.cc",
		"https://www.cutedsl.cc",
		"https://cutedsl.app.nz",
		"https://appstatic.app.nz",
		"http://localhost:3000",
		"http://localhost:8080",
	}
	allowed := false
	for _, o := range allowedOrigins {
		if origin == o {
			allowed = true
			break
		}
	}
	if !allowed && devMode {
		allowed = true // Allow all in dev mode
	}

	if allowed {
		ctx.Response.Header.Set("Access-Control-Allow-Origin", origin)
	}
	ctx.Response.Header.Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
	ctx.Response.Header.Set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Wallet-Address")
	ctx.Response.Header.Set("Access-Control-Allow-Credentials", "true")
	ctx.Response.Header.Set("Access-Control-Max-Age", "86400")
}

func routeAPI(ctx *fasthttp.RequestCtx, path, method string) {
	ctx.Response.Header.Set("Content-Type", "application/json")

	switch {
	// Health check
	case path == "/api/health" && method == "GET":
		jsonResponse(ctx, 200, map[string]string{"status": "ok", "service": "cutedsl"})

	case path == "/api/frontend-error" && method == "POST":
		handleFrontendError(ctx)

	// Crypto checkout - create deposit
	case path == "/api/crypto-checkout" && method == "POST":
		handleCryptoCheckout(ctx)

	// Stripe checkout and auto top-up
	case (path == "/api/stripe-checkout" || path == "/api/create-credits-checkout") && method == "POST":
		handleStripeCheckout(ctx)

	case path == "/api/stripe/config" && method == "GET":
		handleStripeConfig(ctx)

	case (path == "/api/stripe-webhook" || path == "/api/stripe/webhook") && method == "POST":
		handleStripeWebhook(ctx)

	case path == "/api/autotopup-settings" && method == "GET":
		handleGetAutotopupSettings(ctx)

	case (path == "/api/autotopup-settings" || path == "/api/save-autotopup-settings") && method == "POST":
		handleSaveAutotopupSettings(ctx)

	// Crypto checkout - get status
	case strings.HasPrefix(path, "/api/crypto-checkout/") && strings.HasSuffix(path, "/events") && method == "GET":
		intentID := extractPathParam(path, "/api/crypto-checkout/", "/events")
		handleStreamCheckoutEvents(ctx, intentID)

	case strings.HasPrefix(path, "/api/crypto-checkout/") && method == "GET":
		intentID := strings.TrimPrefix(path, "/api/crypto-checkout/")
		handleGetCheckoutStatus(ctx, intentID)

	// Price feeds
	case path == "/api/cute-price" && method == "GET":
		handleGetCUTEPrice(ctx)

	case path == "/api/pricing" && method == "GET":
		handleGetPricing(ctx)

	// Wallet balance
	case path == "/api/balance" && method == "GET":
		handleGetBalance(ctx)

	// Billing history
	case path == "/api/billing-history" && method == "GET":
		handleGetBillingHistory(ctx)

	// AI Service usage
	case path == "/api/service" && method == "POST":
		handleServiceRequest(ctx)

	// LoRA training datasets (list)
	case path == "/api/train/datasets" && method == "GET":
		handleListTrainingDatasets(ctx)

	// LoRA training dataset upload (multipart, server-side proxy)
	case path == "/api/train/upload_dataset" && method == "POST":
		handleUploadTrainingDataset(ctx)

	// Presigned R2 PUT URL for direct browser upload
	case path == "/api/uploads/presign" && method == "GET":
		handlePresignUpload(ctx)

	// Start a LoRA training job from a list of public R2 URLs
	case path == "/api/train/start" && method == "POST":
		handleStartLoraTraining(ctx)

	// Training job status (proxy to inference)
	case strings.HasPrefix(path, "/api/train/") && method == "GET":
		handleTrainStatus(ctx, strings.TrimPrefix(path, "/api/train/"))

	// Register / login (wallet-based)
	case path == "/api/auth/wallet" && method == "POST":
		handleWalletAuth(ctx)

	// Simple email account login
	case path == "/api/auth/email-login" && method == "POST":
		handleEmailLogin(ctx)

	case path == "/api/auth/forgot-password" && method == "POST":
		handleForgotPassword(ctx)

	case path == "/api/auth/reset-password" && method == "POST":
		handleResetPassword(ctx)

	// Update user email
	case path == "/api/auth/email" && method == "POST":
		handleUpdateEmail(ctx)

	// Image gallery / search
	case path == "/api/images" && method == "GET":
		handleImageSearch(ctx)

	case path == "/api/images/count" && method == "GET":
		handleImageCount(ctx)

	// Swap (buy $CUTEDSL via bags.fm liquidity pool)
	case path == "/api/swap/quote" && method == "GET":
		handleSwapQuote(ctx)

	case path == "/api/swap/transaction" && method == "POST":
		handleSwapTransaction(ctx)

	case path == "/api/swap/send_transaction" && method == "POST":
		handleSwapSendTransaction(ctx)

	// Semantic prompt search (gobed) — returns prompts + similarity scores
	case path == "/api/search" && method == "GET":
		handleSemanticSearch(ctx)

	case path == "/api/search/stats" && method == "GET":
		handleSearchStats(ctx)

	// Trigger a full search index rebuild (picks up images added directly to DB)
	case path == "/api/search/reindex" && method == "POST":
		go promptSearch.loadAndIndex()
		jsonResponse(ctx, 202, map[string]string{"status": "reindexing"})

	// Semantic IMAGE search (gobed) — returns hydrated GeneratedImage rows
	case path == "/api/images/semantic" && method == "GET":
		handleSemanticImageSearch(ctx)

	// Single prompt API: image + related
	case strings.HasPrefix(path, "/api/prompt/") && method == "GET":
		handlePromptAPI(ctx, strings.TrimPrefix(path, "/api/prompt/"))

	default:
		jsonError(ctx, 404, "not found")
	}
}

type frontendErrorPayload struct {
	Level       string                 `json:"level"`
	Message     string                 `json:"message"`
	Name        string                 `json:"name"`
	Stack       string                 `json:"stack"`
	Source      string                 `json:"source"`
	Lineno      int                    `json:"lineno"`
	Colno       int                    `json:"colno"`
	Component   string                 `json:"component"`
	URL         string                 `json:"url"`
	Referrer    string                 `json:"referrer"`
	UserAgent   string                 `json:"userAgent"`
	Language    string                 `json:"language"`
	Timezone    string                 `json:"timezone"`
	Viewport    map[string]int         `json:"viewport"`
	Screen      map[string]int         `json:"screen"`
	Connection  map[string]interface{} `json:"connection"`
	AppVersion  string                 `json:"appVersion"`
	BuildID     string                 `json:"buildId"`
	SessionID   string                 `json:"sessionId"`
	OccurredAt  string                 `json:"occurredAt"`
	Fingerprint string                 `json:"fingerprint"`
}

func frontendErrorLogPath() string {
	return getEnv("FRONTEND_ERROR_LOG_PATH", "/nvme0n1-disk/tmp/cutedsl-frontend-errors.jsonl")
}

func newRequestID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return fmt.Sprintf("%d", time.Now().UnixNano())
	}
	return fmt.Sprintf("%x", b[:])
}

func handleFrontendError(ctx *fasthttp.RequestCtx) {
	var payload frontendErrorPayload
	if err := json.Unmarshal(ctx.PostBody(), &payload); err != nil {
		jsonError(ctx, 400, "invalid json")
		return
	}

	payload.Level = strings.ToLower(strings.TrimSpace(payload.Level))
	if payload.Level == "" {
		payload.Level = "error"
	}
	if payload.Level != "error" {
		jsonError(ctx, 400, "only error events are accepted")
		return
	}
	payload.Message = truncateString(strings.TrimSpace(payload.Message), 2000)
	payload.Name = truncateString(strings.TrimSpace(payload.Name), 200)
	payload.Stack = truncateString(payload.Stack, 12000)
	payload.Source = truncateString(payload.Source, 1000)
	payload.Component = truncateString(payload.Component, 200)
	payload.URL = truncateString(payload.URL, 2000)
	payload.Referrer = truncateString(payload.Referrer, 2000)
	payload.UserAgent = truncateString(payload.UserAgent, 1000)
	payload.Language = truncateString(payload.Language, 100)
	payload.Timezone = truncateString(payload.Timezone, 100)
	payload.AppVersion = truncateString(payload.AppVersion, 100)
	payload.BuildID = truncateString(payload.BuildID, 100)
	payload.SessionID = truncateString(payload.SessionID, 100)
	payload.Fingerprint = truncateString(payload.Fingerprint, 200)

	if payload.Message == "" && payload.Stack == "" {
		jsonError(ctx, 400, "message or stack required")
		return
	}

	requestID := newRequestID()
	event := map[string]interface{}{
		"timestamp":   time.Now().UTC().Format(time.RFC3339Nano),
		"request_id":  requestID,
		"remote_ip":   ctx.RemoteIP().String(),
		"level":       payload.Level,
		"message":     payload.Message,
		"name":        payload.Name,
		"stack":       payload.Stack,
		"source":      payload.Source,
		"lineno":      payload.Lineno,
		"colno":       payload.Colno,
		"component":   payload.Component,
		"url":         payload.URL,
		"referrer":    payload.Referrer,
		"user_agent":  payload.UserAgent,
		"language":    payload.Language,
		"timezone":    payload.Timezone,
		"viewport":    payload.Viewport,
		"screen":      payload.Screen,
		"connection":  payload.Connection,
		"app_version": payload.AppVersion,
		"build_id":    payload.BuildID,
		"session_id":  payload.SessionID,
		"occurred_at": payload.OccurredAt,
		"fingerprint": payload.Fingerprint,
	}

	path := frontendErrorLogPath()
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		log.Printf("frontend error log mkdir failed: %v", err)
		jsonError(ctx, 500, "failed to log frontend error")
		return
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		log.Printf("frontend error log open failed: %v", err)
		jsonError(ctx, 500, "failed to log frontend error")
		return
	}
	defer f.Close()
	enc := json.NewEncoder(f)
	if err := enc.Encode(event); err != nil && err != io.ErrClosedPipe {
		log.Printf("frontend error log write failed: %v", err)
		jsonError(ctx, 500, "failed to log frontend error")
		return
	}

	ctx.Response.Header.Set("X-Request-ID", requestID)
	jsonResponse(ctx, 202, map[string]string{"status": "logged", "request_id": requestID})
}

func extractPathParam(path, prefix, suffix string) string {
	path = strings.TrimPrefix(path, prefix)
	path = strings.TrimSuffix(path, suffix)
	return path
}

// handleWalletAuth registers or retrieves a user by wallet address
func handleWalletAuth(ctx *fasthttp.RequestCtx) {
	var req struct {
		WalletAddress string `json:"wallet_address"`
		Email         string `json:"email,omitempty"`
		Password      string `json:"password,omitempty"`
		APIKey        string `json:"api_key,omitempty"`
	}
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil || req.WalletAddress == "" {
		jsonError(ctx, 400, "wallet_address required")
		return
	}
	req.WalletAddress = strings.TrimSpace(req.WalletAddress)
	req.Email = strings.ToLower(strings.TrimSpace(req.Email))
	req.APIKey = strings.TrimSpace(req.APIKey)

	var user *User
	created := false
	linked := false
	var err error

	if req.APIKey != "" {
		user, err = dbConn.GetUserByAPIKey(req.APIKey)
		if err != nil {
			jsonError(ctx, 401, "invalid api key")
			return
		}
		if user.WalletAddress != req.WalletAddress {
			user, linked, err = dbConn.LinkUserToWallet(user.ID, req.WalletAddress)
			if err != nil {
				log.Printf("wallet link error: %v", err)
				jsonError(ctx, 500, "failed to link wallet")
				return
			}
		}
	} else {
		user, created, err = dbConn.GetOrCreateUser(req.WalletAddress)
		if err != nil {
			jsonError(ctx, 500, "failed to register wallet")
			return
		}
	}

	// If email provided (on signup or update), set it and start drip
	if req.Email != "" && req.Email != user.Email {
		if !looksLikeEmail(req.Email) {
			jsonError(ctx, 400, "valid email required")
			return
		}
		updated, err := dbConn.UpdateUserEmailAndPassword(user.ID, req.Email, "")
		if err != nil {
			log.Printf("Failed to update email for %s: %v", user.ID, err)
			if strings.Contains(err.Error(), "email already in use") {
				jsonError(ctx, 409, "email already in use")
				return
			}
		} else {
			user = updated
			// Send welcome email immediately for new email signups
			if created || user.DripStep == 0 {
				go func() {
					if dripConfig != nil && len(dripConfig.Emails) > 0 {
						if err := sendDripEmail(user, dripConfig.Emails[0]); err != nil {
							log.Printf("Welcome email error: %v", err)
						}
					}
				}()
			}
		}
	}
	if req.Password != "" {
		if user.Email == "" {
			jsonError(ctx, 400, "email required to set password")
			return
		}
		passwordHash, err := hashPassword(req.Password)
		if err != nil {
			jsonError(ctx, 400, err.Error())
			return
		}
		updated, err := dbConn.UpdateUserEmailAndPassword(user.ID, user.Email, passwordHash)
		if err != nil {
			log.Printf("wallet password update error: %v", err)
			jsonError(ctx, 500, "failed to update email password")
			return
		}
		user = updated
	}

	cutePrice := getCUTEPriceUSD()
	jsonResponse(ctx, 200, map[string]interface{}{
		"user":           user,
		"api_key":        user.APIKey,
		"created":        created,
		"linked":         linked,
		"cute_price_usd": cutePrice,
		"credits_usd":    user.Credits * cutePrice,
	})
}

// handleEmailLogin creates or retrieves a simple email-backed account.
func handleEmailLogin(ctx *fasthttp.RequestCtx) {
	var req struct {
		Email    string `json:"email"`
		Password string `json:"password"`
	}
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil {
		jsonError(ctx, 400, "invalid request")
		return
	}

	req.Email = strings.ToLower(strings.TrimSpace(req.Email))
	if !looksLikeEmail(req.Email) {
		jsonError(ctx, 400, "valid email required")
		return
	}
	if len(req.Password) < 8 {
		jsonError(ctx, 400, "password must be at least 8 characters")
		return
	}

	passwordHash, err := hashPassword(req.Password)
	if err != nil {
		jsonError(ctx, 400, err.Error())
		return
	}
	user, created, err := dbConn.GetOrCreateUserByEmailWithPassword(req.Email, passwordHash)
	if err != nil {
		log.Printf("email login error: %v", err)
		jsonError(ctx, 500, "failed to login")
		return
	}
	if !created {
		if user.PasswordHash == "" {
			if err := dbConn.SetUserPasswordHash(user.ID, passwordHash); err != nil {
				jsonError(ctx, 500, "failed to set password")
				return
			}
			user.PasswordHash = passwordHash
		} else if !checkPassword(req.Password, user.PasswordHash) {
			jsonError(ctx, 401, "invalid email or password")
			return
		}
	}

	if created || user.DripStep == 0 {
		go func() {
			if dripConfig != nil && len(dripConfig.Emails) > 0 {
				if err := sendDripEmail(user, dripConfig.Emails[0]); err != nil {
					log.Printf("Welcome email error: %v", err)
				}
			}
		}()
	}

	cutePrice := getCUTEPriceUSD()
	jsonResponse(ctx, 200, map[string]interface{}{
		"user":           user,
		"api_key":        user.APIKey,
		"created":        created,
		"cute_price_usd": cutePrice,
		"credits_usd":    user.Credits * cutePrice,
	})
}

func handleForgotPassword(ctx *fasthttp.RequestCtx) {
	var req struct {
		Email string `json:"email"`
	}
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil {
		jsonError(ctx, 400, "invalid request")
		return
	}
	req.Email = strings.ToLower(strings.TrimSpace(req.Email))
	if !looksLikeEmail(req.Email) {
		jsonError(ctx, 400, "valid email required")
		return
	}

	resp := map[string]interface{}{"success": true}
	user, err := dbConn.GetUserByEmail(req.Email)
	if err == nil {
		raw, tokenHash, err := newPasswordResetToken()
		if err != nil {
			jsonError(ctx, 500, "failed to create reset token")
			return
		}
		if err := dbConn.CreatePasswordResetToken(user.ID, tokenHash, time.Now().Add(30*time.Minute)); err != nil {
			jsonError(ctx, 500, "failed to save reset token")
			return
		}
		resetURL := strings.TrimRight(defaultPublicURL(ctx), "/") + "/account?reset_token=" + raw
		go func() {
			if err := sendPasswordResetEmail(user.Email, resetURL); err != nil {
				log.Printf("password reset email error for %s: %v", user.Email, err)
			}
		}()
		if devMode || strings.EqualFold(os.Getenv("EMAIL_DEBUG_RESET_TOKEN"), "true") {
			resp["reset_token"] = raw
		}
	} else {
		log.Printf("password reset requested for unknown email %s", req.Email)
	}

	jsonResponse(ctx, 200, resp)
}

func handleResetPassword(ctx *fasthttp.RequestCtx) {
	var req struct {
		Token    string `json:"token"`
		Password string `json:"password"`
	}
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil {
		jsonError(ctx, 400, "invalid request")
		return
	}
	req.Token = strings.TrimSpace(req.Token)
	if req.Token == "" {
		jsonError(ctx, 400, "token required")
		return
	}
	passwordHash, err := hashPassword(req.Password)
	if err != nil {
		jsonError(ctx, 400, err.Error())
		return
	}

	user, err := dbConn.ConsumePasswordResetToken(passwordResetTokenHash(req.Token))
	if err != nil {
		jsonError(ctx, 400, "invalid or expired reset token")
		return
	}
	if err := dbConn.SetUserPasswordHash(user.ID, passwordHash); err != nil {
		jsonError(ctx, 500, "failed to update password")
		return
	}
	user.PasswordHash = passwordHash
	cutePrice := getCUTEPriceUSD()
	jsonResponse(ctx, 200, map[string]interface{}{
		"success":        true,
		"user":           user,
		"api_key":        user.APIKey,
		"cute_price_usd": cutePrice,
		"credits_usd":    user.Credits * cutePrice,
	})
}

func looksLikeEmail(email string) bool {
	if len(email) < 5 || len(email) > 320 || strings.ContainsAny(email, " \t\r\n") {
		return false
	}
	at := strings.LastIndex(email, "@")
	return at > 0 && at < len(email)-3 && strings.Contains(email[at+1:], ".")
}

// handleUpdateEmail updates a user's email address
func handleUpdateEmail(ctx *fasthttp.RequestCtx) {
	var req struct {
		WalletAddress string `json:"wallet_address"`
		Email         string `json:"email"`
		Password      string `json:"password,omitempty"`
	}
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil {
		jsonError(ctx, 400, "invalid request")
		return
	}

	req.Email = strings.ToLower(strings.TrimSpace(req.Email))
	if req.Email == "" || req.WalletAddress == "" {
		jsonError(ctx, 400, "wallet_address and email required")
		return
	}

	if !looksLikeEmail(req.Email) {
		jsonError(ctx, 400, "invalid email address")
		return
	}
	passwordHash := ""
	if req.Password != "" {
		var err error
		passwordHash, err = hashPassword(req.Password)
		if err != nil {
			jsonError(ctx, 400, err.Error())
			return
		}
	}

	user, err := dbConn.GetUserByWallet(req.WalletAddress)
	if err != nil {
		jsonError(ctx, 404, "wallet not found")
		return
	}

	wasEmpty := user.Email == ""
	user, err = dbConn.UpdateUserEmailAndPassword(user.ID, req.Email, passwordHash)
	if err != nil {
		if strings.Contains(err.Error(), "email already in use") {
			jsonError(ctx, 409, "email already in use")
			return
		}
		jsonError(ctx, 500, "failed to update email")
		return
	}

	// Start drip campaign if this is a new email
	if wasEmpty {
		go func() {
			if dripConfig != nil && len(dripConfig.Emails) > 0 {
				if err := sendDripEmail(user, dripConfig.Emails[0]); err != nil {
					log.Printf("Welcome email error: %v", err)
				}
			}
		}()
	}

	jsonResponse(ctx, 200, map[string]interface{}{
		"success":      true,
		"email":        req.Email,
		"has_password": user.PasswordHash != "",
		"user":         user,
	})
}

// Static file serving for frontend
var mimeTypes = map[string]string{
	".html":  "text/html; charset=utf-8",
	".css":   "text/css; charset=utf-8",
	".js":    "application/javascript; charset=utf-8",
	".json":  "application/json",
	".png":   "image/png",
	".jpg":   "image/jpeg",
	".jpeg":  "image/jpeg",
	".gif":   "image/gif",
	".webp":  "image/webp",
	".svg":   "image/svg+xml",
	".ico":   "image/x-icon",
	".woff":  "font/woff",
	".woff2": "font/woff2",
	".ttf":   "font/ttf",
	".txt":   "text/plain",
}

func serveStatic(ctx *fasthttp.RequestCtx, path string) {
	// Try to serve from frontend build output
	distDir := getEnv("DIST_DIR", "../frontend/out")

	// Clean path
	if path == "/" {
		path = "/index.html"
	}

	filePath := filepath.Join(distDir, path)

	// If path has no extension, also try .html (Next.js static export)
	if filepath.Ext(filePath) == "" {
		htmlPath := filePath + ".html"
		if _, err := os.Stat(htmlPath); err == nil {
			filePath = htmlPath
		}
	}

	// Check if file exists
	if _, err := os.Stat(filePath); err == nil {
		ext := filepath.Ext(filePath)
		if ct, ok := mimeTypes[ext]; ok {
			ctx.Response.Header.Set("Content-Type", ct)
		}

		// Cache static assets
		if strings.HasPrefix(path, "/_next/") || strings.HasPrefix(path, "/assets/") {
			ctx.Response.Header.Set("Cache-Control", "public, max-age=31536000, immutable")
		}

		fasthttp.ServeFile(ctx, filePath)
		return
	}

	// SPA fallback - serve index.html for all non-file paths
	indexPath := filepath.Join(distDir, "index.html")
	if _, err := os.Stat(indexPath); err == nil {
		ctx.Response.Header.Set("Content-Type", "text/html; charset=utf-8")
		fasthttp.ServeFile(ctx, indexPath)
		return
	}

	// No frontend build available
	ctx.SetStatusCode(404)
	ctx.SetBodyString("Not found. Run 'npm run build' in frontend/ to generate static files.")
}

// JSON helpers

func jsonResponse(ctx *fasthttp.RequestCtx, status int, data interface{}) {
	ctx.SetStatusCode(status)
	ctx.Response.Header.Set("Content-Type", "application/json")
	body, err := json.Marshal(data)
	if err != nil {
		ctx.SetStatusCode(500)
		ctx.SetBodyString(`{"error":"internal error"}`)
		return
	}
	ctx.SetBody(body)
}

func jsonError(ctx *fasthttp.RequestCtx, status int, msg string) {
	ctx.SetStatusCode(status)
	ctx.Response.Header.Set("Content-Type", "application/json")
	body, _ := json.Marshal(map[string]string{"error": msg})
	ctx.SetBody(body)
}

// handleImageSearch handles GET /api/images?q=query&page=1&per_page=48&allow_nsfw=false
func handleImageSearch(ctx *fasthttp.RequestCtx) {
	query := string(ctx.QueryArgs().Peek("q"))
	page, _ := strconv.Atoi(string(ctx.QueryArgs().Peek("page")))
	perPage, _ := strconv.Atoi(string(ctx.QueryArgs().Peek("per_page")))
	allowNSFW := string(ctx.QueryArgs().Peek("allow_nsfw")) == "true"

	if page < 1 {
		page = 1
	}
	if perPage < 1 || perPage > 100 {
		perPage = 48
	}

	result, err := dbConn.SearchImages(query, page, perPage, allowNSFW)
	if err != nil {
		jsonError(ctx, 500, "search failed")
		return
	}
	jsonResponse(ctx, 200, result)
}

// handleImageCount handles GET /api/images/count
func handleImageCount(ctx *fasthttp.RequestCtx) {
	count, err := dbConn.GetImageCount()
	if err != nil {
		jsonError(ctx, 500, "count failed")
		return
	}
	jsonResponse(ctx, 200, map[string]int{"count": count})
}

// handleSemanticSearch handles GET /api/search?q=query&top_k=20
func handleSemanticSearch(ctx *fasthttp.RequestCtx) {
	query := string(ctx.QueryArgs().Peek("q"))
	if query == "" {
		jsonError(ctx, 400, "q parameter required")
		return
	}

	topK, _ := strconv.Atoi(string(ctx.QueryArgs().Peek("top_k")))
	if topK < 1 || topK > 200 {
		topK = 20
	}

	if promptSearch == nil || !promptSearch.IsReady() {
		jsonError(ctx, 503, "search engine not ready (still indexing)")
		return
	}

	results, err := promptSearch.Search(query, topK)
	if err != nil {
		jsonError(ctx, 500, "search failed")
		return
	}

	jsonResponse(ctx, 200, map[string]interface{}{
		"query":   query,
		"results": results,
		"count":   len(results),
	})
}

// handleSearchStats handles GET /api/search/stats
func handleSearchStats(ctx *fasthttp.RequestCtx) {
	if promptSearch == nil {
		jsonResponse(ctx, 200, map[string]interface{}{"ready": false})
		return
	}
	jsonResponse(ctx, 200, promptSearch.Stats())
}

// serveImage serves generated images from /sdb-disk/cutedsl-images
func serveImage(ctx *fasthttp.RequestCtx, path string) {
	imagesDir := getEnv("IMAGES_DIR", "/sdb-disk/cutedsl-images")
	// Strip /images/ prefix
	relPath := strings.TrimPrefix(path, "/images/")

	// Prevent directory traversal
	if strings.Contains(relPath, "..") {
		ctx.SetStatusCode(404)
		return
	}

	filePath := filepath.Join(imagesDir, relPath)
	if _, err := os.Stat(filePath); err != nil {
		ctx.SetStatusCode(404)
		return
	}

	ext := filepath.Ext(filePath)
	if ct, ok := mimeTypes[ext]; ok {
		ctx.Response.Header.Set("Content-Type", ct)
	}
	ctx.Response.Header.Set("Cache-Control", "public, max-age=31536000, immutable")
	fasthttp.ServeFile(ctx, filePath)
}
