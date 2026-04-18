package main

import (
	"encoding/json"
	"fmt"
	"html/template"
	"net/url"
	"strings"
	"time"
	"unicode"

	"github.com/valyala/fasthttp"
)

// linkifyPrompt converts a raw prompt into HTML where every significant word
// (>=3 letters, non-stopword) becomes a link to /tag/<slug>.
// This gives crawlers rich deep-linking into curated & dynamic tag pages.
func linkifyPrompt(prompt string) template.HTML {
	if prompt == "" {
		return ""
	}

	var b strings.Builder
	b.Grow(len(prompt) * 4)

	var word strings.Builder
	flush := func() {
		if word.Len() == 0 {
			return
		}
		w := word.String()
		word.Reset()
		lower := strings.ToLower(w)
		// Skip tiny or stopword tokens — render as plain text.
		if len(lower) < 3 || stopwords[lower] {
			b.WriteString(template.HTMLEscapeString(w))
			return
		}
		slug := slugify(lower)
		if slug == "" {
			b.WriteString(template.HTMLEscapeString(w))
			return
		}
		fmt.Fprintf(&b,
			`<a href="/tag/%s" class="prompt-word" rel="tag">%s</a>`,
			url.PathEscape(slug), template.HTMLEscapeString(w),
		)
	}

	for _, r := range prompt {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			word.WriteRune(r)
			continue
		}
		flush()
		// Preserve original whitespace / punctuation (escaped).
		b.WriteString(template.HTMLEscapeString(string(r)))
	}
	flush()
	return template.HTML(b.String())
}

