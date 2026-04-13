package main

import (
	"fmt"
	"html/template"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/valyala/fasthttp"
)

// slugify converts a string to a URL-safe slug (lowercase, hyphens only).
func slugify(s string) string {
	s = strings.ToLower(s)
	var b strings.Builder
	prevHyphen := true // start true so we don't lead with a hyphen
	for _, r := range s {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') {
			b.WriteRune(r)
			prevHyphen = false
		} else if unicode.IsSpace(r) || r == '-' || r == '_' || r == ',' || r == '.' {
			if !prevHyphen && b.Len() > 0 {
				b.WriteByte('-')
				prevHyphen = true
			}
		}
		if b.Len() >= 80 {
			break
		}
	}
	result := strings.TrimRight(b.String(), "-")
	// Trim at last word boundary if over 72 chars
	if len(result) > 72 {
		idx := strings.LastIndex(result[:72], "-")
		if idx > 40 {
			result = result[:idx]
		} else {
			result = result[:72]
		}
	}
	return result
}

// imageSlug returns the SEO slug for an image: {prompt-slug}-{shortID}
// shortID is the first 8 chars of the UUID (before the first dash).
func imageSlug(id, prompt string) string {
	shortID := id
	if dashIdx := strings.Index(id, "-"); dashIdx > 0 {
		shortID = id[:dashIdx]
	}
	if len(shortID) > 8 {
		shortID = shortID[:8]
	}
	slug := slugify(prompt)
	if slug == "" {
		return shortID
	}
	return slug + "-" + shortID
}

// imagePageURL returns the canonical SEO URL for an image.
func imagePageURL(host, id, prompt string) string {
	return host + "/image/" + imageSlug(id, prompt)
}

// handleSemanticImageSearch is the NEW primary image search endpoint.
// GET /api/images/semantic?q=<query>&top_k=24
// Runs gobed semantic search against generated_images.prompt and hydrates
// the top-K matches into full GeneratedImage rows.
func handleSemanticImageSearch(ctx *fasthttp.RequestCtx) {
	query := string(ctx.QueryArgs().Peek("q"))
	if query == "" {
		jsonError(ctx, 400, "q parameter required")
		return
	}
	topK, _ := strconv.Atoi(string(ctx.QueryArgs().Peek("top_k")))
	if topK < 1 || topK > 200 {
		topK = 24
	}
	allowNSFW := string(ctx.QueryArgs().Peek("allow_nsfw")) == "true"

	if promptSearch == nil || !promptSearch.IsReady() {
		jsonError(ctx, 503, "search engine not ready (still indexing)")
		return
	}

	results, err := promptSearch.Search(query, topK)
	if err != nil {
		jsonError(ctx, 500, "search failed: "+err.Error())
		return
	}

	// Hydrate the image rows
	ids := make([]string, 0, len(results))
	simByID := make(map[string]float32, len(results))
	for _, r := range results {
		ids = append(ids, r.ImageID)
		simByID[r.ImageID] = r.Similarity
	}

	images, err := dbConn.GetImagesByIDs(ids, allowNSFW)
	if err != nil {
		jsonError(ctx, 500, "image lookup failed: "+err.Error())
		return
	}

	// Attach similarity scores
	type ImageWithScore struct {
		GeneratedImage
		Similarity float32 `json:"similarity"`
	}
	out := make([]ImageWithScore, len(images))
	for i, img := range images {
		out[i] = ImageWithScore{GeneratedImage: img, Similarity: simByID[img.ID]}
	}

	jsonResponse(ctx, 200, map[string]interface{}{
		"query":  query,
		"images": out,
		"count":  len(out),
	})
}

// handlePromptAPI returns JSON for a single prompt/image with related results.
// GET /api/prompt/:id
func handlePromptAPI(ctx *fasthttp.RequestCtx, imageID string) {
	imageID = strings.TrimSpace(imageID)
	if imageID == "" {
		jsonError(ctx, 400, "image id required")
		return
	}
	images, err := dbConn.GetImagesByIDs([]string{imageID}, true)
	if err != nil || len(images) == 0 {
		jsonError(ctx, 404, "image not found")
		return
	}
	img := images[0]

	// Related
	var related []GeneratedImage
	if promptSearch != nil && promptSearch.IsReady() {
		sims, _ := promptSearch.SearchRelated(img.Prompt, img.ID, 24)
		if len(sims) > 0 {
			relIDs := make([]string, 0, len(sims))
			for _, r := range sims {
				relIDs = append(relIDs, r.ImageID)
			}
			related, _ = dbConn.GetImagesByIDs(relIDs, false)
		}
	}

	jsonResponse(ctx, 200, map[string]interface{}{
		"image":   img,
		"related": related,
	})
}

