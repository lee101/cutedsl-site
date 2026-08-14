package main

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/valyala/fasthttp"
)

const maxManifoldResponseBytes = 4 << 20
const maxManifoldFeaturedVideos = 18

var manifoldHTTPClient = &http.Client{Timeout: 45 * time.Second}

type generationJob struct {
	ID            string          `json:"job_id"`
	ProviderJobID string          `json:"-"`
	Service       string          `json:"service"`
	Kind          string          `json:"kind"`
	Status        string          `json:"status"`
	Prompt        string          `json:"prompt"`
	Result        json.RawMessage `json:"result,omitempty"`
	Error         string          `json:"error,omitempty"`
	IsPublic      bool            `json:"is_public"`
	CreatedAt     time.Time       `json:"created_at"`
	UpdatedAt     time.Time       `json:"updated_at"`
}

type createGenerationRequest struct {
	WalletAddress   string `json:"wallet_address,omitempty"`
	Prompt          string `json:"prompt"`
	AspectRatio     string `json:"aspect_ratio,omitempty"`
	Size            string `json:"size,omitempty"`
	Duration        int    `json:"duration,omitempty"`
	NumSteps        int    `json:"num_steps,omitempty"`
	IncludeAudio    *bool  `json:"include_audio,omitempty"`
	Structured      *bool  `json:"structured_prompt,omitempty"`
	OutputFormat    string `json:"output_format,omitempty"`
	EncodeQuality   int    `json:"encode_quality,omitempty"`
	FirstFrame      string `json:"first_frame,omitempty"`
	PublishOnFinish bool   `json:"publish_on_finish,omitempty"`
}

func manifoldOrigin() string {
	return strings.TrimRight(getEnv("MANIFOLDGEN_ORIGIN", "https://manifoldgen.com"), "/")
}

func manifoldAPIKey() string {
	if key := strings.TrimSpace(os.Getenv("MANIFOLDGEN_API_KEY")); key != "" {
		return key
	}
	return strings.TrimSpace(os.Getenv("MANIFOLD_API_KEY"))
}

func generationUser(ctx *fasthttp.RequestCtx, wallet string) (*User, error) {
	auth := strings.TrimSpace(string(ctx.Request.Header.Peek("Authorization")))
	if strings.HasPrefix(auth, "Bearer ") {
		return dbConn.GetUserByAPIKey(strings.TrimSpace(strings.TrimPrefix(auth, "Bearer ")))
	}
	if wallet != "" {
		return dbConn.GetUserByWallet(strings.TrimSpace(wallet))
	}
	return nil, errors.New("authorization required")
}

func normalizeGenerationRequest(req *createGenerationRequest) error {
	req.Prompt = strings.TrimSpace(req.Prompt)
	if len(req.Prompt) < 3 || len(req.Prompt) > 4000 {
		return errors.New("prompt must be between 3 and 4000 characters")
	}
	if req.AspectRatio == "" {
		req.AspectRatio = "16:9"
	}
	if req.AspectRatio != "16:9" && req.AspectRatio != "9:16" && req.AspectRatio != "1:1" {
		return errors.New("aspect_ratio must be 16:9, 9:16, or 1:1")
	}
	if req.Size == "" {
		req.Size = "preview"
	}
	if req.Size != "preview" && req.Size != "balanced" && req.Size != "native" {
		return errors.New("size must be preview, balanced, or native")
	}
	if req.Duration == 0 {
		req.Duration = 5
	}
	if req.Duration < 4 || req.Duration > 60 {
		return errors.New("duration must be between 4 and 60 seconds")
	}
	if req.NumSteps == 0 {
		req.NumSteps = 20
	}
	if req.NumSteps < 8 || req.NumSteps > 40 {
		return errors.New("num_steps must be between 8 and 40")
	}
	// AV1 WebM is the canonical gallery source. Callers cannot accidentally
	// create a less efficient public-gallery master.
	req.OutputFormat = "webm-av1"
	if req.EncodeQuality == 0 {
		req.EncodeQuality = 24
	}
	if req.EncodeQuality < 18 || req.EncodeQuality > 40 {
		return errors.New("encode_quality must be between 18 and 40")
	}
	if req.FirstFrame != "" {
		parsed, err := url.ParseRequestURI(req.FirstFrame)
		if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") {
			return errors.New("first_frame must be a public http(s) URL")
		}
	}
	return nil
}

