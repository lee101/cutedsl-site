package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strconv"
	"strings"

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
	initServices()

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

	// Static files / frontend
	serveStatic(ctx, path)
}

func setCORSHeaders(ctx *fasthttp.RequestCtx) {
	origin := string(ctx.Request.Header.Peek("Origin"))
	if origin == "" {
		origin = "*"
	}

	// Allow the frontend origin and common dev origins
	allowedOrigins := []string{frontendURL, "http://localhost:3000", "http://localhost:8080"}
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

	// Crypto checkout - create deposit
	case path == "/api/crypto-checkout" && method == "POST":
		handleCryptoCheckout(ctx)

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

	// Register / login (wallet-based)
	case path == "/api/auth/wallet" && method == "POST":
		handleWalletAuth(ctx)

	default:
		jsonError(ctx, 404, "not found")
	}
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
	}
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil || req.WalletAddress == "" {
		jsonError(ctx, 400, "wallet_address required")
		return
	}

	user, created, err := dbConn.GetOrCreateUser(req.WalletAddress)
	if err != nil {
		jsonError(ctx, 500, "failed to register wallet")
		return
	}

	cutePrice := getCUTEPriceUSD()
	jsonResponse(ctx, 200, map[string]interface{}{
		"user":           user,
		"created":        created,
		"cute_price_usd": cutePrice,
		"credits_usd":    user.Credits * cutePrice,
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