// promptPageTemplate is a lightweight, SEO-friendly HTML page served at
// /prompt/<id>. Server-side rendered so crawlers get full content without JS.
var promptPageTemplate = template.Must(template.New("prompt").Parse(`<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{.TitlePrompt}} | CuteDSL AI Art</title>
<meta name="description" content="{{.MetaPrompt}}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta property="og:title" content="{{.TitlePrompt}}">
<meta property="og:description" content="{{.MetaPrompt}}">
<meta property="og:image" content="{{.OGImage}}">
<meta property="og:type" content="article">
<meta property="og:url" content="{{.CanonicalURL}}">
<link rel="canonical" href="{{.CanonicalURL}}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="https://appstatic.app.nz/cutedsl/images/favicon.ico">
<style>
  body{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#fef6fb;color:#1e293b}
  .nav{padding:1.5rem 2rem;display:flex;justify-content:space-between;align-items:center;max-width:72rem;margin:0 auto}
  .nav a{color:#db2777;text-decoration:none;font-weight:700;margin-left:1.5rem}
  .nav .logo{font-size:1.6rem}
  main{max-width:72rem;margin:0 auto;padding:1rem 2rem 4rem}
  h1{font-size:1.4rem;font-weight:700;color:#0f172a;line-height:1.4;margin:1rem 0}
  .hero{background:#fff;border:1px solid #fbcfe8;border-radius:1.25rem;padding:1.5rem;box-shadow:0 4px 20px rgba(244,114,182,.1)}
  .hero img{width:100%;max-height:80vh;object-fit:contain;border-radius:.75rem;background:#f1f5f9}
  .meta{display:flex;flex-wrap:wrap;gap:1rem;font-size:.85rem;color:#64748b;margin-top:1rem}
  .meta span{background:#f1f5f9;padding:.25rem .75rem;border-radius:9999px}
  h2{font-size:1.1rem;font-weight:700;color:#0f172a;margin:2.5rem 0 1rem}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:1rem}
  .card{background:#fff;border:1px solid #f1f5f9;border-radius:.75rem;overflow:hidden;transition:transform .15s}
  .card:hover{transform:translateY(-2px);border-color:#fbcfe8}
  .card a{display:block;color:inherit;text-decoration:none}
  .card img{width:100%;aspect-ratio:1;object-fit:cover;display:block;background:#f1f5f9}
  .card p{font-size:.75rem;color:#64748b;padding:.5rem;line-height:1.4;margin:0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  footer{text-align:center;color:#94a3b8;font-size:.85rem;padding:2rem 0;margin-top:3rem;border-top:1px solid #f1f5f9}
</style>
</head>
<body>
<nav class="nav">
  <a href="/" class="logo">🦋 CuteDSL</a>
  <div>
    <a href="/gallery">Gallery</a>
    <a href="/search">Search</a>
    <a href="/docs">Docs</a>
  </div>
</nav>
<main>
  <div class="hero">
    <img src="{{.ImageURL}}" alt="{{.AltText}}" loading="eager">
    <h1>{{.TitlePrompt}}</h1>
    <div class="meta">
      <span>{{.Image.Width}}×{{.Image.Height}}</span>
      <span>Model: {{.Image.Model}}</span>
      <span>Steps: {{.Image.Steps}}</span>
      {{if .Image.Seed}}<span>Seed: {{.Image.Seed}}</span>{{end}}
    </div>
  </div>

  {{if .Related}}
  <h2>Related images</h2>
  <div class="grid">
    {{range .Related}}
    <article class="card">
      <a href="/image/{{.Slug}}">
        <img src="/images/{{if .ThumbPath}}{{.ThumbPath}}{{else}}{{.FilePath}}{{end}}" alt="{{.Prompt}}" loading="lazy">
        <p>{{.Prompt}}</p>
      </a>
    </article>
    {{end}}
  </div>
  {{end}}
</main>
<footer>
  © {{.Year}} <a href="https://cutedsl.app.nz" style="color:#db2777">CuteDSL</a> — AI-generated
</footer>
</body>
</html>`))