func manifoldJSON(method, path string, payload interface{}) (int, []byte, error) {
	key := manifoldAPIKey()
	if key == "" {
		return 0, nil, errors.New("MANIFOLDGEN_API_KEY is not configured")
	}
	var body io.Reader
	if payload != nil {
		encoded, err := json.Marshal(payload)
		if err != nil {
			return 0, nil, err
		}
		body = bytes.NewReader(encoded)
	}
	req, err := http.NewRequest(method, manifoldOrigin()+path, body)
	if err != nil {
		return 0, nil, err
	}
	req.Header.Set("Authorization", "Bearer "+key)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", "Mozilla/5.0 CuteDSL-ManifoldGen/1.0")
	resp, err := manifoldHTTPClient.Do(req)
	if err != nil {
		return 0, nil, err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxManifoldResponseBytes))
	return resp.StatusCode, data, err
}

func handleCreateGeneration(ctx *fasthttp.RequestCtx) {
	var req createGenerationRequest
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil {
		jsonError(ctx, http.StatusBadRequest, "invalid json")
		return
	}
	user, err := generationUser(ctx, req.WalletAddress)
	if err != nil {
		jsonError(ctx, http.StatusUnauthorized, "valid CuteDSL authorization required")
		return
	}
	if err := normalizeGenerationRequest(&req); err != nil {
		jsonError(ctx, http.StatusBadRequest, err.Error())
		return
	}
	dailyLimit := 3
	if configured, parseErr := strconv.Atoi(strings.TrimSpace(os.Getenv("MANIFOLDGEN_DAILY_JOB_LIMIT"))); parseErr == nil && configured >= 0 {
		dailyLimit = configured
	}
	if dailyLimit > 0 && !user.UnlimitedAPI {
		var used int
		if countErr := dbConn.conn.QueryRow(
			`SELECT COUNT(*) FROM generation_jobs WHERE user_id=$1 AND created_at >= NOW() - INTERVAL '24 hours'`, user.ID,
		).Scan(&used); countErr != nil {
			jsonError(ctx, http.StatusInternalServerError, "could not check generation allowance")
			return
		}
		if used >= dailyLimit {
			jsonError(ctx, http.StatusTooManyRequests, fmt.Sprintf("daily generation limit reached (%d jobs)", dailyLimit))
			return
		}
	}
	includeAudio, structured := true, true
	if req.IncludeAudio != nil {
		includeAudio = *req.IncludeAudio
	}
	if req.Structured != nil {
		structured = *req.Structured
	}
	payload := map[string]interface{}{
		"service": "video", "prompt": req.Prompt, "aspect_ratio": req.AspectRatio,
		"size": req.Size, "duration": req.Duration, "num_steps": req.NumSteps,
		"include_audio": includeAudio, "structured_prompt": structured,
		"output_format": req.OutputFormat, "encode_quality": req.EncodeQuality,
	}
	if req.FirstFrame != "" {
		payload["first_frame"] = req.FirstFrame
	}
	status, data, err := manifoldJSON(http.MethodPost, "/api/service", payload)
	if err != nil {
		jsonError(ctx, http.StatusServiceUnavailable, "generation provider unavailable")
		return
	}
	if status < 200 || status >= 300 {
		jsonError(ctx, http.StatusBadGateway, "generation provider rejected the request")
		return
	}
	var upstream struct {
		Result struct {
			JobID  string `json:"job_id"`
			Status string `json:"status"`
		} `json:"result"`
	}
	if json.Unmarshal(data, &upstream) != nil || upstream.Result.JobID == "" {
		jsonError(ctx, http.StatusBadGateway, "generation provider returned no durable job")
		return
	}
	localID := "gen_" + newUUID()
	initial := json.RawMessage(`{}`)
	_, err = dbConn.conn.Exec(
		`INSERT INTO generation_jobs
		 (id, user_id, provider, provider_job_id, service, kind, status, prompt, result, is_public)
		 VALUES ($1,$2,'manifoldgen',$3,'video','video',$4,$5,$6,$7)`,
		localID, user.ID, upstream.Result.JobID, cleanGenerationStatus(upstream.Result.Status), req.Prompt, initial, req.PublishOnFinish,
	)
	if err != nil {
		jsonError(ctx, http.StatusInternalServerError, "could not persist generation job")
		return
	}
	job, _ := getGenerationJob(localID, user.ID)
	jsonResponse(ctx, http.StatusAccepted, map[string]interface{}{
		"job": job, "status_url": "/api/generations/" + localID,
	})
}

