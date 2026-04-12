package main

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/valyala/fasthttp"
)

func postJSONRaw(endpoint string, body []byte) ([]byte, int, error) {
	req, err := http.NewRequest("POST", endpoint, bytes.NewReader(body))
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := backendClient.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()
	rb, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, resp.StatusCode, err
	}
	return rb, resp.StatusCode, nil
}

func rawJSON(b []byte) interface{} {
	return json.RawMessage(b)
}

// R2 / appstatic config
var (
	r2AccountID       string
	r2AccessKeyID     string
	r2SecretAccessKey string
	r2Bucket          string // "appstatic"
	r2PathPrefix      string // "cutedsl/uploads"
	r2PublicHost      string // "appstatic.app.nz"
)

func initUploads() {
	r2AccountID = getEnv("R2_ACCOUNT_ID", "f76d25b8b86cfa5638f43016510d8f77")
	r2AccessKeyID = getEnv("CLOUDFLARE_R2_ACCESS_KEY_ID", "")
	r2SecretAccessKey = getEnv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "")
	r2Bucket = getEnv("R2_BUCKET", "appstatic")
	r2PathPrefix = getEnv("R2_PATH_PREFIX", "cutedsl/uploads")
	r2PublicHost = getEnv("R2_PUBLIC_HOST", "appstatic.app.nz")
}

// presignR2PutObject builds an SigV4 query-string-signed PUT URL for R2.
// expires is in seconds (max 7 days).
func presignR2PutObject(objectKey, contentType string, expires int) (string, error) {
	if r2AccountID == "" || r2AccessKeyID == "" || r2SecretAccessKey == "" {
		return "", fmt.Errorf("R2 credentials not configured")
	}
	if expires <= 0 || expires > 604800 {
		expires = 900
	}

	host := fmt.Sprintf("%s.r2.cloudflarestorage.com", r2AccountID)
	region := "auto"
	service := "s3"
	method := "PUT"
	now := time.Now().UTC()
	amzDate := now.Format("20060102T150405Z")
	dateStamp := now.Format("20060102")

	// Canonical URI: /{bucket}/{key} (path-style)
	canonicalURI := "/" + r2Bucket + "/" + escapePath(objectKey)

	credentialScope := fmt.Sprintf("%s/%s/%s/aws4_request", dateStamp, region, service)
	credential := r2AccessKeyID + "/" + credentialScope

	// Signed headers — only host (we deliberately do NOT sign content-type so the
	// browser PUT can attach whatever the file's MIME is).
	signedHeaders := "host"
	canonicalHeaders := "host:" + host + "\n"

	// Query parameters (sorted)
	params := url.Values{}
	params.Set("X-Amz-Algorithm", "AWS4-HMAC-SHA256")
	params.Set("X-Amz-Credential", credential)
	params.Set("X-Amz-Date", amzDate)
	params.Set("X-Amz-Expires", fmt.Sprintf("%d", expires))
	params.Set("X-Amz-SignedHeaders", signedHeaders)

	canonicalQuery := canonicalQueryString(params)

	canonicalRequest := strings.Join([]string{
		method,
		canonicalURI,
		canonicalQuery,
		canonicalHeaders,
		signedHeaders,
		"UNSIGNED-PAYLOAD",
	}, "\n")

	hash := sha256.Sum256([]byte(canonicalRequest))
	stringToSign := strings.Join([]string{
		"AWS4-HMAC-SHA256",
		amzDate,
		credentialScope,
		hex.EncodeToString(hash[:]),
	}, "\n")

	// Derive signing key
	kDate := hmacSHA256([]byte("AWS4"+r2SecretAccessKey), dateStamp)
	kRegion := hmacSHA256(kDate, region)
	kService := hmacSHA256(kRegion, service)
	kSigning := hmacSHA256(kService, "aws4_request")
	signature := hex.EncodeToString(hmacSHA256(kSigning, stringToSign))

	params.Set("X-Amz-Signature", signature)
	finalQuery := canonicalQueryString(params)

	return fmt.Sprintf("https://%s%s?%s", host, canonicalURI, finalQuery), nil
}

func hmacSHA256(key []byte, data string) []byte {
	h := hmac.New(sha256.New, key)
	h.Write([]byte(data))
	return h.Sum(nil)
}

// canonicalQueryString builds an RFC3986-encoded, sorted query string per SigV4.
func canonicalQueryString(params url.Values) string {
	keys := make([]string, 0, len(params))
	for k := range params {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	parts := make([]string, 0, len(keys))
	for _, k := range keys {
		for _, v := range params[k] {
			parts = append(parts, awsURIEncode(k, true)+"="+awsURIEncode(v, true))
		}
	}
	return strings.Join(parts, "&")
}

// escapePath encodes a path leaving / unescaped, per SigV4 canonical URI rules.
func escapePath(p string) string {
	parts := strings.Split(p, "/")
	for i, seg := range parts {
		parts[i] = awsURIEncode(seg, false)
	}
	return strings.Join(parts, "/")
}

// awsURIEncode mirrors AWS SigV4's URI-encoding rules. unreserved = A-Z a-z 0-9 - _ . ~
func awsURIEncode(s string, encodeSlash bool) string {
	var sb strings.Builder
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
			c == '-' || c == '_' || c == '.' || c == '~':
			sb.WriteByte(c)
		case c == '/' && !encodeSlash:
			sb.WriteByte(c)
		default:
			sb.WriteString(fmt.Sprintf("%%%02X", c))
		}
	}
	return sb.String()
}