// handlePromptHTML server-renders /prompt/<id> as a full HTML page so that
// search engines can index the image + caption + related thumbnails.
func handlePromptHTML(ctx *fasthttp.RequestCtx, imageID string) {
	imageID = strings.TrimSpace(imageID)
	if imageID == "" {
		ctx.SetStatusCode(404)
		ctx.SetBodyString("prompt not found")
		return
	}
	images, err := dbConn.GetImagesByIDs([]string{imageID}, true)
	if err != nil || len(images) == 0 {
		ctx.SetStatusCode(404)
		ctx.Response.Header.Set("Content-Type", "text/html; charset=utf-8")
		ctx.SetBodyString(`<!DOCTYPE html><html><body style="font-family:system-ui;text-align:center;padding:4rem"><h1>Prompt not found</h1><a href="/search">Browse gallery</a></body></html>`)
		return
	}
	img := images[0]

	// Related images via semantic search
	var related []GeneratedImage
	if promptSearch != nil && promptSearch.IsReady() {
		sims, _ := promptSearch.SearchRelated(img.Prompt, img.ID, 12)
		if len(sims) > 0 {
			relIDs := make([]string, 0, len(sims))
			for _, r := range sims {
				relIDs = append(relIDs, r.ImageID)
			}
			related, _ = dbConn.GetImagesByIDs(relIDs, false)
		}
	}

	// Choose medium-size image for the hero if available, else original
	imgPath := img.FilePath
	if img.MedPath != "" {
		imgPath = img.MedPath
	}

	// Truncate prompt for title/meta
	titlePrompt := img.Prompt
	if len(titlePrompt) > 80 {
		titlePrompt = titlePrompt[:77] + "..."
	}
	metaPrompt := img.Prompt
	if len(metaPrompt) > 160 {
		metaPrompt = metaPrompt[:157] + "..."
	}
	altText := img.Prompt
	if len(altText) > 200 {
		altText = altText[:197] + "..."
	}

	type RelatedEntry struct {
		GeneratedImage
		Slug string
	}
	relEntries := make([]RelatedEntry, len(related))
	for i, r := range related {
		relEntries[i] = RelatedEntry{GeneratedImage: r, Slug: imageSlug(r.ID, r.Prompt)}
	}

	host := "https://cutedsl.app.nz"
	data := struct {
		Image        GeneratedImage
		Related      []RelatedEntry
		TitlePrompt  string
		MetaPrompt   string
		AltText      string
		ImageURL     string
		OGImage      string
		CanonicalURL string
		Year         int
	}{
		Image:        img,
		Related:      relEntries,
		TitlePrompt:  titlePrompt,
		MetaPrompt:   metaPrompt,
		AltText:      altText,
		ImageURL:     "/images/" + imgPath,
		OGImage:      host + "/images/" + imgPath,
		CanonicalURL: imagePageURL(host, img.ID, img.Prompt),
		Year:         time.Now().Year(),
	}

	ctx.Response.Header.Set("Content-Type", "text/html; charset=utf-8")
	ctx.Response.Header.Set("Cache-Control", "public, max-age=3600")
	if err := promptPageTemplate.Execute(ctx, data); err != nil {
		ctx.SetStatusCode(500)
		ctx.SetBodyString("template error")
	}
}

// ---------------- Sitemap ----------------

const sitemapPageSize = 40000 // URLs per sitemap file

// handleSitemapIndex serves /sitemap.xml as a sitemap-index pointing to
// the static site pages + one image sitemap per chunk of 40k images.
func handleSitemapIndex(ctx *fasthttp.RequestCtx) {
	count, err := dbConn.GetImageCount()
	if err != nil {
		count = 0
	}
	numImgMaps := (count + sitemapPageSize - 1) / sitemapPageSize

	host := "https://cutedsl.app.nz"
	var sb strings.Builder
	sb.WriteString(`<?xml version="1.0" encoding="UTF-8"?>` + "\n")
	sb.WriteString(`<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">` + "\n")

	// Static site pages sitemap
	sb.WriteString("  <sitemap><loc>" + host + "/sitemap-pages.xml</loc></sitemap>\n")

	// Paginated image sitemaps
	for i := 1; i <= numImgMaps; i++ {
		fmt.Fprintf(&sb, "  <sitemap><loc>%s/sitemap-images-%d.xml</loc></sitemap>\n", host, i)
	}
	sb.WriteString(`</sitemapindex>` + "\n")

	ctx.Response.Header.Set("Content-Type", "application/xml; charset=utf-8")
	ctx.Response.Header.Set("Cache-Control", "public, max-age=3600")
	ctx.SetBodyString(sb.String())
}

// handleSitemapPages serves the list of static site pages
func handleSitemapPages(ctx *fasthttp.RequestCtx) {
	host := "https://cutedsl.app.nz"
	pages := []string{
		"/", "/search", "/gallery", "/docs", "/blog", "/evals", "/lora-trainer", "/api-docs",
		"/docs/zimage", "/docs/chronos2", "/docs/tts", "/docs/stt",
		"/docs/gemma4", "/docs/caption", "/docs/flux_image", "/docs/ltx_video", "/docs/lora_training",
	}
	var sb strings.Builder
	sb.WriteString(`<?xml version="1.0" encoding="UTF-8"?>` + "\n")
	sb.WriteString(`<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">` + "\n")
	for _, p := range pages {
		fmt.Fprintf(&sb, "  <url><loc>%s%s</loc><changefreq>weekly</changefreq></url>\n", host, p)
	}
	sb.WriteString(`</urlset>` + "\n")
	ctx.Response.Header.Set("Content-Type", "application/xml; charset=utf-8")
	ctx.Response.Header.Set("Cache-Control", "public, max-age=3600")
	ctx.SetBodyString(sb.String())
}

