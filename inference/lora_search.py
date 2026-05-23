"""LoRA search engine — sentence-transformer embedding search with keyword fallback.

Uses the same model as gobed (static-retrieval-mrl-en-v1) for compatibility.
Falls back to keyword search if the model can't be loaded.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from dataclasses import dataclass

import numpy as np

from lora_fixtures import LoRAMetadata, get_all_zimage_loras, get_lora_map

logger = logging.getLogger("cutedsl-inference")

_STOPWORDS = {"a", "an", "and", "the", "with", "for", "to", "of", "in", "on", "by", "at", "is"}
_ADULT_QUERY_TERMS = {
    "nsfw", "adult", "explicit", "porn", "hentai", "nude", "naked",
    "breast", "breasts", "ahegao", "erotic", "sensual", "xxx",
}


def _normalize_token(token: str) -> str:
    token = re.sub(r"^[^\w]+|[^\w]+$", "", token.lower())
    for suffix in ("istic", "ism", "ing", "ness", "tion", "es", "ed", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _query_terms(text: str) -> list[str]:
    terms = []
    for raw in re.split(r"[\s,;:/|()\[\]{}]+", text.lower()):
        term = _normalize_token(raw)
        if len(term) > 2 and term not in _STOPWORDS:
            terms.append(term)
    return terms


def _query_allows_adult(query: str) -> bool:
    terms = set(_query_terms(query))
    return any(term in terms for term in _ADULT_QUERY_TERMS)


def _normalized_phrase(text: str) -> str:
    return " ".join(_query_terms(text))


@dataclass
class LoRASearchResult:
    lora: LoRAMetadata
    score: float
    match_type: str


class LoRASearchEngine:
    def __init__(self):
        self._lora_embeddings: dict[str, list[np.ndarray]] = {}
        self._negative_embeddings: dict[str, list[np.ndarray]] = {}
        self._query_cache: dict[str, np.ndarray] = {}
        self._keyword_map: dict[str, list[str]] = {}
        self._model = None
        self._has_embeddings = False
        self._initialized = False
        self._lock = threading.Lock()

    def initialize(self):
        with self._lock:
            if self._initialized:
                return

            loras = get_lora_map()
            self._build_keyword_map(loras)
            self._initialized = True

        # Try loading sentence-transformers model in background
        threading.Thread(target=self._load_model_and_precompute, daemon=True).start()

    def _load_model_and_precompute(self):
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("sentence-transformers/static-retrieval-mrl-en-v1", device="cpu")
            with self._lock:
                self._model = model
            logger.info("loaded embedding model for LoRA search")
            self._precompute_embeddings()
        except Exception as e:
            logger.warning("embedding model load failed, using keyword search: %s", e)

    def _build_keyword_map(self, loras: dict[str, LoRAMetadata]):
        for lora_id, lora in loras.items():
            for keyword in lora.keywords:
                kw = keyword.lower()
                self._keyword_map.setdefault(kw, []).append(lora_id)
            if lora.trigger_word:
                tw = lora.trigger_word.lower()
                self._keyword_map.setdefault(tw, []).append(lora_id)
            self._keyword_map.setdefault(lora.name.lower(), []).append(lora_id)

    def _embed(self, text: str) -> np.ndarray | None:
        with self._lock:
            model = self._model
        if model is None:
            return None
        return model.encode(text, convert_to_numpy=True)

    def _precompute_embeddings(self):
        loras = get_lora_map()
        computed = 0

        for lora_id, lora in loras.items():
            embeddings = []

            if lora.trigger_word:
                emb = self._embed(lora.trigger_word)
                if emb is not None:
                    embeddings.append(emb)

            emb = self._embed(lora.name)
            if emb is not None:
                embeddings.append(emb)

            for keyword in lora.keywords:
                emb = self._embed(keyword)
                if emb is not None:
                    embeddings.append(emb)

            # Compute negative keyword embeddings separately
            neg_embeddings = []
            for neg_kw in lora.negative_keywords:
                emb = self._embed(neg_kw)
                if emb is not None:
                    neg_embeddings.append(emb)

            if embeddings:
                with self._lock:
                    self._lora_embeddings[lora_id] = embeddings
                    if neg_embeddings:
                        self._negative_embeddings[lora_id] = neg_embeddings
                computed += 1

        with self._lock:
            self._has_embeddings = True
        logger.info("pre-computed embeddings for %d/%d loras", computed, len(loras))

    def _get_query_embedding(self, query: str) -> np.ndarray | None:
        if query in self._query_cache:
            return self._query_cache[query]

        emb = self._embed(query)
        if emb is None:
            return None

        self._query_cache[query] = emb
        if len(self._query_cache) > 1000:
            keys = list(self._query_cache.keys())
            for k in keys[:500]:
                del self._query_cache[k]

        return emb

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a < 1e-8 or norm_b < 1e-8:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _compute_embedding_score(self, query_emb: np.ndarray, lora_id: str, lora: LoRAMetadata, query: str) -> float:
        with self._lock:
            embeddings = self._lora_embeddings.get(lora_id, [])
        if not embeddings:
            return 0.0

        max_positive_sim = 0.0
        for i, emb in enumerate(embeddings):
            sim = self._cosine_similarity(query_emb, emb)
            if i == 0 and lora.trigger_word:
                sim *= 1.5
            max_positive_sim = max(max_positive_sim, sim)

        # Compute max negative similarity from negative keyword embeddings
        max_negative_sim = 0.0
        with self._lock:
            neg_embeddings = self._negative_embeddings.get(lora_id, [])
        for neg_emb in neg_embeddings:
            sim = self._cosine_similarity(query_emb, neg_emb)
            max_negative_sim = max(max_negative_sim, sim)

        score = max(max_positive_sim - max_negative_sim, 0.0)
        query_norm = _normalized_phrase(query)
        if lora.trigger_word and _normalized_phrase(lora.trigger_word) in query_norm:
            score += 0.35
        if _normalized_phrase(lora.name) in query_norm:
            score += 0.25
        return score * 1.2

    def search(self, query: str, top_k: int = 5) -> list[LoRASearchResult]:
        with self._lock:
            has_emb = self._has_embeddings
        if has_emb:
            return self._search_embeddings(query, top_k)
        return self._search_keywords(query, top_k)

    def _search_embeddings(self, query: str, top_k: int) -> list[LoRASearchResult]:
        query_emb = self._get_query_embedding(query)
        if query_emb is None:
            return self._search_keywords(query, top_k)

        loras = get_lora_map()
        results = []
        allow_adult = _query_allows_adult(query)

        for lora_id, lora in loras.items():
            if lora.is_adult and not allow_adult:
                continue
            score = self._compute_embedding_score(query_emb, lora_id, lora, query)
            if score <= 0:
                continue

            match_type = "embedding"
            query_lower = query.lower()

            if lora.trigger_word and lora.trigger_word.lower() in query_lower:
                match_type = "trigger"
                score += 2.0
            elif lora.name.lower() in query_lower:
                match_type = "name"
                score += 1.0

            results.append(LoRASearchResult(lora=lora, score=score, match_type=match_type))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def _search_keywords(self, query: str, top_k: int) -> list[LoRASearchResult]:
        query_lower = query.lower()
        query_norm = _normalized_phrase(query)
        query_word_set = set(_query_terms(query))
        allow_adult = _query_allows_adult(query)

        loras = get_lora_map()
        scores: dict[str, float] = {}
        match_types: dict[str, str] = {}

        for lora_id, lora in loras.items():
            if lora.is_adult and not allow_adult:
                continue

            score = 0.0
            mt = "keyword"

            trigger_norm = _normalized_phrase(lora.trigger_word)
            name_norm = _normalized_phrase(lora.name)
            if trigger_norm and trigger_norm in query_norm:
                score += 3.0
                mt = "trigger"

            if name_norm and name_norm in query_norm:
                score += 2.0
                if mt == "keyword":
                    mt = "name"

            lora_id_norm = _normalize_token(lora_id.replace("_", " "))
            if lora_id_norm and lora_id_norm in query_norm:
                score += 2.0
                if mt == "keyword":
                    mt = "id"

            for name_word in set(_query_terms(lora.name)):
                if name_word in query_word_set:
                    score += 1.5
                    if mt == "keyword":
                        mt = "name"

            matched_words = set()
            for kw in lora.keywords:
                kw_terms = _query_terms(kw)
                kw_norm = " ".join(kw_terms)
                if kw_norm and kw_norm in query_norm:
                    score += 1.25
                for word in query_word_set:
                    if word in kw_terms:
                        if word not in matched_words:
                            score += 1.0
                            matched_words.add(word)

            for neg_kw in lora.negative_keywords:
                neg_norm = _normalized_phrase(neg_kw)
                if neg_norm and neg_norm in query_norm:
                    score -= 0.5
                elif any(word in query_word_set for word in _query_terms(neg_kw)):
                    score -= 0.25

            if score > 0:
                scores[lora_id] = score * 1.2
                match_types[lora_id] = mt

        sorted_ids = sorted(scores, key=scores.get, reverse=True)
        return [
            LoRASearchResult(lora=loras[lid], score=scores[lid], match_type=match_types[lid])
            for lid in sorted_ids[:top_k]
        ]

    def select_best(self, prompt: str, min_score: float = 0.45) -> LoRAMetadata | None:
        results = self.search(prompt, top_k=1)
        if results and results[0].score >= min_score:
            return results[0].lora
        return None


_engine: LoRASearchEngine | None = None


def get_lora_search_engine() -> LoRASearchEngine:
    global _engine
    if _engine is None:
        _engine = LoRASearchEngine()
        _engine.initialize()
    return _engine
