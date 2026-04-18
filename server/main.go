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

	// If email provided (on signup or update), set it and start drip
	req.Email = strings.TrimSpace(req.Email)
	if req.Email != "" && req.Email != user.Email {
		if err := dbConn.UpdateUserEmail(user.ID, req.Email); err != nil {
			log.Printf("Failed to update email for %s: %v", user.ID, err)
		} else {
			user.Email = req.Email
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

	cutePrice := getCUTEPriceUSD()
	jsonResponse(ctx, 200, map[string]interface{}{
		"user":           user,
		"api_key":        user.APIKey,
		"created":        created,
		"cute_price_usd": cutePrice,
		"credits_usd":    user.Credits * cutePrice,
	})
}

// handleUpdateEmail updates a user's email address
func handleUpdateEmail(ctx *fasthttp.RequestCtx) {
	var req struct {
		WalletAddress string `json:"wallet_address"`
		Email         string `json:"email"`
	}
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil {
		jsonError(ctx, 400, "invalid request")
		return
	}

	req.Email = strings.TrimSpace(req.Email)
	if req.Email == "" || req.WalletAddress == "" {
		jsonError(ctx, 400, "wallet_address and email required")
		return
	}

	// Basic email validation
	if !strings.Contains(req.Email, "@") || !strings.Contains(req.Email, ".") {
		jsonError(ctx, 400, "invalid email address")
		return
	}

	user, err := dbConn.GetUserByWallet(req.WalletAddress)
	if err != nil {
		jsonError(ctx, 404, "wallet not found")
		return
	}

	wasEmpty := user.Email == ""
	if err := dbConn.UpdateUserEmail(user.ID, req.Email); err != nil {
		jsonError(ctx, 500, "failed to update email")
		return
	}
	user.Email = req.Email

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
		"success": true,
		"email":   req.Email,
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