// tagPageTemplate renders /tag/<slug> with a Pinterest-style grid of
// semantic-matched images. Self-contained styles match the rest of the site.
var tagPageTemplate = template.Must(template.New("tag").Funcs(template.FuncMap{
	"urlquery": url.QueryEscape,
	"linkify":  linkifyPrompt,
}).Parse(`<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{.Display}} AI Art — {{.Count}} Images | CuteDSL</title>
<meta name="description" content="{{.MetaDescription}}">
<meta name="keywords" content="{{.Keywords}}">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta property="og:type" content="website">
<meta property="og:title" content="{{.Display}} AI Art — CuteDSL">
<meta property="og:description" content="{{.MetaDescription}}">
<meta property="og:url" content="{{.CanonicalURL}}">
<meta property="og:site_name" content="CuteDSL AI Art">
{{if .HeroImageURL}}<meta property="og:image" content="{{.HeroImageURL}}">{{end}}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{{.Display}} AI Art — CuteDSL">
<meta name="twitter:description" content="{{.MetaDescription}}">
{{if .HeroImageURL}}<meta name="twitter:image" content="{{.HeroImageURL}}">{{end}}
<link rel="canonical" href="{{.CanonicalURL}}">
<link rel="icon" href="https://appstatic.app.nz/cutedsl/images/favicon.ico">
<script type="application/ld+json">{{.JSONLD}}</script>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;background:linear-gradient(135deg,#fef6fb 0%,#faf5ff 50%,#f0f9ff 100%);color:#1e293b;line-height:1.6;min-height:100vh}
a{color:inherit;text-decoration:none}
.nav{padding:1.25rem 2rem;display:flex;justify-content:space-between;align-items:center;max-width:90rem;margin:0 auto}
.nav-logo{font-size:1.5rem;font-weight:800;color:#db2777;display:flex;align-items:center;gap:.5rem}
.nav-links a{color:#475569;font-weight:600;margin-left:1.25rem;font-size:.9rem;transition:color .15s}
.nav-links a:hover{color:#db2777}
.breadcrumb{max-width:90rem;margin:0 auto;padding:.25rem 2rem 0;font-size:.8rem;color:#94a3b8;display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}
.breadcrumb a{color:#94a3b8;transition:color .15s}.breadcrumb a:hover{color:#db2777}
.breadcrumb span{color:#cbd5e1}
main{max-width:90rem;margin:0 auto;padding:1rem 1.25rem 5rem}
.hero{text-align:center;padding:2rem 0 2.5rem}
h1{font-size:2.5rem;font-weight:800;color:#0f172a;margin:0 0 .5rem;background:linear-gradient(135deg,#db2777,#a855f7,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
@media(min-width:700px){h1{font-size:3.5rem}}
.intro{color:#475569;font-size:1.05rem;max-width:44rem;margin:.25rem auto 1.25rem}
.count-pill{display:inline-block;font-size:.85rem;font-weight:700;padding:.35rem .9rem;border-radius:9999px;background:linear-gradient(135deg,#fce7f3,#faf5ff);color:#86198f;border:1px solid #f0abfc;margin-bottom:1rem}
.siblings{display:flex;flex-wrap:wrap;justify-content:center;gap:.4rem;margin:.5rem 0 0}
.sibling{font-size:.78rem;font-weight:600;padding:.28rem .75rem;border-radius:9999px;background:#fff;border:1px solid #fbcfe8;color:#475569;transition:all .15s}
.sibling:hover{background:linear-gradient(135deg,#f9a8d4,#d8b4fe);color:#fff;border-color:transparent}
.grid{columns:2;column-gap:.75rem}
@media(min-width:480px){.grid{columns:3}}
@media(min-width:700px){.grid{columns:4}}
@media(min-width:1000px){.grid{columns:5}}
@media(min-width:1280px){.grid{columns:6}}
@media(min-width:1600px){.grid{columns:7}}
.card{break-inside:avoid;margin-bottom:.75rem;background:#fff;border:1px solid #fce7f3;border-radius:.875rem;overflow:hidden;transition:transform .15s,box-shadow .15s,border-color .15s}
.card:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgba(219,39,119,.12);border-color:#f9a8d4}
.card a{display:block;color:inherit}
.card img{width:100%;display:block;background:#f1f5f9}
.card .cap{font-size:.72rem;color:#64748b;padding:.5rem .6rem .6rem;line-height:1.4;margin:0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.empty{text-align:center;padding:4rem 1rem;color:#94a3b8}
.about{max-width:48rem;margin:3rem auto 0;background:rgba(255,255,255,.7);backdrop-filter:blur(8px);border:1px solid #fce7f3;border-radius:1.25rem;padding:1.75rem}
.about h2{font-size:1.25rem;margin:0 0 .75rem;color:#0f172a}
.about p{color:#475569;font-size:.92rem;margin:0 0 .75rem}
.about a{color:#db2777;font-weight:600}
.about a:hover{text-decoration:underline}
footer{text-align:center;color:#94a3b8;font-size:.82rem;padding:2.5rem 1rem 3rem}
footer a{color:#db2777}
</style>
</head>
<body>
<nav class="nav">
  <a href="/" class="nav-logo">🦋 CuteDSL</a>
  <div class="nav-links">
    <a href="/gallery">Gallery</a>
    <a href="/search">Search</a>
    <a href="/tags">Tags</a>
    <a href="/docs">API Docs</a>
  </div>
</nav>

<nav class="breadcrumb" aria-label="Breadcrumb">
  <a href="/">Home</a>
  <span>›</span>
  <a href="/gallery">Gallery</a>
  <span>›</span>
  <a href="/tags">Tags</a>
  <span>›</span>
  <span style="color:#475569">{{.Display}}</span>
</nav>

<main>
  <header class="hero">
    <h1>{{.Display}} AI Art</h1>
    <p class="intro">{{.IntroText}}</p>
    <div class="count-pill">✨ {{.Count}} matching images</div>
    {{if .Siblings}}
    <div class="siblings" aria-label="Related tags">
      {{range .Siblings}}<a class="sibling" href="/tag/{{.Slug}}">{{.Display}}</a>{{end}}
    </div>
    {{end}}
  </header>

  {{if .Images}}
  <section class="grid" aria-label="{{.Display}} image results">
    {{range .Images}}
    <article class="card" itemscope itemtype="https://schema.org/ImageObject">
      <a href="/image/{{.Slug}}" itemprop="url" title="{{.Prompt}}">
        <img src="/images/{{if .ThumbPath}}{{.ThumbPath}}{{else}}{{.FilePath}}{{end}}"
             alt="{{.Prompt}}" loading="lazy" decoding="async"
             width="{{.Width}}" height="{{.Height}}"
             style="aspect-ratio:{{.Width}}/{{.Height}}"
             itemprop="thumbnailUrl">
        <p class="cap" itemprop="description">{{.Prompt}}</p>
      </a>
    </article>
    {{end}}
  </section>
  {{else}}
  <div class="empty">
    <p>No images matching <strong>{{.Display}}</strong> yet.</p>
    <p><a href="/gallery" style="color:#db2777;font-weight:600">← Back to gallery</a></p>
  </div>
  {{end}}

  <section class="about">
    <h2>About this tag</h2>
    <p>
      {{.Display}} images are generated by <strong>CuteDSL Z-Image Turbo</strong> — a fused-kernel
      diffusion transformer that runs 2× faster on RTX 5090. Every image has its own SEO-friendly
      detail page under <code>/image/…</code> with the full prompt, seed, model, and related art.
    </p>
    <p>
      Looking for something else? <a href="/search?q={{.Slug | urlquery}}">Search {{.Display}}</a> ·
      <a href="/tags">Browse all tags</a> · <a href="/gallery">Full gallery</a> ·
      <a href="/#api">Generate your own</a>.
    </p>
  </section>
</main>

<footer>
  <p>© {{.Year}} <a href="https://cutedsl.cc">CuteDSL</a> — AI art powered by Z-Image Turbo on Solana</p>
  <p style="margin-top:.4rem"><a href="/gallery">Gallery</a> · <a href="/search">Search</a> · <a href="/tags">Tags</a> · <a href="/sitemap.xml">Sitemap</a></p>
</footer>
</body>
</html>`))

