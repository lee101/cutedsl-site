package main

import "strings"

// Curated tag taxonomy — grouped so /tag landing pages get themed siblings,
// and so /sitemap-tags.xml surfaces every tag to crawlers.
// Keep tag strings short, lowercase, and search-friendly.

type TagCategory struct {
	Name string   // Display name — "Fantasy & Magic"
	Slug string   // URL slug of the category — "fantasy"
	Tags []string // Member tag slugs (lowercase, hyphen-separated)
}

var curatedCategories = []TagCategory{
	{
		Name: "Fantasy & Magic",
		Slug: "fantasy",
		Tags: []string{
			"fairy", "elf", "dragon", "unicorn", "witch", "wizard", "mermaid",
			"angel", "demon", "goddess", "griffin", "phoenix", "pegasus",
			"enchanted-forest", "magical", "spell", "potion", "crystal",
		},
	},
	{
		Name: "Anime & Kawaii",
		Slug: "anime",
		Tags: []string{
			"anime", "manga", "kawaii", "chibi", "waifu", "studio-ghibli",
			"magical-girl", "school-uniform", "pastel", "cute", "moe",
		},
	},
	{
		Name: "Cute Animals",
		Slug: "animals",
		Tags: []string{
			"cat", "kitten", "dog", "puppy", "bunny", "fox", "panda",
			"hamster", "hedgehog", "owl", "deer", "wolf", "tiger",
		},
	},
	{
		Name: "Landscapes & Nature",
		Slug: "landscapes",
		Tags: []string{
			"landscape", "mountain", "forest", "sunset", "sunrise", "beach",
			"waterfall", "meadow", "autumn", "winter", "cherry-blossom",
			"aurora", "starry-sky", "galaxy", "nebula",
		},
	},
	{
		Name: "Sci-Fi & Cyberpunk",
		Slug: "scifi",
		Tags: []string{
			"cyberpunk", "robot", "mecha", "spaceship", "astronaut", "neon",
			"futuristic", "dystopian", "synthwave", "space", "android",
		},
	},
	{
		Name: "Characters & Portraits",
		Slug: "characters",
		Tags: []string{
			"portrait", "warrior", "knight", "samurai", "ninja", "pirate",
			"princess", "queen", "king", "goth", "cowboy", "steampunk",
		},
	},
	{
		Name: "Art Styles",
		Slug: "styles",
		Tags: []string{
			"watercolor", "oil-painting", "digital-art", "concept-art",
			"pixel-art", "vaporwave", "art-nouveau", "baroque", "impressionist",
			"cel-shaded", "3d-render", "line-art",
		},
	},
	{
		Name: "Mood & Aesthetic",
		Slug: "aesthetic",
		Tags: []string{
			"dreamy", "whimsical", "ethereal", "cozy", "gothic", "noir",
			"minimalist", "surreal", "psychedelic", "fairycore", "cottagecore",
		},
	},
	{
		Name: "Food & Drink",
		Slug: "food",
		Tags: []string{
			"food", "dessert", "cake", "ice-cream", "coffee", "tea",
			"sushi", "ramen", "macaron", "bakery",
		},
	},
	{
		Name: "Architecture",
		Slug: "architecture",
		Tags: []string{
			"castle", "cathedral", "temple", "palace", "ruins", "lighthouse",
			"bridge", "pagoda", "cabin", "village", "cityscape",
		},
	},
}

// tagQuery expands a tag slug into a free-text query for gobed.
// e.g. "enchanted-forest" -> "enchanted forest", "studio-ghibli" -> "studio ghibli".
// Most tags are single words so the transform is cheap.
func tagQuery(slug string) string {
	return strings.ReplaceAll(slug, "-", " ")
}

// tagDisplay returns the title-cased display form of a tag slug.
// "enchanted-forest" -> "Enchanted Forest".
func tagDisplay(slug string) string {
	parts := strings.Split(slug, "-")
	for i, p := range parts {
		if len(p) == 0 {
			continue
		}
		parts[i] = strings.ToUpper(p[:1]) + p[1:]
	}
	return strings.Join(parts, " ")
}

// allCuratedTags returns every tag slug across all categories (deduped).
func allCuratedTags() []string {
	seen := map[string]bool{}
	var out []string
	for _, cat := range curatedCategories {
		for _, t := range cat.Tags {
			if seen[t] {
				continue
			}
			seen[t] = true
			out = append(out, t)
		}
	}
	return out
}

// categoryForTag returns the first curated category that contains the tag
// (for sibling-tag suggestions). Returns nil if the tag is not curated.
func categoryForTag(slug string) *TagCategory {
	for i := range curatedCategories {
		for _, t := range curatedCategories[i].Tags {
			if t == slug {
				return &curatedCategories[i]
			}
		}
	}
	return nil
}

// isCuratedTag reports whether a slug is in the curated taxonomy.
// Curated tags get richer tag pages (intro copy, sibling pills); any other
// slug still renders via gobed search, just without the curated trimmings.
func isCuratedTag(slug string) bool {
	return categoryForTag(slug) != nil
}