// ---------------- HTTP handlers ----------------

// handlePresignUpload returns a presigned PUT URL for uploading a file to R2.
// Auth: Bearer API key.
// Query params: filename, content_type (optional), dataset (optional, default "default")
func handlePresignUpload(ctx *fasthttp.RequestCtx) {
	authHeader := string(ctx.Request.Header.Peek("Authorization"))
	if !strings.HasPrefix(authHeader, "Bearer ") {
		jsonError(ctx, 401, "API key required")
		return
	}
	apiKey := strings.TrimPrefix(authHeader, "Bearer ")
	user, err := dbConn.GetUserByAPIKey(apiKey)
	if err != nil {
		jsonError(ctx, 401, "invalid API key")
		return
	}

	filename := string(ctx.QueryArgs().Peek("filename"))
	if filename == "" {
		jsonError(ctx, 400, "filename query param required")
		return
	}
	contentType := string(ctx.QueryArgs().Peek("content_type"))
	if contentType == "" {
		contentType = "application/octet-stream"
	}
	dataset := string(ctx.QueryArgs().Peek("dataset"))
	if dataset == "" {
		dataset = "default"
	}

	// Sanitize
	filename = sanitizeUploadName(filename)
	dataset = sanitizeUploadName(dataset)
	if filename == "" || dataset == "" {
		jsonError(ctx, 400, "invalid filename or dataset")
		return
	}

	// Object key: cutedsl/uploads/<user_short>/<dataset>/<random>-<filename>
	userShort := user.ID
	if len(userShort) > 8 {
		userShort = userShort[:8]
	}
	id := uuid.New().String()[:10]
	objectKey := fmt.Sprintf("%s/%s/%s/%s-%s", r2PathPrefix, userShort, dataset, id, filename)

	uploadURL, err := presignR2PutObject(objectKey, contentType, 900)
	if err != nil {
		jsonError(ctx, 500, "failed to presign: "+err.Error())
		return
	}

	publicURL := fmt.Sprintf("https://%s/%s", r2PublicHost, objectKey)

	jsonResponse(ctx, 200, map[string]interface{}{
		"upload_url":   uploadURL,
		"public_url":   publicURL,
		"object_key":   objectKey,
		"content_type": contentType,
		"expires_in":   900,
	})
}

func sanitizeUploadName(s string) string {
	var sb strings.Builder
	for i := 0; i < len(s); i++ {
		c := s[i]
		if (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
			c == '.' || c == '_' || c == '-' {
			sb.WriteByte(c)
		} else if c == ' ' {
			sb.WriteByte('_')
		}
	}
	out := sb.String()
	if len(out) > 200 {
		out = out[:200]
	}
	return out
}

// handleStartLoraTraining accepts a list of public R2 URLs (the just-uploaded
// images) plus dataset metadata and kicks off a real training job.
// Auth: Bearer API key. Deducts credits via the existing /api/service flow,
// but here we proxy directly to inference's /train so we can pass image URLs.
func handleStartLoraTraining(ctx *fasthttp.RequestCtx) {
	authHeader := string(ctx.Request.Header.Peek("Authorization"))
	if !strings.HasPrefix(authHeader, "Bearer ") {
		jsonError(ctx, 401, "API key required")
		return
	}
	apiKey := strings.TrimPrefix(authHeader, "Bearer ")
	user, err := dbConn.GetUserByAPIKey(apiKey)
	if err != nil {
		jsonError(ctx, 401, "invalid API key")
		return
	}

	// Charge first
	cuteCost := getServicePriceCUTE("lora_training")
	if cuteCost <= 0 {
		jsonError(ctx, 503, "pricing unavailable")
		return
	}
	newBalance, err := dbConn.DeductUserCredits(user.ID, cuteCost)
	if err != nil {
		if strings.Contains(err.Error(), "insufficient") {
			jsonError(ctx, 402, fmt.Sprintf("insufficient credits: need %.2f $CUTEDSL, have %.2f", cuteCost, user.Credits))
			return
		}
		jsonError(ctx, 500, "failed to deduct credits")
		return
	}

	// Forward request body to inference /train/from_urls
	backendURL := serviceBackends["lora_training"]
	endpoint := backendURL + "/train/from_urls"

	body, statusCode, err := postJSONRaw(endpoint, ctx.PostBody())
	if err != nil {
		// Refund
		go dbConn.AddUserCredits(user.ID, cuteCost)
		jsonError(ctx, 502, "training backend unavailable: "+err.Error())
		return
	}
	if statusCode >= 400 {
		go dbConn.AddUserCredits(user.ID, cuteCost)
		ctx.SetStatusCode(statusCode)
		ctx.SetBody(body)
		return
	}

	// Log billing
	cutePrice := getCUTEPriceUSD()
	usdEquiv := cuteCost * cutePrice
	go dbConn.CreateBillingEvent(&BillingEvent{
		UserID:       user.ID,
		EventType:    "lora_training",
		Amount:       -cuteCost,
		CuteAmount:   cuteCost,
		USDAmount:    usdEquiv,
		Description:  fmt.Sprintf("LoRA training kickoff (%.2f $CUTEDSL)", cuteCost),
		CreditsAfter: newBalance,
	})

	jsonResponse(ctx, 200, map[string]interface{}{
		"result":         rawJSON(body),
		"credits_used":   cuteCost,
		"credits_remain": newBalance,
		"usd_equivalent": usdEquiv,
	})
}