// tagsIndexTemplate renders /tags — a single-page index of every curated category.
var tagsIndexTemplate = template.Must(template.New("tagsIdx").Parse(`<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>All AI Art Tags — Fairies, Fantasy, Anime &amp; More | CuteDSL</title>
<meta name="description" content="Browse every tag in the CuteDSL AI art gallery — fairies, dragons, anime, landscapes, cyberpunk, kawaii animals and more. {{.TotalTags}} curated tags across {{.TotalCats}} categories.">
<meta name="robots" content="index, follow">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="https://cutedsl.cc/tags">
<link rel="icon" href="https://appstatic.app.nz/cutedsl/images/favicon.ico">
<meta property="og:title" content="All AI Art Tags — CuteDSL">
<meta property="og:description" content="Browse every curated tag in the CuteDSL AI art gallery.">
<meta property="og:url" content="https://cutedsl.cc/tags">
<style>
body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;background:linear-gradient(135deg,#fef6fb 0%,#faf5ff 50%,#f0f9ff 100%);color:#1e293b;line-height:1.6}
a{color:inherit;text-decoration:none}
.nav{padding:1.25rem 2rem;display:flex;justify-content:space-between;align-items:center;max-width:80rem;margin:0 auto}
.nav-logo{font-size:1.5rem;font-weight:800;color:#db2777}
.nav-links a{color:#475569;font-weight:600;margin-left:1.25rem;font-size:.9rem}
.nav-links a:hover{color:#db2777}
main{max-width:80rem;margin:0 auto;padding:1rem 1.5rem 5rem}
h1{font-size:2.5rem;font-weight:800;margin:1.5rem 0 .25rem;background:linear-gradient(135deg,#db2777,#a855f7,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.sub{color:#475569;margin:0 0 2rem}
.cat{background:rgba(255,255,255,.7);backdrop-filter:blur(8px);border:1px solid #fce7f3;border-radius:1.25rem;padding:1.5rem;margin-bottom:1.25rem}
.cat h2{font-size:1.2rem;font-weight:800;color:#0f172a;margin:0 0 .75rem;display:flex;align-items:center;gap:.5rem}
.cat h2 a{color:#db2777}
.tags{display:flex;flex-wrap:wrap;gap:.4rem}
.tag{font-size:.82rem;font-weight:600;padding:.35rem .85rem;border-radius:9999px;background:linear-gradient(135deg,#fdf2f8,#faf5ff);border:1px solid #f0abfc;color:#86198f;transition:all .15s}
.tag:hover{background:linear-gradient(135deg,#f9a8d4,#d8b4fe);color:#fff;border-color:transparent;transform:translateY(-1px)}
footer{text-align:center;color:#94a3b8;font-size:.82rem;padding:1.5rem 1rem 3rem}
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
  </div>
</nav>

<main>
  <h1>All AI Art Tags</h1>
  <p class="sub">{{.TotalTags}} curated tags across {{.TotalCats}} categories. Click any tag for a Pinterest-style grid of matching images.</p>

  {{range .Categories}}
  <section class="cat" aria-labelledby="cat-{{.Slug}}">
    <h2 id="cat-{{.Slug}}">{{.Name}}</h2>
    <div class="tags">
      {{range .TagDisplays}}
      <a class="tag" href="/tag/{{.Slug}}">{{.Display}}</a>
      {{end}}
    </div>
  </section>
  {{end}}
</main>

<footer>
  <p>© {{.Year}} <a href="https://cutedsl.cc">CuteDSL</a> — <a href="/gallery">Gallery</a> · <a href="/search">Search</a> · <a href="/sitemap.xml">Sitemap</a></p>
</footer>
</body>
</html>`))