func handleGenerationPricing(ctx *fasthttp.RequestCtx) {
	request, err := http.NewRequest(http.MethodGet, manifoldOrigin()+"/api/pricing", nil)
	if err != nil {
		jsonError(ctx, http.StatusServiceUnavailable, "pricing unavailable")
		return
	}
	request.Header.Set("User-Agent", "Mozilla/5.0 CuteDSL-ManifoldGen/1.0")
	response, err := manifoldHTTPClient.Do(request)
	if err != nil {
		jsonError(ctx, http.StatusServiceUnavailable, "pricing unavailable")
		return
	}
	defer response.Body.Close()
	data, err := io.ReadAll(io.LimitReader(response.Body, maxManifoldResponseBytes))
	if err != nil || response.StatusCode != http.StatusOK {
		jsonError(ctx, http.StatusServiceUnavailable, "pricing unavailable")
		return
	}
	ctx.Response.Header.Set("Cache-Control", "public, max-age=300, s-maxage=900, stale-while-revalidate=3600")
	ctx.SetStatusCode(http.StatusOK)
	ctx.Response.Header.SetContentType("application/json")
	ctx.SetBody(data)
}

func cleanGenerationStatus(status string) string {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case "completed", "succeeded", "success":
		return "completed"
	case "failed", "error", "cancelled", "canceled", "timed_out", "payment_required":
		return "failed"
	case "processing", "starting", "running", "in_progress":
		return "processing"
	default:
		return "queued"
	}
}

func scanGeneration(scanner interface{ Scan(...interface{}) error }) (*generationJob, error) {
	var job generationJob
	err := scanner.Scan(&job.ID, &job.ProviderJobID, &job.Service, &job.Kind, &job.Status,
		&job.Prompt, &job.Result, &job.Error, &job.IsPublic, &job.CreatedAt, &job.UpdatedAt)
	return &job, err
}

const generationColumns = `id, provider_job_id, service, kind, status, prompt, result, error, is_public, created_at, updated_at`

func getGenerationJob(id, userID string) (*generationJob, error) {
	return scanGeneration(dbConn.conn.QueryRow(
		`SELECT `+generationColumns+` FROM generation_jobs WHERE id=$1 AND user_id=$2`, id, userID,
	))
}

func refreshGeneration(job *generationJob, userID string) {
	if job == nil || (job.Status != "queued" && job.Status != "processing") {
		return
	}
	status, data, err := manifoldJSON(http.MethodGet, "/api/video-jobs/"+url.PathEscape(job.ProviderJobID), nil)
	if err != nil || (status != http.StatusOK && status != http.StatusAccepted && status != http.StatusPaymentRequired) {
		return
	}
	var upstream struct {
		Job struct {
			Status string          `json:"status"`
			Result json.RawMessage `json:"result"`
			Error  string          `json:"error"`
		} `json:"job"`
	}
	if json.Unmarshal(data, &upstream) != nil {
		return
	}
	next := cleanGenerationStatus(upstream.Job.Status)
	result := upstream.Job.Result
	if len(result) == 0 || string(result) == "null" {
		result = json.RawMessage(`{}`)
	}
	_, _ = dbConn.conn.Exec(
		`UPDATE generation_jobs SET status=$1, result=$2, error=$3, updated_at=NOW()
		 WHERE id=$4 AND user_id=$5`, next, result, upstream.Job.Error, job.ID, userID,
	)
	updated, err := getGenerationJob(job.ID, userID)
	if err == nil {
		*job = *updated
	}
}

func handleGetGeneration(ctx *fasthttp.RequestCtx, id string) {
	user, err := generationUser(ctx, string(ctx.QueryArgs().Peek("wallet_address")))
	if err != nil {
		jsonError(ctx, http.StatusUnauthorized, "valid CuteDSL authorization required")
		return
	}
	job, err := getGenerationJob(strings.TrimSpace(id), user.ID)
	if err != nil {
		jsonError(ctx, http.StatusNotFound, "generation job not found")
		return
	}
	refreshGeneration(job, user.ID)
	status := http.StatusOK
	if job.Status == "queued" || job.Status == "processing" {
		status = http.StatusAccepted
	}
	jsonResponse(ctx, status, map[string]interface{}{"job": job})
}

