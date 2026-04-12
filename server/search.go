package main

import (
	"log"
	"runtime"
	"sync"
	"time"

	"github.com/lee101/gobed"
)

// PromptSearchEngine wraps gobed for semantic search over generated-image
// prompts. The gobed engine uses int IDs internally; we keep a parallel slice
// that maps gobed int ID → (image UUID, prompt text) so we can hydrate search
// results back into full GeneratedImage rows.
type PromptSearchEngine struct {
	engine    *gobed.SearchEngine
	model     *gobed.EmbeddingModel
	imageIDs  []string // gobed int ID → image UUID
	prompts   []string // gobed int ID → prompt text (for debug / suggestions)
	mu        sync.RWMutex
	ready     bool
	indexing  bool
	indexedAt time.Time
}

var promptSearch *PromptSearchEngine

func initPromptSearch() {
	promptSearch = &PromptSearchEngine{}
	go promptSearch.loadAndIndex()
}

// loadAndIndex streams every generated_images row into gobed at startup.
// Re-runs periodically to pick up newly inserted rows (cheap for DBs < 1M).
func (ps *PromptSearchEngine) loadAndIndex() {
	ps.mu.Lock()
	ps.indexing = true
	ps.mu.Unlock()

	defer func() {
		ps.mu.Lock()
		ps.indexing = false
		ps.mu.Unlock()
	}()

	t0 := time.Now()

	log.Println("[search] Loading gobed embedding model...")
	model, err := gobed.LoadModel()
	if err != nil {
		log.Printf("[search] Failed to load gobed model: %v", err)
		return
	}
	ps.model = model
	log.Printf("[search] Model loaded in %v", time.Since(t0))

	config := gobed.AsyncSearchConfig()
	config.MaxExactSearchSize = 500000
	config.AsyncWorkers = runtime.NumCPU() * 2
	config.AsyncQueueSize = 100000
	ps.engine = gobed.NewSearchEngineWithConfig(model, config)

	// Stream rows from the DB. Skip NSFW by default so the public index stays clean.
	var (
		imageIDs []string
		prompts  []string
	)
	err = dbConn.StreamAllImagePrompts(false, func(id, prompt string) error {
		imageIDs = append(imageIDs, id)
		prompts = append(prompts, prompt)
		return nil
	})
	if err != nil {
		log.Printf("[search] Failed to stream image prompts: %v", err)
		return
	}
	log.Printf("[search] Loaded %d image prompts from DB in %v", len(prompts), time.Since(t0))

	if len(prompts) == 0 {
		ps.mu.Lock()
		ps.ready = true
		ps.indexedAt = time.Now()
		ps.mu.Unlock()
		return
	}

	// Index in batches
	batchSize := 10000
	log.Printf("[search] Indexing %d prompts (batch_size=%d)...", len(prompts), batchSize)
	indexStart := time.Now()

	for i := 0; i < len(prompts); i += batchSize {
		end := i + batchSize
		if end > len(prompts) {
			end = len(prompts)
		}
		batch := prompts[i:end]
		ids := make([]int, len(batch))
		for j := range batch {
			ids[j] = i + j
		}
		ps.engine.IndexBatchWithIDs(ids, batch)

		if (i/batchSize)%10 == 0 {
			log.Printf("[search] Indexed %d/%d prompts (%.1f%%)",
				end, len(prompts), float64(end)/float64(len(prompts))*100)
		}
	}

	ps.mu.Lock()
	ps.prompts = prompts
	ps.imageIDs = imageIDs
	ps.ready = true
	ps.indexedAt = time.Now()
	ps.mu.Unlock()

	log.Printf("[search] Index built: %d prompts in %v (total %v)",
		len(prompts), time.Since(indexStart), time.Since(t0))
}

// IndexIncremental adds a single newly-generated image into the live index.
// Called from InsertGeneratedImage after a successful DB insert.
func (ps *PromptSearchEngine) IndexIncremental(imageID, prompt string) {
	if ps == nil || prompt == "" {
		return
	}
	ps.mu.Lock()
	defer ps.mu.Unlock()
	if ps.engine == nil || !ps.ready {
		return // still indexing the bulk load; this will be picked up on next full rebuild
	}
	intID := len(ps.prompts)
	if err := ps.engine.IndexWithID(intID, prompt); err != nil {
		log.Printf("[search] IndexIncremental failed: %v", err)
		return
	}
	ps.prompts = append(ps.prompts, prompt)
	ps.imageIDs = append(ps.imageIDs, imageID)
}

// SearchResult is a single semantic match with the mapped image UUID.
type SearchResult struct {
	ImageID    string  `json:"image_id"`
	Prompt     string  `json:"prompt"`
	Similarity float32 `json:"similarity"`
}

// Search returns topK semantic matches for query, as (imageID, prompt, sim).
func (ps *PromptSearchEngine) Search(query string, topK int) ([]SearchResult, error) {
	ps.mu.RLock()
	defer ps.mu.RUnlock()

	if !ps.ready || ps.engine == nil {
		return nil, nil
	}

	t0 := time.Now()
	results, err := ps.engine.Search(query, topK)
	if err != nil {
		return nil, err
	}

	out := make([]SearchResult, 0, len(results))
	for _, r := range results {
		if r.ID < 0 || r.ID >= len(ps.prompts) {
			continue
		}
		out = append(out, SearchResult{
			ImageID:    ps.imageIDs[r.ID],
			Prompt:     ps.prompts[r.ID],
			Similarity: r.Similarity,
		})
	}

	log.Printf("[search] query=%q top_k=%d results=%d time=%v", query, topK, len(out), time.Since(t0))
	return out, nil
}

// SearchRelated finds the topK most-similar image prompts to a given prompt,
// excluding the exact source image. Used by the /prompt/<id> page.
func (ps *PromptSearchEngine) SearchRelated(prompt, excludeImageID string, topK int) ([]SearchResult, error) {
	results, err := ps.Search(prompt, topK+1)
	if err != nil {
		return nil, err
	}
	out := make([]SearchResult, 0, len(results))
	for _, r := range results {
		if r.ImageID == excludeImageID {
			continue
		}
		out = append(out, r)
		if len(out) >= topK {
			break
		}
	}
	return out, nil
}

// IsReady returns whether the search engine is ready
func (ps *PromptSearchEngine) IsReady() bool {
	ps.mu.RLock()
	defer ps.mu.RUnlock()
	return ps.ready
}

// Stats returns search engine statistics
func (ps *PromptSearchEngine) Stats() map[string]interface{} {
	ps.mu.RLock()
	defer ps.mu.RUnlock()

	stats := map[string]interface{}{
		"ready":         ps.ready,
		"indexing":      ps.indexing,
		"total_prompts": len(ps.prompts),
	}
	if !ps.indexedAt.IsZero() {
		stats["indexed_at"] = ps.indexedAt.Format(time.RFC3339)
	}
	if ps.engine != nil {
		stats["engine_stats"] = ps.engine.Stats()
	}
	return stats
}