// handleTagPage renders /tag/<slug> with gobed-matched images.
func handleTagPage(ctx *fasthttp.RequestCtx, slug string) {
	slug = strings.TrimSpace(strings.ToLower(slug))
	if slug == "" || len(slug) > 80 {
		ctx.SetStatusCode(404)
		ctx.SetBodyString("tag not found")
		return
	}
	// Only allow safe slug chars; if a user typed "fairy magic", normalize.
	slug = slugify(slug)
	if slug == "" {
		ctx.SetStatusCode(404)
		return
	}

	display := tagDisplay(slug)
	query := tagQuery(slug)
	host := "https://cutedsl.cc"
	canonical := host + "/tag/" + slug

	// Gobed semantic search for matching images.
	var images []GeneratedImage
	if promptSearch != nil && promptSearch.IsReady() {
		sims, _ := promptSearch.Search(query, 60)
		if len(sims) > 0 {
			ids := make([]string, 0, len(sims))
			for _, r := range sims {
				ids = append(ids, r.ImageID)
			}
			images, _ = dbConn.GetImagesByIDs(ids, false)
		}
	}

	type entry struct {
		GeneratedImage
		Slug string
	}
	entries := make([]entry, len(images))
	for i, img := range images {
		entries[i] = entry{GeneratedImage: img, Slug: imageSlug(img.ID, img.Prompt)}
	}

	// Sibling tags — other members of the same curated category.
	type sibling struct{ Slug, Display string }
	var siblings []sibling
	if cat := categoryForTag(slug); cat != nil {
		for _, t := range cat.Tags {
			if t == slug {
				continue
			}
			siblings = append(siblings, sibling{Slug: t, Display: tagDisplay(t)})
			if len(siblings) >= 12 {
				break
			}
		}
	}

	// Hero image URL for OG cards.
	heroURL := ""
	if len(entries) > 0 {
		img := entries[0]
		path := img.MedPath
		if path == "" {
			path = img.FilePath
		}
		heroURL = host + "/images/" + path
	}

	metaDesc := fmt.Sprintf(
		"%d AI-generated %s images — browse, download, or generate your own with CuteDSL Z-Image Turbo. Pinterest-style grid, full prompts, related art.",
		len(entries), strings.ToLower(display),
	)
	intro := fmt.Sprintf(
		"Semantic-matched gallery for %s. Every image is generated with CuteDSL Z-Image Turbo — fused kernels, 2× faster on RTX 5090.",
		display,
	)
	keywords := strings.Join([]string{
		display, display + " AI art", display + " images",
		"AI generated " + strings.ToLower(display),
		"CuteDSL", "Z-Image Turbo", "Stable Diffusion", "AI art gallery",
	}, ", ")

	// JSON-LD: CollectionPage + BreadcrumbList + ItemList.
	itemList := make([]map[string]interface{}, 0, len(entries))
	for i, e := range entries {
		if i >= 20 {
			break
		}
		thumb := host + "/images/" + e.FilePath
		if e.ThumbPath != "" {
			thumb = host + "/images/" + e.ThumbPath
		}
		prompt := e.Prompt
		if len(prompt) > 140 {
			prompt = prompt[:137] + "..."
		}
		itemList = append(itemList, map[string]interface{}{
			"@type":    "ListItem",
			"position": i + 1,
			"item": map[string]interface{}{
				"@type":        "ImageObject",
				"contentUrl":   host + "/images/" + e.FilePath,
				"url":          host + "/image/" + e.Slug,
				"thumbnailUrl": thumb,
				"description":  prompt,
			},
		})
	}
	jsonLD := map[string]interface{}{
		"@context": "https://schema.org",
		"@graph": []interface{}{
			map[string]interface{}{
				"@type":       "CollectionPage",
				"@id":         canonical,
				"url":         canonical,
				"name":        display + " AI Art",
				"description": metaDesc,
				"inLanguage":  "en",
				"isPartOf":    map[string]interface{}{"@type": "WebSite", "name": "CuteDSL", "url": host},
			},
			map[string]interface{}{
				"@type": "BreadcrumbList",
				"itemListElement": []interface{}{
					map[string]interface{}{"@type": "ListItem", "position": 1, "name": "Home", "item": host},
					map[string]interface{}{"@type": "ListItem", "position": 2, "name": "Gallery", "item": host + "/gallery"},
					map[string]interface{}{"@type": "ListItem", "position": 3, "name": "Tags", "item": host + "/tags"},
					map[string]interface{}{"@type": "ListItem", "position": 4, "name": display, "item": canonical},
				},
			},
			map[string]interface{}{
				"@type":           "ItemList",
				"numberOfItems":   len(entries),
				"itemListElement": itemList,
			},
		},
	}
	jsonLDBytes, _ := json.Marshal(jsonLD)

	data := struct {
		Slug            string
		Display         string
		IntroText       string
		MetaDescription string
		Keywords        string
		CanonicalURL    string
		HeroImageURL    string
		Count           int
		Images          []entry
		Siblings        []sibling
		JSONLD          template.HTML
		Year            int
	}{
		Slug:            slug,
		Display:         display,
		IntroText:       intro,
		MetaDescription: metaDesc,
		Keywords:        keywords,
		CanonicalURL:    canonical,
		HeroImageURL:    heroURL,
		Count:           len(entries),
		Images:          entries,
		Siblings:        siblings,
		JSONLD:          template.HTML(jsonLDBytes),
		Year:            time.Now().Year(),
	}

	ctx.Response.Header.Set("Content-Type", "text/html; charset=utf-8")
	ctx.Response.Header.Set("Cache-Control", "public, max-age=600")
	if err := tagPageTemplate.Execute(ctx, data); err != nil {
		ctx.SetStatusCode(500)
		ctx.SetBodyString("template error")
	}
}

