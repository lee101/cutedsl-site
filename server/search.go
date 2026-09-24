package main

import (
	"container/list"
	"hash/fnv"
	"log"
	"runtime"
	"strconv"
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
	cacheOnce sync.Once
	cache     *searchCache
	searchFn  func(query string, topK int) ([]SearchResult, error) // test hook
	relOnce   sync.Once
	rel       *lruCache
}

const (
	searchCacheTTL = 6 * time.Hour
	searchCacheMax = 20000
)

type searchCacheEntry struct {
	results []SearchResult
	expires time.Time
}

type searchFlight struct {
	done    chan struct{}
	results []SearchResult
	err     error
}

// searchCache is a TTL result cache with a soft entry cap and singleflight
// dedup for concurrent identical queries.
type searchCache struct {
	mu      sync.Mutex
	entries map[string]*searchCacheEntry
	flight  map[string]*searchFlight
}

func newSearchCache() *searchCache {
	return &searchCache{
		entries: make(map[string]*searchCacheEntry),
		flight:  make(map[string]*searchFlight),
	}
}

func searchCacheKey(query string, topK int) string {
	if len(query) > 128 {
		h := fnv.New64a()
		h.Write([]byte(query))
		return strconv.Itoa(topK) + ":h:" + strconv.FormatUint(h.Sum64(), 16)
	}
	return strconv.Itoa(topK) + ":" + query
}

func (c *searchCache) get(key string) ([]SearchResult, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.entries[key]
	if !ok {
		return nil, false
	}
	if time.Now().After(e.expires) {
		delete(c.entries, key)
		return nil, false
	}
	return e.results, true
}

func (c *searchCache) set(key string, results []SearchResult) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.entries) >= searchCacheMax {
		now := time.Now()
		for k, e := range c.entries {
			if now.After(e.expires) {
				delete(c.entries, k)
			}
		}
		for k := range c.entries {
			if len(c.entries) < searchCacheMax {
				break
			}
			delete(c.entries, k)
		}
	}
	c.entries[key] = &searchCacheEntry{results: results, expires: time.Now().Add(searchCacheTTL)}
}

func (c *searchCache) flush() {
	c.mu.Lock()
	c.entries = make(map[string]*searchCacheEntry)
	c.mu.Unlock()
}

func (c *searchCache) len() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return len(c.entries)
}

// Long-lived per-page cache for related/tag results. Crawlers hit each
// /image/ and /tag/ page roughly once per day with a unique prompt, so the
// query-keyed cache above almost never hits; keying by page lets each page's
// ANN search run at most once per relatedCacheTTL. Only image IDs and
// similarities are kept, and the cache survives index rebuilds because image
// IDs are stable.
const (
	relatedCacheTTL = 36 * time.Hour
	relatedCacheMax = 100000
)

type lruEntry struct {
	key     string
	results []SearchResult
	expires time.Time
}

type lruCache struct {
	mu    sync.Mutex
	max   int
	ttl   time.Duration
	ll    *list.List
	items map[string]*list.Element
}

func newLRUCache(max int, ttl time.Duration) *lruCache {
	return &lruCache{max: max, ttl: ttl, ll: list.New(), items: make(map[string]*list.Element)}
}

func (c *lruCache) get(key string) ([]SearchResult, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	el, ok := c.items[key]
	if !ok {
		return nil, false
	}
	e := el.Value.(*lruEntry)
	if time.Now().After(e.expires) {
		c.ll.Remove(el)
		delete(c.items, key)
		return nil, false
	}
	c.ll.MoveToFront(el)
	return e.results, true
}

func (c *lruCache) set(key string, results []SearchResult) {
	c.mu.Lock()
	defer c.mu.Unlock()
	exp := time.Now().Add(c.ttl)
	if el, ok := c.items[key]; ok {
		e := el.Value.(*lruEntry)
		e.results, e.expires = results, exp
		c.ll.MoveToFront(el)
		return
	}
	c.items[key] = c.ll.PushFront(&lruEntry{key: key, results: results, expires: exp})
	for c.ll.Len() > c.max {
		el := c.ll.Back()
		c.ll.Remove(el)
		delete(c.items, el.Value.(*lruEntry).key)
	}
}