func handleListGenerations(ctx *fasthttp.RequestCtx) {
	user, err := generationUser(ctx, string(ctx.QueryArgs().Peek("wallet_address")))
	if err != nil {
		jsonError(ctx, http.StatusUnauthorized, "valid CuteDSL authorization required")
		return
	}
	limit, _ := strconv.Atoi(string(ctx.QueryArgs().Peek("limit")))
	if limit < 1 || limit > 100 {
		limit = 50
	}
	rows, err := dbConn.conn.Query(
		`SELECT `+generationColumns+` FROM generation_jobs WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2`, user.ID, limit,
	)
	if err != nil {
		jsonError(ctx, http.StatusInternalServerError, "could not load generations")
		return
	}
	defer rows.Close()
	jobs := make([]*generationJob, 0)
	for rows.Next() {
		job, scanErr := scanGeneration(rows)
		if scanErr == nil {
			jobs = append(jobs, job)
		}
	}
	jsonResponse(ctx, http.StatusOK, map[string]interface{}{"jobs": jobs})
}

func handlePublishGeneration(ctx *fasthttp.RequestCtx, id string) {
	user, err := generationUser(ctx, "")
	if err != nil {
		jsonError(ctx, http.StatusUnauthorized, "valid CuteDSL authorization required")
		return
	}
	job, err := getGenerationJob(strings.TrimSpace(id), user.ID)
	if err != nil {
		jsonError(ctx, http.StatusNotFound, "generation job not found")
		return
	}
	refreshGeneration(job, user.ID)
	if job.Status != "completed" {
		jsonError(ctx, http.StatusConflict, "only completed generations can be published")
		return
	}
	var payload struct {
		Public bool `json:"public"`
	}
	payload.Public = true
	if len(ctx.PostBody()) > 0 && json.Unmarshal(ctx.PostBody(), &payload) != nil {
		jsonError(ctx, http.StatusBadRequest, "invalid json")
		return
	}
	_, err = dbConn.conn.Exec(
		`UPDATE generation_jobs SET is_public=$1, updated_at=NOW() WHERE id=$2 AND user_id=$3`, payload.Public, job.ID, user.ID,
	)
	if err != nil {
		jsonError(ctx, http.StatusInternalServerError, "could not update gallery visibility")
		return
	}
	job.IsPublic = payload.Public
	jsonResponse(ctx, http.StatusOK, map[string]interface{}{"job": job})
}

func handlePublicVideos(ctx *fasthttp.RequestCtx) {
	limit, _ := strconv.Atoi(string(ctx.QueryArgs().Peek("limit")))
	if limit < 1 || limit > 100 {
		limit = 48
	}
	rows, err := dbConn.conn.Query(
		`SELECT `+generationColumns+` FROM generation_jobs
		 WHERE is_public=TRUE AND kind='video' AND status='completed'
		 ORDER BY created_at DESC LIMIT $1`, limit,
	)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		jsonError(ctx, http.StatusInternalServerError, "could not load public videos")
		return
	}
	if rows != nil {
		defer rows.Close()
	}
	jobs := make([]*generationJob, 0)
	for rows != nil && rows.Next() {
		job, scanErr := scanGeneration(rows)
		if scanErr == nil {
			jobs = append(jobs, job)
		}
	}
	// ManifoldGen's featured endpoint is already explicitly public. Merge it
	// with CuteDSL-published jobs so the gallery is useful on first deploy and
	// continues to surface curated work made in either product.
	seen := make(map[string]bool, len(jobs))
	for _, job := range jobs {
		seen[job.ID] = true
	}
	if featured, featuredErr := getManifoldFeaturedVideos(limit); featuredErr == nil {
		for _, item := range featured {
			if seen[item.JobID] || strings.TrimSpace(item.VideoURL) == "" {
				continue
			}
			result, _ := json.Marshal(map[string]interface{}{"video_url": item.VideoURL, "provider": "manifoldgen"})
			jobs = append(jobs, &generationJob{
				ID: item.JobID, ProviderJobID: item.JobID, Service: item.Service,
				Kind: "video", Status: "completed", Prompt: item.Prompt,
				Result: result, IsPublic: true,
			})
			seen[item.JobID] = true
			if len(jobs) >= limit {
				break
			}
		}
	}
	ctx.Response.Header.Set("Cache-Control", "public, max-age=60, s-maxage=300, stale-while-revalidate=3600")
	jsonResponse(ctx, http.StatusOK, map[string]interface{}{"videos": jobs, "count": len(jobs)})
}

