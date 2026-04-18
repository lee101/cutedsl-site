package main

import (
	"encoding/json"
	"fmt"
	"html/template"
	"net/url"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/valyala/fasthttp"
)

// stopwords filtered out of keyword tag extraction.
var stopwords = map[string]bool{
	"the": true, "a": true, "an": true, "of": true, "in": true,
	"with": true, "and": true, "for": true, "to": true, "at": true,
	"by": true, "on": true, "as": true, "is": true, "are": true,
	"was": true, "be": true, "has": true, "from": true, "that": true,
	"this": true, "it": true, "its": true, "or": true, "not": true,
	"but": true, "so": true, "if": true, "into": true, "over": true,
	"under": true, "very": true, "just": true, "than": true, "then": true,
	"through": true, "upon": true, "about": true, "against": true,
	"after": true, "before": true, "between": true, "while": true,
	"style": true, "art": true, "image": true, "photo": true,
}

// extractTags pulls meaningful keywords from a prompt for SEO tag pills.
func extractTags(prompt string) []string {
	seen := map[string]bool{}
	var tags []string
	words := strings.FieldsFunc(strings.ToLower(prompt), func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r)
	})
	for _, w := range words {
		if len(w) < 4 || stopwords[w] || seen[w] {
			continue
		}
		seen[w] = true
		// Capitalise for display
		tags = append(tags, strings.ToUpper(w[:1])+w[1:])
		if len(tags) >= 14 {
			break
		}
	}
	return tags
}

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