func (c *lruCache) len() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.ll.Len()
}

func (ps *PromptSearchEngine) getRelCache() *lruCache {
	ps.relOnce.Do(func() { ps.rel = newLRUCache(relatedCacheMax, relatedCacheTTL) })
	return ps.rel
}

// SearchByPage runs query once per pageKey per relatedCacheTTL, bypassing the
// short-lived query cache so unique prompts do not evict popular searches.
func (ps *PromptSearchEngine) SearchByPage(pageKey, query string, topK int) ([]SearchResult, error) {
	if !ps.IsReady() {
		return nil, nil
	}
	cache := ps.getRelCache()
	key := strconv.Itoa(topK) + ":" + pageKey
	if r, ok := cache.get(key); ok {
		return r, nil
	}
	t0 := time.Now()
	results, err := ps.searchFunc()(query, topK)
	if err != nil {
		return nil, err
	}
	slim := make([]SearchResult, len(results))
	for i, r := range results {
		slim[i] = SearchResult{ImageID: r.ImageID, Similarity: r.Similarity}
	}
	if ps.IsReady() {
		cache.set(key, slim)
	}
	log.Printf("[search] page=%q top_k=%d results=%d time=%v cache_hit=false", pageKey, topK, len(slim), time.Since(t0))
	return slim, nil
}

func (ps *PromptSearchEngine) getCache() *searchCache {
	ps.cacheOnce.Do(func() { ps.cache = newSearchCache() })
	return ps.cache
}

var promptSearch *PromptSearchEngine

func newPromptSearchIndex(model *gobed.EmbeddingModel) *gobed.SearchEngine {
	if gobed.IsCUDAAvailable() {
		return gobed.NewAutoSearchEngine(model)
	}
	// gobed's automatic CAGRA preset selects 1,024 IVF centroids even in a
	// CPU-only build. Its k-means++ initializer is quadratic in the number of
	// centroids and left the production index unavailable for tens of minutes.
	// A compact CPU IVF keeps both startup training and per-query candidate
	// counts bounded for the current ~814k-document catalog.
	return gobed.NewSearchEngineWithConfig(model, gobed.SearchConfig{
		AutoMode:           false,
		MaxExactSearchSize: 1500,
		NumClusters:        64,
		SearchClusters:     2,
		UseCompression:     false,
		UseGraphRouting:    false,
		CandidatesToRerank: 256,
		MaxConcurrency:     runtime.NumCPU(),
	})
}

func initPromptSearch() {
	promptSearch = &PromptSearchEngine{}
	go promptSearch.loadAndIndex()
}

// loadAndIndex streams every generated_images row into gobed at startup.
// Re-run on demand to reconcile prompts skipped by best-effort live indexing.
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
	log.Printf("[search] Model loaded in %v", time.Since(t0))

	// Auto-select the fastest backend for the available hardware: GPU CAGRA +
	// int8 when CUDA is present (build with the `gpu` tag), otherwise an
	// optimized CPU ANN (IVF-HNSW-PQ) index. This replaces the old config that
	// forced MaxExactSearchSize=500000 — i.e. a brute-force exact scan over every
	// vector on every query, which does not scale past a few thousand prompts.
	if gobed.IsCUDAAvailable() {
		log.Printf("[search] CUDA available — using GPU-accelerated search index")
	} else {
		log.Printf("[search] No CUDA — using optimized CPU ANN search index")
	}
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
		ps.model = model
		ps.engine = newPromptSearchIndex(model)
		ps.prompts = nil
		ps.imageIDs = nil
		ps.ready = true
		ps.indexedAt = time.Now()
		ps.mu.Unlock()
		ps.getCache().flush()
		return
	}

	// The first IndexBatchWithIDs call determines whether gobed constructs a flat
	// or trained IVF index. Pass the full catalog on that first call: seeding it
	// with a 10k chunk makes the GPU auto-config choose a flat index, which cannot
	// grow past its 100k threshold. The implementation parallelizes embeddings
	// internally and trains on at most 100k vectors.
	log.Printf("[search] Indexing %d prompts as one catalog-sized build...", len(prompts))
	indexStart := time.Now()
	engine := newPromptSearchIndex(model)
	ids := make([]int, len(prompts))
	for i := range ids {
		ids[i] = i
	}
	if err := engine.IndexBatchWithIDs(ids, prompts); err != nil {
		_ = engine.Close()
		log.Printf("[search] Failed to build complete %d-prompt index: %v", len(prompts), err)
		return
	}

	ps.mu.Lock()
	oldEngine := ps.engine
	ps.model = model
	ps.engine = engine
	ps.prompts = prompts
	ps.imageIDs = imageIDs
	ps.ready = true
	ps.indexedAt = time.Now()
	ps.mu.Unlock()
	if oldEngine != nil {
		_ = oldEngine.Close()
	}
	ps.getCache().flush()

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

