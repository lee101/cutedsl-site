package main

import (
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func newTestEngine(fn func(string, int) ([]SearchResult, error)) *PromptSearchEngine {
	return &PromptSearchEngine{ready: true, searchFn: fn}
}

func TestSearchCacheHit(t *testing.T) {
	var calls int32
	ps := newTestEngine(func(q string, k int) ([]SearchResult, error) {
		atomic.AddInt32(&calls, 1)
		return []SearchResult{{ImageID: "img1", Prompt: q, Similarity: 0.9}}, nil
	})

	r1, err := ps.Search("cute fairy", 10)
	if err != nil || len(r1) != 1 {
		t.Fatalf("first search: %v %v", r1, err)
	}
	r2, err := ps.Search("cute fairy", 10)
	if err != nil || len(r2) != 1 || r2[0].ImageID != "img1" {
		t.Fatalf("second search: %v %v", r2, err)
	}
	if got := atomic.LoadInt32(&calls); got != 1 {
		t.Fatalf("expected 1 underlying call, got %d", got)
	}

	if _, err := ps.Search("cute fairy", 20); err != nil {
		t.Fatal(err)
	}
	if got := atomic.LoadInt32(&calls); got != 2 {
		t.Fatalf("different topK should miss cache, calls=%d", got)
	}
}

func TestSearchNotReadyNotCached(t *testing.T) {
	var calls int32
	ps := newTestEngine(func(q string, k int) ([]SearchResult, error) {
		atomic.AddInt32(&calls, 1)
		return nil, nil
	})
	ps.ready = false

	r, err := ps.Search("q", 5)
	if r != nil || err != nil {
		t.Fatalf("expected nil,nil when not ready: %v %v", r, err)
	}
	if atomic.LoadInt32(&calls) != 0 {
		t.Fatal("searchFn should not run when not ready")
	}
	if ps.getCache().len() != 0 {
		t.Fatal("nothing should be cached when not ready")
	}
}

func TestSearchSingleflight(t *testing.T) {
	var calls int32
	release := make(chan struct{})
	ps := newTestEngine(func(q string, k int) ([]SearchResult, error) {
		atomic.AddInt32(&calls, 1)
		<-release
		return []SearchResult{{ImageID: "img1", Prompt: q}}, nil
	})

	const n = 16
	var wg sync.WaitGroup
	results := make([][]SearchResult, n)
	errs := make([]error, n)
	started := make(chan struct{}, n)
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			started <- struct{}{}
			results[i], errs[i] = ps.Search("same query", 10)
		}(i)
	}
	for i := 0; i < n; i++ {
		<-started
	}
	close(release)
	wg.Wait()

	for i := 0; i < n; i++ {
		if errs[i] != nil || len(results[i]) != 1 || results[i][0].ImageID != "img1" {
			t.Fatalf("goroutine %d: %v %v", i, results[i], errs[i])
		}
	}
	if got := atomic.LoadInt32(&calls); got != 1 {
		t.Fatalf("expected 1 underlying call for %d concurrent queries, got %d", n, got)
	}
}

func TestSearchCacheFlushOnReindex(t *testing.T) {
	var calls int32
	ps := newTestEngine(func(q string, k int) ([]SearchResult, error) {
		atomic.AddInt32(&calls, 1)
		return []SearchResult{{ImageID: fmt.Sprintf("img%d", atomic.LoadInt32(&calls))}}, nil
	})

	if _, err := ps.Search("q", 5); err != nil {
		t.Fatal(err)
	}
	ps.getCache().flush()
	r, err := ps.Search("q", 5)
	if err != nil {
		t.Fatal(err)
	}
	if atomic.LoadInt32(&calls) != 2 {
		t.Fatalf("flush should force recompute, calls=%d", calls)
	}
	if r[0].ImageID != "img2" {
		t.Fatalf("expected fresh result after flush, got %v", r)
	}
}

func TestSearchCacheCapEviction(t *testing.T) {
	c := newSearchCache()
	for i := 0; i < searchCacheMax+50; i++ {
		c.set(fmt.Sprintf("k%d", i), nil)
	}
	if n := c.len(); n > searchCacheMax {
		t.Fatalf("cache exceeded cap: %d > %d", n, searchCacheMax)
	}
}

func TestSearchCacheKeyLongQuery(t *testing.T) {
	long1 := strings.Repeat("a", 500) + "x"
	long2 := strings.Repeat("a", 500) + "y"
	k1 := searchCacheKey(long1, 10)
	k2 := searchCacheKey(long2, 10)
	if k1 == k2 {
		t.Fatal("distinct long queries must hash to distinct keys")
	}
	if k1 != searchCacheKey(long1, 10) {
		t.Fatal("key must be deterministic")
	}
	if len(k1) > 64 {
		t.Fatalf("long query key not hashed: %q", k1)
	}
	if searchCacheKey("short", 10) != "10:short" {
		t.Fatal("short key format changed")
	}
}

func TestSearchByPageCachesPerPage(t *testing.T) {
	var calls int32
	ps := newTestEngine(func(q string, k int) ([]SearchResult, error) {
		atomic.AddInt32(&calls, 1)
		return []SearchResult{{ImageID: "src", Prompt: q}, {ImageID: "a", Prompt: q}, {ImageID: "b", Prompt: q}}, nil
	})
	for i := 0; i < 3; i++ {
		r, err := ps.SearchRelated("fairy", "src", 2)
		if err != nil || len(r) != 2 || r[0].ImageID != "a" || r[0].Prompt != "" {
			t.Fatalf("related: %+v %v", r, err)
		}
	}
	if atomic.LoadInt32(&calls) != 1 {
		t.Fatalf("expected 1 call, got %d", calls)
	}
	ps.SearchRelated("fairy", "other", 2)
	if atomic.LoadInt32(&calls) != 2 {
		t.Fatalf("distinct page should miss, calls=%d", calls)
	}
	if ps.getCache().len() != 0 {
		t.Fatal("page searches must not fill the query cache")
	}
}

func TestLRUCacheEvictsOldest(t *testing.T) {
	c := newLRUCache(2, time.Hour)
	c.set("a", nil)
	c.set("b", nil)
	c.get("a")
	c.set("c", nil)
	if _, ok := c.get("b"); ok {
		t.Fatal("b should be evicted")
	}
	if _, ok := c.get("a"); !ok {
		t.Fatal("a should survive")
	}
	if c.len() != 2 {
		t.Fatalf("len=%d", c.len())
	}
	e := newLRUCache(2, -time.Second)
	e.set("x", nil)
	if _, ok := e.get("x"); ok {
		t.Fatal("expired entry returned")
	}
}