type manifoldFeaturedVideo struct {
	JobID    string `json:"job_id"`
	Prompt   string `json:"prompt"`
	VideoURL string `json:"video_url"`
	Service  string `json:"service"`
}

func getManifoldFeaturedVideos(limit int) ([]manifoldFeaturedVideo, error) {
	// Older featured records can contain legacy inline media fields that make
	// large pages unexpectedly multi-megabyte. The newest curated page is all
	// the gallery needs and stays comfortably inside the response limit.
	if limit < 1 || limit > maxManifoldFeaturedVideos {
		limit = maxManifoldFeaturedVideos
	}
	request, err := http.NewRequest(http.MethodGet, manifoldOrigin()+"/api/videos/featured?limit="+strconv.Itoa(limit), nil)
	if err != nil {
		return nil, err
	}
	request.Header.Set("User-Agent", "Mozilla/5.0 CuteDSL-ManifoldGen/1.0")
	response, err := manifoldHTTPClient.Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("featured videos returned %d", response.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, maxManifoldResponseBytes))
	if err != nil {
		return nil, err
	}
	var payload struct {
		Results []manifoldFeaturedVideo `json:"results"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, err
	}
	return payload.Results, nil
}

func generationVideoURL(result json.RawMessage) string {
	var values map[string]interface{}
	if json.Unmarshal(result, &values) != nil {
		return ""
	}
	videoURL, _ := values["video_url"].(string)
	return videoURL
}

func generationDebugString(job *generationJob) string {
	return fmt.Sprintf("%s/%s/%s", job.ID, job.Kind, job.Status)
}

func handleSitemapVideos(ctx *fasthttp.RequestCtx) {
	rows, err := dbConn.conn.Query(
		`SELECT id, prompt, result, created_at FROM generation_jobs
		 WHERE is_public=TRUE AND kind='video' AND status='completed'
		 ORDER BY created_at DESC LIMIT 40000`,
	)
	if err != nil {
		ctx.SetStatusCode(http.StatusInternalServerError)
		return
	}
	defer rows.Close()
	const host = "https://cutedsl.cc"
	const fallbackThumbnail = "https://appstatic.app.nz/cutedsl/images/og-image.webp"
	var body strings.Builder
	body.WriteString(`<?xml version="1.0" encoding="UTF-8"?>` + "\n")
	body.WriteString(`<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
 xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">` + "\n")
	seen := map[string]bool{}
	writeVideo := func(id, prompt, videoURL string, createdAt time.Time) {
		if videoURL == "" || seen[id] {
			return
		}
		seen[id] = true
		title := xmlEscape(truncateRunes(prompt, 100))
		description := xmlEscape(truncateRunes(prompt, 1900))
		fmt.Fprintf(&body, `  <url>
    <loc>%s/video-gallery?video=%s</loc>
    <lastmod>%s</lastmod>
    <video:video>
      <video:thumbnail_loc>%s</video:thumbnail_loc>
      <video:title>%s</video:title>
      <video:description>%s</video:description>
      <video:content_loc>%s</video:content_loc>
      <video:publication_date>%s</video:publication_date>
      <video:family_friendly>yes</video:family_friendly>
    </video:video>
  </url>
`, host, url.QueryEscape(id), createdAt.UTC().Format(time.RFC3339), fallbackThumbnail,
			title, description, xmlEscape(videoURL), createdAt.UTC().Format(time.RFC3339))
	}
	for rows.Next() {
		var id, prompt string
		var result json.RawMessage
		var createdAt time.Time
		if rows.Scan(&id, &prompt, &result, &createdAt) != nil {
			continue
		}
		videoURL := generationVideoURL(result)
		if videoURL == "" {
			continue
		}
		writeVideo(id, prompt, videoURL, createdAt)
	}
	if featured, featuredErr := getManifoldFeaturedVideos(48); featuredErr == nil {
		for _, item := range featured {
			writeVideo(item.JobID, item.Prompt, item.VideoURL, time.Now().UTC())
		}
	}
	body.WriteString("</urlset>\n")
	writeSitemap(ctx, body.String())
}