// handleTagsIndex renders /tags — one-page hub listing every curated tag.
func handleTagsIndex(ctx *fasthttp.RequestCtx) {
	type tagDisp struct{ Slug, Display string }
	type catDisp struct {
		Name        string
		Slug        string
		TagDisplays []tagDisp
	}
	cats := make([]catDisp, 0, len(curatedCategories))
	total := 0
	for _, c := range curatedCategories {
		td := make([]tagDisp, 0, len(c.Tags))
		for _, t := range c.Tags {
			td = append(td, tagDisp{Slug: t, Display: tagDisplay(t)})
		}
		cats = append(cats, catDisp{Name: c.Name, Slug: c.Slug, TagDisplays: td})
		total += len(c.Tags)
	}
	data := struct {
		Categories []catDisp
		TotalTags  int
		TotalCats  int
		Year       int
	}{cats, total, len(cats), time.Now().Year()}

	ctx.Response.Header.Set("Content-Type", "text/html; charset=utf-8")
	ctx.Response.Header.Set("Cache-Control", "public, max-age=3600")
	if err := tagsIndexTemplate.Execute(ctx, data); err != nil {
		ctx.SetStatusCode(500)
		ctx.SetBodyString("template error")
	}
}

// handleSitemapTags emits /sitemap-tags.xml with every curated /tag/<slug> URL
// plus the /tags hub.
func handleSitemapTags(ctx *fasthttp.RequestCtx) {
	host := "https://cutedsl.cc"
	var sb strings.Builder
	sb.WriteString(`<?xml version="1.0" encoding="UTF-8"?>` + "\n")
	sb.WriteString(`<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">` + "\n")
	fmt.Fprintf(&sb, "  <url><loc>%s/tags</loc><changefreq>weekly</changefreq><priority>0.7</priority></url>\n", host)
	for _, t := range allCuratedTags() {
		fmt.Fprintf(&sb,
			"  <url><loc>%s/tag/%s</loc><changefreq>weekly</changefreq><priority>0.6</priority></url>\n",
			host, t,
		)
	}
	sb.WriteString(`</urlset>` + "\n")
	writeSitemap(ctx, sb.String())
}