// TryIndexIncremental updates the live index only when doing so cannot queue
// behind active searches. The database remains the source of truth, and the
// next startup/admin rebuild reconciles any prompt skipped under load.
func (ps *PromptSearchEngine) TryIndexIncremental(imageID, prompt string) bool {
	if ps == nil || prompt == "" || !ps.mu.TryLock() {
		return false
	}
	defer ps.mu.Unlock()
	if ps.engine == nil || !ps.ready {
		return false
	}
	intID := len(ps.prompts)
	if err := ps.engine.IndexWithID(intID, prompt); err != nil {
		log.Printf("[search] TryIndexIncremental failed: %v", err)
		return false
	}
	ps.prompts = append(ps.prompts, prompt)
	ps.imageIDs = append(ps.imageIDs, imageID)
	return true
}

// SearchResult is a single semantic match with the mapped image UUID.
type SearchResult struct {
	ImageID    string  `json:"image_id"`
	Prompt     string  `json:"prompt"`
	Similarity float32 `json:"similarity"`
}

// Search returns topK semantic matches for query, as (imageID, prompt, sim).
// Results are cached for searchCacheTTL and concurrent identical queries are
// deduped so only one embedding forward runs per unique (query, topK).
func (ps *PromptSearchEngine) Search(query string, topK int) ([]SearchResult, error) {
	if !ps.IsReady() {
		return nil, nil
	}

	key := searchCacheKey(query, topK)
	cache := ps.getCache()
	t0 := time.Now()

	if results, ok := cache.get(key); ok {
		log.Printf("[search] query=%q top_k=%d results=%d time=%v cache_hit=true", query, topK, len(results), time.Since(t0))
		return results, nil
	}

	cache.mu.Lock()
	if f, ok := cache.flight[key]; ok {
		cache.mu.Unlock()
		<-f.done
		if f.err != nil {
			return nil, f.err
		}
		log.Printf("[search] query=%q top_k=%d results=%d time=%v cache_hit=true", query, topK, len(f.results), time.Since(t0))
		return f.results, nil
	}
	f := &searchFlight{done: make(chan struct{})}
	cache.flight[key] = f
	cache.mu.Unlock()

	results, err := ps.searchFunc()(query, topK)

	cache.mu.Lock()
	f.results, f.err = results, err
	delete(cache.flight, key)
	cache.mu.Unlock()
	close(f.done)

	if err != nil {
		return nil, err
	}
	if ps.IsReady() {
		cache.set(key, results)
	}
	log.Printf("[search] query=%q top_k=%d results=%d time=%v cache_hit=false", query, topK, len(results), time.Since(t0))
	return results, nil
}

func (ps *PromptSearchEngine) searchFunc() func(string, int) ([]SearchResult, error) {
	if ps.searchFn != nil {
		return ps.searchFn
	}
	return ps.doSearch
}

func (ps *PromptSearchEngine) doSearch(query string, topK int) ([]SearchResult, error) {
	ps.mu.RLock()
	defer ps.mu.RUnlock()

	if !ps.ready || ps.engine == nil {
		return nil, nil
	}

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
	return out, nil
}

// SearchRelated finds the topK most-similar image prompts to a given prompt,
// excluding the exact source image. Used by the /prompt/<id> page. Results are
// cached per source image (see SearchByPage) and carry no Prompt text.
func (ps *PromptSearchEngine) SearchRelated(prompt, excludeImageID string, topK int) ([]SearchResult, error) {
	results, err := ps.SearchByPage("img:"+excludeImageID, prompt, topK+1)
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