// handleSitemapImages serves one page (N) of the image sitemap with Image
// extension tags so search engines can index the actual images too.
func handleSitemapImages(ctx *fasthttp.RequestCtx, pageStr string) {
	page, err := strconv.Atoi(pageStr)
	if err != nil || page < 1 {
		ctx.SetStatusCode(404)
		return
	}
	offset := (page - 1) * sitemapPageSize

	rows, err := dbConn.conn.Query(
		`SELECT id, prompt, file_path, med_path, thumb_path FROM generated_images
		 WHERE (is_nsfw = FALSE OR is_nsfw IS NULL)
		 ORDER BY created_at DESC LIMIT $1 OFFSET $2`,
		sitemapPageSize, offset,
	)
	if err != nil {
		ctx.SetStatusCode(500)
		return
	}
	defer rows.Close()

	host := "https://cutedsl.app.nz"
	var sb strings.Builder
	sb.WriteString(`<?xml version="1.0" encoding="UTF-8"?>` + "\n")
	sb.WriteString(`<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
     xmlns:image="http://www.google.com/schemas/sitemaps-image/1.1">` + "\n")

	n := 0
	for rows.Next() {
		var id, prompt, fp, med, thumb string
		if err := rows.Scan(&id, &prompt, &fp, &med, &thumb); err != nil {
			continue
		}
		imgPath := fp
		if med != "" {
			imgPath = med
		}
		_ = thumb
		caption := xmlEscape(prompt)
		if len(caption) > 300 {
			caption = caption[:297] + "..."
		}
		slug := imageSlug(id, prompt)
		title := xmlEscape(prompt)
		if len(title) > 100 {
			title = title[:97] + "..."
		}
		fmt.Fprintf(&sb,
			`  <url>
    <loc>%s/image/%s</loc>
    <changefreq>monthly</changefreq>
    <image:image>
      <image:loc>%s/images/%s</image:loc>
      <image:caption>%s</image:caption>
      <image:title>%s</image:title>
    </image:image>
  </url>
`, host, slug, host, imgPath, caption, title)
		n++
	}
	sb.WriteString(`</urlset>` + "\n")

	if n == 0 {
		ctx.SetStatusCode(404)
		return
	}
	ctx.Response.Header.Set("Content-Type", "application/xml; charset=utf-8")
	ctx.Response.Header.Set("Cache-Control", "public, max-age=3600")
	ctx.SetBodyString(sb.String())
}

// xmlEscape escapes the minimum characters needed for XML text content.
func xmlEscape(s string) string {
	replacer := strings.NewReplacer(
		"&", "&amp;",
		"<", "&lt;",
		">", "&gt;",
		"\"", "&quot;",
		"'", "&apos;",
	)
	return replacer.Replace(s)
}

// handleImageBySlug serves /image/<slug> where slug ends in -{shortID}.
// shortID is the first 8 chars of the UUID. We look up by id LIKE shortID||'-%'.
func handleImageBySlug(ctx *fasthttp.RequestCtx, slug string) {
	slug = strings.TrimSpace(slug)
	if slug == "" {
		ctx.SetStatusCode(404)
		ctx.SetBodyString("not found")
		return
	}

	// Extract shortID: last token after the final '-'
	shortID := slug
	if idx := strings.LastIndex(slug, "-"); idx >= 0 {
		shortID = slug[idx+1:]
	}
	if len(shortID) == 0 {
		ctx.SetStatusCode(404)
		ctx.SetBodyString("not found")
		return
	}

	// Look up the image by the shortID prefix. UUID format: xxxxxxxx-xxxx-...
	// so shortID matches the first segment of the UUID.
	row := dbConn.conn.QueryRow(
		`SELECT id FROM generated_images WHERE id LIKE $1 || '-%' OR id = $1 LIMIT 1`,
		shortID,
	)
	var imageID string
	if err := row.Scan(&imageID); err != nil {
		ctx.SetStatusCode(404)
		ctx.Response.Header.Set("Content-Type", "text/html; charset=utf-8")
		ctx.SetBodyString(`<!DOCTYPE html><html><body style="font-family:system-ui;text-align:center;padding:4rem"><h1>Image not found</h1><a href="/gallery">Browse gallery</a></body></html>`)
		return
	}

	// Render using the shared prompt HTML handler but with the canonical /image/ URL
	handlePromptHTML(ctx, imageID)
}
