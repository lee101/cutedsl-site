'use client';

import { useState, useEffect, useRef, useCallback } from 'react';

interface WordFrequencies {
  [word: string]: number;
}

interface AutocompleteSuggestion {
  /** The full text that would replace the input */
  value: string;
  /** The portion the user already typed */
  typed: string;
  /** The suggested completion suffix */
  completion: string;
  /** Word frequency score */
  frequency: number;
}

let cachedFrequencies: WordFrequencies | null = null;
let cachedSorted: string[] | null = null;
let loadingPromise: Promise<void> | null = null;

async function loadFrequencies(): Promise<void> {
  if (cachedFrequencies) return;
  if (loadingPromise) return loadingPromise;

  loadingPromise = fetch('/word_frequencies.json')
    .then(r => r.json())
    .then((data: WordFrequencies) => {
      cachedFrequencies = data;
      // Pre-sort by frequency descending
      cachedSorted = Object.keys(data).sort((a, b) => data[b] - data[a]);
    })
    .catch(() => {
      cachedFrequencies = {};
      cachedSorted = [];
    });

  return loadingPromise;
}

function getSuggestions(query: string, maxResults = 8): AutocompleteSuggestion[] {
  if (!cachedFrequencies || !cachedSorted || !query) return [];

  const words = query.split(' ');
  const lastWord = (words[words.length - 1] || '').toLowerCase();
  if (lastWord.length < 1) return [];

  const usedWords = new Set(words.map(w => w.toLowerCase()));
  const results: AutocompleteSuggestion[] = [];

  for (let i = 0; i < cachedSorted.length && results.length < maxResults * 2; i++) {
    const word = cachedSorted[i];
    if (!word || word.length > 30) continue;
    if (usedWords.has(word.toLowerCase())) continue;

    const wordLower = word.toLowerCase();
    if (wordLower.startsWith(lastWord) && word.length > lastWord.length) {
      const completion = word.substring(lastWord.length);
      const prefix = words.slice(0, -1).join(' ');
      const value = prefix ? `${prefix} ${word}` : word;

      results.push({
        value,
        typed: query,
        completion,
        frequency: cachedFrequencies[word] || 0,
      });
    }
  }

  // Already sorted by frequency since cachedSorted is pre-sorted
  return results.slice(0, maxResults);
}

export function useAutocomplete(input: string) {
  const [suggestions, setSuggestions] = useState<AutocompleteSuggestion[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [isOpen, setIsOpen] = useState(false);
  const loadedRef = useRef(false);

  // Load word frequencies on first use
  useEffect(() => {
    if (!loadedRef.current) {
      loadedRef.current = true;
      loadFrequencies();
    }
  }, []);

  // Update suggestions when input changes
  useEffect(() => {
    if (!input || input.length < 1) {
      setSuggestions([]);
      setIsOpen(false);
      return;
    }

    // Small debounce for typing performance
    const timer = setTimeout(() => {
      const results = getSuggestions(input);
      setSuggestions(results);
      setIsOpen(results.length > 0);
      setSelectedIndex(-1);
    }, 50);

    return () => clearTimeout(timer);
  }, [input]);

  const selectSuggestion = useCallback((index: number) => {
    if (index >= 0 && index < suggestions.length) {
      const selected = suggestions[index].value;
      setSuggestions([]);
      setIsOpen(false);
      setSelectedIndex(-1);
      return selected;
    }
    return null;
  }, [suggestions]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!isOpen || suggestions.length === 0) return null;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev => Math.min(prev + 1, suggestions.length - 1));
      return 'handled';
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev => Math.max(prev - 1, -1));
      return 'handled';
    }
    if (e.key === 'Tab' || (e.key === 'Enter' && selectedIndex >= 0)) {
      e.preventDefault();
      return selectSuggestion(selectedIndex >= 0 ? selectedIndex : 0);
    }
    if (e.key === 'Escape') {
      setIsOpen(false);
      setSelectedIndex(-1);
      return 'handled';
    }

    return null;
  }, [isOpen, suggestions, selectedIndex, selectSuggestion]);

  const close = useCallback(() => {
    setIsOpen(false);
    setSelectedIndex(-1);
  }, []);

  return {
    suggestions,
    selectedIndex,
    isOpen,
    selectSuggestion,
    handleKeyDown,
    close,
  };
}

export type { AutocompleteSuggestion };
