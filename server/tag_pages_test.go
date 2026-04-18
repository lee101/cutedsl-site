package main

import (
	"strings"
	"testing"
)

func TestLinkifyPrompt(t *testing.T) {
	got := string(linkifyPrompt("A cute fairy in an enchanted forest, digital art"))
	// Stopwords / tiny words stay as plain text.
	if strings.Contains(got, `href="/tag/a"`) {
		t.Errorf("stopword 'a' should not be linkified: %s", got)
	}
	if strings.Contains(got, `href="/tag/in"`) {
		t.Errorf("stopword 'in' should not be linkified: %s", got)
	}
	// Significant words become /tag/<slug> links.
	wantTags := []string{"cute", "fairy", "enchanted", "forest", "digital"}
	for _, w := range wantTags {
		if !strings.Contains(got, `href="/tag/`+w+`"`) {
			t.Errorf("expected /tag/%s link, got: %s", w, got)
		}
	}
	// 'art' is a stopword per our list — ensure it stays plain.
	if strings.Contains(got, `href="/tag/art"`) {
		t.Errorf("'art' is a stopword but got linked: %s", got)
	}
	// Punctuation preserved.
	if !strings.Contains(got, ",") {
		t.Errorf("punctuation missing from output: %s", got)
	}
}

func TestLinkifyPromptEscapesHTML(t *testing.T) {
	got := string(linkifyPrompt("scary <script>alert(1)</script> witch"))
	// Raw angle brackets must never round-trip as tag open/close.
	if strings.Contains(got, "<script>") || strings.Contains(got, "</script>") {
		t.Errorf("raw script tag should be escaped: %s", got)
	}
	// Escaped entities must appear for both brackets.
	if !strings.Contains(got, "&lt;") || !strings.Contains(got, "&gt;") {
		t.Errorf("expected escaped < and >: %s", got)
	}
	if !strings.Contains(got, `href="/tag/witch"`) {
		t.Errorf("expected witch to still linkify: %s", got)
	}
}

func TestCuratedTagsNonEmpty(t *testing.T) {
	all := allCuratedTags()
	if len(all) < 50 {
		t.Errorf("expected >= 50 curated tags, got %d", len(all))
	}
	if !isCuratedTag("fairy") {
		t.Errorf("'fairy' should be a curated tag")
	}
	if isCuratedTag("totallyfakemadeupword-xyz") {
		t.Errorf("unknown slug should not be curated")
	}
}

func TestTagDisplay(t *testing.T) {
	cases := map[string]string{
		"fairy":             "Fairy",
		"enchanted-forest":  "Enchanted Forest",
		"studio-ghibli":     "Studio Ghibli",
	}
	for in, want := range cases {
		if got := tagDisplay(in); got != want {
			t.Errorf("tagDisplay(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestTagQuery(t *testing.T) {
	if got := tagQuery("enchanted-forest"); got != "enchanted forest" {
		t.Errorf("tagQuery did not un-hyphenate: %q", got)
	}
}

// Templates are already wrapped in template.Must at package init, so importing
// this test package will panic if they fail to parse. A trivial exec ensures
// the template executes without dot-reference errors on the expected shape.
func TestTagsIndexTemplateExecutes(t *testing.T) {
	type tagDisp struct{ Slug, Display string }
	type catDisp struct {
		Name        string
		Slug        string
		TagDisplays []tagDisp
	}
	data := struct {
		Categories []catDisp
		TotalTags  int
		TotalCats  int
		Year       int
	}{
		Categories: []catDisp{
			{Name: "Fantasy", Slug: "fantasy", TagDisplays: []tagDisp{{Slug: "fairy", Display: "Fairy"}}},
		},
		TotalTags: 1, TotalCats: 1, Year: 2026,
	}
	var sb strings.Builder
	if err := tagsIndexTemplate.Execute(&sb, data); err != nil {
		t.Fatalf("tagsIndexTemplate execute failed: %v", err)
	}
	if !strings.Contains(sb.String(), `href="/tag/fairy"`) {
		t.Errorf("expected tag link in rendered HTML")
	}
}