// promptPageTemplate is a rich, SEO-optimised HTML page served at /image/<slug>
// and /prompt/<id>. Server-side rendered so crawlers get full content without JS.
var promptPageTemplate = template.Must(template.New("prompt").Funcs(template.FuncMap{
	"urlquery": url.QueryEscape,
	"linkify":  linkifyPrompt,
	"lower":    strings.ToLower,
	"tagslug":  slugify,
}).Parse(`<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{.TitlePrompt}} | CuteDSL AI Art</title>
<meta name="description" content="{{.MetaPrompt}}">
<meta name="keywords" content="{{.Keywords}}">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- Open Graph -->
<meta property="og:title" content="{{.TitlePrompt}}">
<meta property="og:description" content="{{.MetaPrompt}}">
<meta property="og:image" content="{{.OGImage}}">
<meta property="og:image:width" content="{{.Image.Width}}">
<meta property="og:image:height" content="{{.Image.Height}}">
<meta property="og:image:type" content="image/webp">
<meta property="og:image:alt" content="{{.AltText}}">
<meta property="og:type" content="article">
<meta property="og:url" content="{{.CanonicalURL}}">
<meta property="og:site_name" content="CuteDSL AI Art">
<meta property="article:published_time" content="{{.Published}}">
<meta property="article:section" content="AI Art">
<!-- Twitter / X -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{{.TitlePrompt}}">
<meta name="twitter:description" content="{{.MetaPrompt}}">
<meta name="twitter:image" content="{{.OGImage}}">
<meta name="twitter:image:alt" content="{{.AltText}}">
<meta name="twitter:site" content="@cutedsl">
<!-- Canonical + preload -->
<link rel="canonical" href="{{.CanonicalURL}}">
<link rel="preload" as="image" href="{{.ImageURL}}">
<link rel="icon" href="https://appstatic.app.nz/cutedsl/images/favicon.ico">
<!-- JSON-LD structured data -->
<script type="application/ld+json">{{.JSONLD}}</script>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;background:#fef6fb;color:#1e293b;line-height:1.6}
a{color:inherit;text-decoration:none}
.nav{padding:1.25rem 2rem;display:flex;justify-content:space-between;align-items:center;max-width:80rem;margin:0 auto}
.nav-logo{font-size:1.5rem;font-weight:800;color:#db2777;display:flex;align-items:center;gap:.5rem}
.nav-links a{color:#475569;font-weight:600;margin-left:1.5rem;font-size:.9rem;transition:color .15s}
.nav-links a:hover{color:#db2777}
.breadcrumb{max-width:80rem;margin:0 auto;padding:.5rem 2rem 0;font-size:.8rem;color:#94a3b8;display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}
.breadcrumb a{color:#94a3b8;transition:color .15s}.breadcrumb a:hover{color:#db2777}
.breadcrumb span{color:#cbd5e1}
main{max-width:80rem;margin:0 auto;padding:1.25rem 2rem 5rem;display:grid;grid-template-columns:1fr 340px;gap:2rem}
@media(max-width:900px){main{grid-template-columns:1fr;padding:1rem 1rem 4rem}}
.hero-col{}
.hero-img-wrap{background:#fff;border:1px solid #fbcfe8;border-radius:1.25rem;overflow:hidden;box-shadow:0 4px 24px rgba(219,39,119,.08)}
.hero-img-wrap img{width:100%;display:block;max-height:75vh;object-fit:contain;background:#f8fafc}
.info-col{}
.info-card{background:#fff;border:1px solid #fce7f3;border-radius:1.25rem;padding:1.5rem;box-shadow:0 2px 12px rgba(219,39,119,.06);position:sticky;top:1.5rem}
h1{font-size:1.1rem;font-weight:700;color:#0f172a;line-height:1.5;margin:0 0 1.25rem}
.meta-grid{display:grid;grid-template-columns:1fr 1fr;gap:.5rem;margin-bottom:1.25rem}
.meta-item{background:#f8fafc;border:1px solid #e2e8f0;border-radius:.6rem;padding:.4rem .7rem}
.meta-label{font-size:.68rem;color:#94a3b8;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.meta-value{font-size:.85rem;font-weight:700;color:#334155}
.actions{display:flex;flex-direction:column;gap:.6rem;margin-bottom:1.25rem}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:.4rem;padding:.6rem 1rem;border-radius:.75rem;font-size:.85rem;font-weight:700;cursor:pointer;transition:all .15s;border:none;text-align:center}
.btn-primary{background:linear-gradient(135deg,#ec4899,#a855f7);color:#fff;box-shadow:0 2px 12px rgba(236,72,153,.3)}
.btn-primary:hover{box-shadow:0 4px 20px rgba(236,72,153,.45);transform:translateY(-1px)}
.btn-secondary{background:#f1f5f9;color:#334155;border:1px solid #e2e8f0}
.btn-secondary:hover{background:#e2e8f0}
.btn-download{background:#fff;color:#0f172a;border:1px solid #e2e8f0}
.btn-download:hover{border-color:#db2777;color:#db2777}
.section-title{font-size:.85rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.06em;margin:1.25rem 0 .6rem}
.tags{display:flex;flex-wrap:wrap;gap:.4rem}
.tag{font-size:.75rem;font-weight:600;padding:.25rem .65rem;border-radius:9999px;background:linear-gradient(135deg,#fdf2f8,#faf5ff);border:1px solid #f0abfc;color:#86198f;transition:all .15s}
.tag:hover{background:linear-gradient(135deg,#f9a8d4,#d8b4fe);color:#fff;border-color:transparent}
.prompt-box{background:#fdf2f8;border:1px solid #fce7f3;border-radius:.75rem;padding:.85rem 1rem;font-size:.82rem;color:#475569;line-height:1.7;margin-bottom:1.25rem}
.prompt-box a.prompt-word{color:#86198f;font-weight:600;border-bottom:1px dotted #f0abfc;transition:all .15s;padding:0 1px;border-radius:3px}
.prompt-box a.prompt-word:hover{background:#fce7f3;color:#db2777;border-bottom-color:transparent}
/* Related section spans full width below */
.related-section{grid-column:1/-1;margin-top:.5rem}
h2{font-size:1.2rem;font-weight:800;color:#0f172a;margin:0 0 1rem;display:flex;align-items:center;gap:.5rem}
.related-grid{columns:2;column-gap:.75rem}
@media(min-width:480px){.related-grid{columns:3}}
@media(min-width:700px){.related-grid{columns:4}}
@media(min-width:1000px){.related-grid{columns:5}}
@media(min-width:1280px){.related-grid{columns:6}}
.card{break-inside:avoid;margin-bottom:.75rem;background:#fff;border:1px solid #f1f5f9;border-radius:.875rem;overflow:hidden;transition:transform .15s,box-shadow .15s,border-color .15s}
.card:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgba(219,39,119,.12);border-color:#fbcfe8}
.card a{display:block;color:inherit}
.card img{width:100%;display:block;background:#f1f5f9}
.card p{font-size:.72rem;color:#64748b;padding:.45rem .6rem .5rem;line-height:1.4;margin:0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
footer{text-align:center;color:#94a3b8;font-size:.82rem;padding:2rem 0 3rem;border-top:1px solid #fce7f3}
footer a{color:#db2777}
</style>
</head>
<body>
<nav class="nav">
  <a href="/" class="nav-logo">🦋 CuteDSL</a>
  <div class="nav-links">
    <a href="/gallery">Gallery</a>
    <a href="/search">Search</a>
    <a href="/docs">API Docs</a>
    <a href="/">Generate</a>
  </div>
</nav>

<nav class="breadcrumb" aria-label="Breadcrumb">
  <a href="/">Home</a>
  <span>›</span>
  <a href="/gallery">Gallery</a>
  <span>›</span>
  <span style="color:#475569;max-width:40ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{.TitlePrompt}}</span>
</nav>

<main>
  <!-- Hero image -->
  <div class="hero-col">
    <div class="hero-img-wrap">
      <img src="{{.ImageURL}}" alt="{{.AltText}}" loading="eager" width="{{.Image.Width}}" height="{{.Image.Height}}">
    </div>
  </div>

  <!-- Info sidebar -->
  <div class="info-col">
    <div class="info-card">
      <h1>{{.TitlePrompt}}</h1>

      <div class="prompt-box" aria-label="Prompt (click any word to search)">{{linkify .Image.Prompt}}</div>

      <div class="actions">
        <a href="/" class="btn btn-primary">✨ Generate similar image</a>
        <a href="{{.FullImageURL}}" download class="btn btn-download">⬇ Download full resolution</a>
        <button onclick="navigator.clipboard.writeText(this.dataset.p);this.textContent='✓ Copied!';setTimeout(()=>this.textContent='📋 Copy prompt',2000)" data-p="{{.CopyPrompt}}" class="btn btn-secondary">📋 Copy prompt</button>
      </div>

      <div class="section-title">Details</div>
      <div class="meta-grid">
        <div class="meta-item"><div class="meta-label">Dimensions</div><div class="meta-value">{{.Image.Width}}×{{.Image.Height}}</div></div>
        <div class="meta-item"><div class="meta-label">Model</div><div class="meta-value">{{.Image.Model}}</div></div>
        <div class="meta-item"><div class="meta-label">Steps</div><div class="meta-value">{{.Image.Steps}}</div></div>
        {{if .Image.Seed}}<div class="meta-item"><div class="meta-label">Seed</div><div class="meta-value">{{.Image.Seed}}</div></div>{{end}}
        <div class="meta-item"><div class="meta-label">Published</div><div class="meta-value">{{.PublishedShort}}</div></div>
        {{if .Image.FileSize}}<div class="meta-item"><div class="meta-label">File size</div><div class="meta-value">{{.FileSizeKB}} KB</div></div>{{end}}
      </div>

      {{if .Tags}}
      <div class="section-title">Tags</div>
      <div class="tags">
        {{range .Tags}}<a href="/tag/{{. | tagslug}}" class="tag" rel="tag">{{.}}</a>{{end}}
      </div>
      {{end}}
    </div>
  </div>

  {{if .Related}}
  <section class="related-section">
    <h2>🎨 Related images <span style="font-size:.85rem;color:#94a3b8;font-weight:500">({{len .Related}})</span></h2>
    <div class="related-grid">
      {{range .Related}}
      <article class="card" itemscope itemtype="https://schema.org/ImageObject">
        <a href="/image/{{.Slug}}" itemprop="url">
          <img src="/images/{{if .ThumbPath}}{{.ThumbPath}}{{else}}{{.FilePath}}{{end}}"
               alt="{{.Prompt}}" loading="lazy" itemprop="thumbnailUrl"
               style="aspect-ratio:{{.Width}}/{{.Height}}">
          <p itemprop="description">{{.Prompt}}</p>
        </a>
      </article>
      {{end}}
    </div>
  </section>
  {{end}}
</main>

<footer>
  <p>© {{.Year}} <a href="https://cutedsl.cc">CuteDSL</a> — AI-generated art powered by Z-Image Turbo on Solana</p>
  <p style="margin-top:.5rem;font-size:.75rem">
    <a href="/gallery">Gallery</a> · <a href="/search">Search</a> · <a href="/docs">API</a> · <a href="/evals">Evals</a>
  </p>
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
		ctx.SetBodyString(`<!DOCTYPE html><html><body style="font-family:system-ui;text-align:center;padding:4rem"><h1>Prompt not found</h1><a href="/gallery">Browse gallery</a></body></html>`)
		return
	}
	img := images[0]

	// Related images via semantic search — fetch 24
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

	host := "https://cutedsl.cc"
	canonicalURL := imagePageURL(host, img.ID, img.Prompt)
	tags := extractTags(img.Prompt)

	// Build keywords meta string
	kwLower := make([]string, len(tags))
	for i, t := range tags {
		kwLower[i] = strings.ToLower(t)
	}
	keywords := strings.Join(kwLower, ", ") + ", ai art, ai generated, cutedsl, z-image turbo, stable diffusion"

	// JSON-LD structured data
	thumbURL := host + "/images/" + img.FilePath
	if img.ThumbPath != "" {
		thumbURL = host + "/images/" + img.ThumbPath
	}
	relatedURLs := make([]map[string]interface{}, 0, len(relEntries))
	for _, r := range relEntries {
		relatedURLs = append(relatedURLs, map[string]interface{}{
			"@type": "ImageObject",
			"url":   host + "/image/" + r.Slug,
			"thumbnailUrl": func() string {
				if r.ThumbPath != "" {
					return host + "/images/" + r.ThumbPath
				}
				return host + "/images/" + r.FilePath
			}(),
			"description": func() string {
				p := r.Prompt
				if len(p) > 120 {
					p = p[:117] + "..."
				}
				return p
			}(),
		})
	}

	jsonLDData := map[string]interface{}{
		"@context": "https://schema.org",
		"@graph": []interface{}{
			map[string]interface{}{
				"@type":          "ImageObject",
				"@id":            canonicalURL + "#image",
				"contentUrl":     host + "/images/" + img.FilePath,
				"url":            canonicalURL,
				"thumbnailUrl":   thumbURL,
				"description":    img.Prompt,
				"name":           titlePrompt,
				"width":          img.Width,
				"height":         img.Height,
				"encodingFormat": "image/webp",
				"datePublished":  img.CreatedAt.Format(time.RFC3339),
				"author": map[string]interface{}{
					"@type": "Organization",
					"name":  "CuteDSL",
					"url":   "https://cutedsl.cc",
				},
				"license":         "https://creativecommons.org/licenses/by/4.0/",
				"acquireLicensePage": "https://cutedsl.cc",
				"keywords":        keywords,
				"relatedLink":     canonicalURL,
			},
			map[string]interface{}{
				"@type": "BreadcrumbList",
				"itemListElement": []interface{}{
					map[string]interface{}{"@type": "ListItem", "position": 1, "name": "Home", "item": "https://cutedsl.cc"},
					map[string]interface{}{"@type": "ListItem", "position": 2, "name": "Gallery", "item": "https://cutedsl.cc/gallery"},
					map[string]interface{}{"@type": "ListItem", "position": 3, "name": titlePrompt, "item": canonicalURL},
				},
			},
			map[string]interface{}{
				"@type":            "WebPage",
				"@id":              canonicalURL,
				"url":              canonicalURL,
				"name":             titlePrompt + " | CuteDSL AI Art",
				"description":      metaPrompt,
				"datePublished":    img.CreatedAt.Format(time.RFC3339),
				"inLanguage":       "en",
				"isPartOf":         map[string]interface{}{"@type": "WebSite", "name": "CuteDSL", "url": "https://cutedsl.cc"},
				"primaryImageOfPage": map[string]interface{}{"@id": canonicalURL + "#image"},
			},
		},
	}
	jsonLDBytes, _ := json.Marshal(jsonLDData)

	year := time.Now().Year()
	fileSizeKB := img.FileSize / 1024

	data := struct {
		Image          GeneratedImage
		Related        []RelatedEntry
		Tags           []string
		TitlePrompt    string
		MetaPrompt     string
		AltText        string
		Keywords       string
		ImageURL       string
		FullImageURL   string
		OGImage        string
		CanonicalURL   string
		CopyPrompt     string
		JSONLD         template.HTML
		Published      string
		PublishedShort string
		FileSizeKB     int64
		Year           int
	}{
		Image:          img,
		Related:        relEntries,
		Tags:           tags,
		TitlePrompt:    titlePrompt,
		MetaPrompt:     metaPrompt,
		AltText:        altText,
		Keywords:       keywords,
		ImageURL:       "/images/" + imgPath,
		FullImageURL:   "/images/" + img.FilePath,
		OGImage:        host + "/images/" + imgPath,
		CanonicalURL:   canonicalURL,
		CopyPrompt:     img.Prompt,
		JSONLD:         template.HTML(jsonLDBytes),
		Published:      img.CreatedAt.Format(time.RFC3339),
		PublishedShort: img.CreatedAt.Format("Jan 2006"),
		FileSizeKB:     fileSizeKB,
		Year:           year,
	}
	_ = relatedURLs // included in JSON-LD above

	ctx.Response.Header.Set("Content-Type", "text/html; charset=utf-8")
	ctx.Response.Header.Set("Cache-Control", "public, max-age=3600")
	if err := promptPageTemplate.Execute(ctx, data); err != nil {
		ctx.SetStatusCode(500)
		ctx.SetBodyString("template error")
	}
}

// ---------------- Sitemap ----------------

const sitemapPageSize = 40000 // URLs per sitemap file

// writeSitemap writes an XML sitemap body with the correct Content-Type and
// transparently gzips the response when the client advertises Accept-Encoding:
// gzip. Image sitemaps can be 20MB+ uncompressed — without this, Google's
// crawler often times out fetching them.
func writeSitemap(ctx *fasthttp.RequestCtx, body string) {
	ctx.Response.Header.Set("Content-Type", "application/xml; charset=utf-8")
	ctx.Response.Header.Set("Cache-Control", "public, max-age=3600")
	ctx.Response.Header.Set("Vary", "Accept-Encoding")

	ae := string(ctx.Request.Header.Peek("Accept-Encoding"))
	if strings.Contains(ae, "gzip") {
		gzipped := fasthttp.AppendGzipBytesLevel(nil, []byte(body), fasthttp.CompressDefaultCompression)
		ctx.Response.Header.Set("Content-Encoding", "gzip")
		ctx.SetBody(gzipped)
		return
	}
	ctx.SetBodyString(body)
}

// handleSitemapIndex serves /sitemap.xml as a sitemap-index pointing to
// the static site pages + one image sitemap per chunk of 40k images.
func handleSitemapIndex(ctx *fasthttp.RequestCtx) {
	count, err := dbConn.GetImageCount()
	if err != nil {
		count = 0
	}
	numImgMaps := (count + sitemapPageSize - 1) / sitemapPageSize

	host := "https://cutedsl.cc"
	var sb strings.Builder
	sb.WriteString(`<?xml version="1.0" encoding="UTF-8"?>` + "\n")
	sb.WriteString(`<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">` + "\n")

	// Static site pages sitemap
	sb.WriteString("  <sitemap><loc>" + host + "/sitemap-pages.xml</loc></sitemap>\n")

	// Curated tag sitemap (SEO-rich landing pages per tag)
	sb.WriteString("  <sitemap><loc>" + host + "/sitemap-tags.xml</loc></sitemap>\n")

	// Paginated image sitemaps
	for i := 1; i <= numImgMaps; i++ {
		fmt.Fprintf(&sb, "  <sitemap><loc>%s/sitemap-images-%d.xml</loc></sitemap>\n", host, i)
	}
	sb.WriteString(`</sitemapindex>` + "\n")

	writeSitemap(ctx, sb.String())
}

// handleSitemapPages serves the list of static site pages
func handleSitemapPages(ctx *fasthttp.RequestCtx) {
	host := "https://cutedsl.cc"
	pages := []string{
		"/", "/search", "/gallery", "/tags", "/docs", "/blog", "/evals", "/lora-trainer", "/api-docs",
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
	writeSitemap(ctx, sb.String())
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

	host := "https://cutedsl.cc"
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
		// Truncate BEFORE escaping, on rune boundaries — otherwise we can
		// split a multi-byte UTF-8 char or an XML entity like &apos; in half,
		// producing invalid XML that Google refuses to parse.
		caption := xmlEscape(truncateRunes(prompt, 300))
		slug := imageSlug(id, prompt)
		title := xmlEscape(truncateRunes(prompt, 100))
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
	writeSitemap(ctx, sb.String())
}

// xmlEscape escapes the minimum characters needed for XML text content,
// and strips ASCII control chars (0x00-0x1F except \t \n \r) that are
// illegal in XML 1.0 and would make the whole document unparseable.
func xmlEscape(s string) string {
	var b strings.Builder
	b.Grow(len(s))
	for _, r := range s {
		if r < 0x20 && r != '\t' && r != '\n' && r != '\r' {
			continue
		}
		switch r {
		case '&':
			b.WriteString("&amp;")
		case '<':
			b.WriteString("&lt;")
		case '>':
			b.WriteString("&gt;")
		case '"':
			b.WriteString("&quot;")
		case '\'':
			b.WriteString("&apos;")
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

// truncateRunes returns s truncated to at most maxRunes runes (plus "..." if
// truncated). Operates on runes so multi-byte UTF-8 chars aren't split.
func truncateRunes(s string, maxRunes int) string {
	runes := []rune(s)
	if len(runes) <= maxRunes {
		return s
	}
	if maxRunes <= 3 {
		return string(runes[:maxRunes])
	}
	return string(runes[:maxRunes-3]) + "..."
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
