package main

import (
	"log"
	"sort"
	"strings"
	"sync"

	"github.com/lee101/gobed"
)

type LoRASearchResult struct {
	LoRA      *LoRAMetadata `json:"lora"`
	Score     float32       `json:"score"`
	MatchType string        `json:"match_type"`
}

type LoRASearchEngine struct {
	mu sync.RWMutex

	model *gobed.EmbeddingModel

	loras      map[string]*LoRAMetadata
	loraEmbeds map[string][][]float32
	negEmbeds  map[string][][]float32
	queryCache map[string][]float32

	initialized bool
}

var (
	loraSearch     *LoRASearchEngine
	loraSearchOnce sync.Once
)

func GetLoRASearchEngine() *LoRASearchEngine {
	loraSearchOnce.Do(func() {
		loraSearch = &LoRASearchEngine{
			loras:      make(map[string]*LoRAMetadata),
			loraEmbeds: make(map[string][][]float32),
			negEmbeds:  make(map[string][][]float32),
			queryCache: make(map[string][]float32),
		}
	})
	return loraSearch
}

func (e *LoRASearchEngine) Initialize() error {
	e.mu.Lock()
	defer e.mu.Unlock()

	if e.initialized {
		return nil
	}

	log.Println("[lora] Loading gobed model...")
	model, err := gobed.LoadModel()
	if err != nil {
		return err
	}
	e.model = model

	allLoRAs := GetAllZImageLoRAs()
	for _, lora := range allLoRAs {
		e.loras[lora.ID] = lora
	}
	log.Printf("[lora] Loaded %d Z-Image LoRAs", len(e.loras))

	go e.precomputeEmbeddings()

	e.initialized = true
	return nil
}

func (e *LoRASearchEngine) precomputeEmbeddings() {
	e.mu.Lock()
	defer e.mu.Unlock()

	log.Println("[lora] Pre-computing LoRA embeddings...")

	for loraID, lora := range e.loras {
		var positives [][]float32

		if lora.TriggerWord != "" {
			if embed, err := e.model.Encode(lora.TriggerWord); err == nil {
				positives = append(positives, embed)
			}
		}

		if embed, err := e.model.Encode(lora.Name); err == nil {
			positives = append(positives, embed)
		}

		for _, kw := range lora.Keywords {
			if embed, err := e.model.Encode(kw); err == nil {
				positives = append(positives, embed)
			}
		}

		e.loraEmbeds[loraID] = positives

		var negatives [][]float32
		for _, nkw := range lora.NegativeKeywords {
			if embed, err := e.model.Encode(nkw); err == nil {
				negatives = append(negatives, embed)
			}
		}
		e.negEmbeds[loraID] = negatives
	}

	log.Printf("[lora] Pre-computed embeddings for %d LoRAs", len(e.loraEmbeds))
}

func (e *LoRASearchEngine) SearchLoRAs(query string, topK int) []*LoRASearchResult {
	e.mu.RLock()
	defer e.mu.RUnlock()

	if !e.initialized || e.model == nil {
		return nil
	}

	queryEmbed, err := e.getQueryEmbedding(query)
	if err != nil {
		log.Printf("[lora] Failed to embed query '%s': %v", query, err)
		return nil
	}

	type scored struct {
		id        string
		score     float32
		matchType string
	}

	var results []scored

	for loraID, lora := range e.loras {
		positiveScore := e.maxSimilarity(queryEmbed, e.loraEmbeds[loraID], lora.TriggerWord != "")
		negativeScore := e.maxSimilarity(queryEmbed, e.negEmbeds[loraID], false)

		score := positiveScore - negativeScore

		if score <= 0 {
			continue
		}

		matchType := "embedding"
		queryLower := strings.ToLower(query)
		if lora.TriggerWord != "" && strings.Contains(queryLower, strings.ToLower(lora.TriggerWord)) {
			matchType = "trigger"
			score += 2.0
		} else if strings.Contains(queryLower, strings.ToLower(lora.Name)) {
			matchType = "name"
			score += 1.0
		}

		score *= 1.2

		results = append(results, scored{id: loraID, score: score, matchType: matchType})
	}

	sort.Slice(results, func(i, j int) bool {
		return results[i].score > results[j].score
	})

	out := make([]*LoRASearchResult, 0, topK)
	for i := 0; i < len(results) && i < topK; i++ {
		out = append(out, &LoRASearchResult{
			LoRA:      e.loras[results[i].id],
			Score:     results[i].score,
			MatchType: results[i].matchType,
		})
	}

	return out
}

func (e *LoRASearchEngine) maxSimilarity(queryEmbed []float32, embeddings [][]float32, boostFirst bool) float32 {
	if len(embeddings) == 0 {
		return 0
	}

	var maxSim float32
	for i, embed := range embeddings {
		sim := gobed.CosineSimilarity(queryEmbed, embed)
		if i == 0 && boostFirst {
			sim *= 1.5
		}
		if sim > maxSim {
			maxSim = sim
		}
	}
	return maxSim
}

func (e *LoRASearchEngine) SelectBest(prompt string) *LoRAMetadata {
	results := e.SearchLoRAs(prompt, 1)
	if len(results) == 0 {
		return nil
	}
	return results[0].LoRA
}

func ApplyLoRATemplate(lora *LoRAMetadata, prompt string) string {
	if lora == nil || lora.Template == "" {
		return prompt
	}
	return strings.Replace(lora.Template, "{prompt}", prompt, 1)
}

func (e *LoRASearchEngine) getQueryEmbedding(query string) ([]float32, error) {
	if cached, ok := e.queryCache[query]; ok {
		return cached, nil
	}

	embed, err := e.model.Encode(query)
	if err != nil {
		return nil, err
	}

	e.queryCache[query] = embed

	if len(e.queryCache) > 1000 {
		for k := range e.queryCache {
			delete(e.queryCache, k)
			if len(e.queryCache) <= 500 {
				break
			}
		}
	}

	return embed, nil
}
