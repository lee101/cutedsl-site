package main

import (
	"bufio"
	"encoding/json"
	"log"
	"os"
	"runtime"
	"sync"
	"time"

	"github.com/lee101/gobed"
)

// PromptSearchEngine wraps gobed for semantic search over image prompts
type PromptSearchEngine struct {
	engine   *gobed.SearchEngine
	model    *gobed.EmbeddingModel
	prompts  []string // indexed prompts for ID → prompt lookup
	mu       sync.RWMutex
	ready    bool
	indexing bool
}

var promptSearch *PromptSearchEngine

func initPromptSearch() {
	promptSearch = &PromptSearchEngine{}
	go promptSearch.loadAndIndex()
}

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

	// Load gobed model
	log.Println("[search] Loading gobed embedding model...")
	model, err := gobed.LoadModel()
	if err != nil {
		log.Printf("[search] Failed to load gobed model: %v", err)
		return
	}
	ps.model = model
	log.Printf("[search] Model loaded in %v", time.Since(t0))

	// Configure search engine for large dataset
	config := gobed.AsyncSearchConfig()
	config.MaxExactSearchSize = 500000
	config.AsyncWorkers = runtime.NumCPU() * 2
	config.AsyncQueueSize = 100000

	ps.engine = gobed.NewSearchEngineWithConfig(model, config)

	// Load prompts from JSONL
	promptsFile := getEnv("PROMPTS_FILE", "/sdb-disk/cutedsl-images/prompts.jsonl")
	log.Printf("[search] Loading prompts from %s...", promptsFile)

	f, err := os.Open(promptsFile)
	if err != nil {
		log.Printf("[search] Failed to open prompts file: %v", err)
		return
	}
	defer f.Close()

	var prompts []string
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 1024*1024), 1024*1024)

	for scanner.Scan() {
		var row struct {
			Prompt string `json:"prompt"`
		}
		if err := json.Unmarshal(scanner.Bytes(), &row); err == nil && row.Prompt != "" {
			prompts = append(prompts, row.Prompt)
		}
	}
	log.Printf("[search] Loaded %d prompts in %v", len(prompts), time.Since(t0))

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
	ps.ready = true
	ps.mu.Unlock()

	log.Printf("[search] Index built: %d prompts in %v (total %v)",
		len(prompts), time.Since(indexStart), time.Since(t0))
}

// Search performs semantic search over prompts
func (ps *PromptSearchEngine) Search(query string, topK int) ([]PromptSearchResult, error) {
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

	elapsed := time.Since(t0)

	var out []PromptSearchResult
	for _, r := range results {
		prompt := ""
		if r.ID >= 0 && r.ID < len(ps.prompts) {
			prompt = ps.prompts[r.ID]
		}
		out = append(out, PromptSearchResult{
			ID:         r.ID,
			Prompt:     prompt,
			Similarity: r.Similarity,
		})
	}

	log.Printf("[search] query=%q top_k=%d results=%d time=%v", query, topK, len(out), elapsed)
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
		"ready":        ps.ready,
		"indexing":     ps.indexing,
		"total_prompts": len(ps.prompts),
	}

	if ps.engine != nil {
		s := ps.engine.Stats()
		stats["engine_stats"] = s
	}

	return stats
}

// PromptSearchResult is a single search result
type PromptSearchResult struct {
	ID         int     `json:"id"`
	Prompt     string  `json:"prompt"`
	Similarity float32 `json:"similarity"`
}
