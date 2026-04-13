'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { Search, ArrowLeft, X, Loader2, ImageIcon, Wand2, ChevronDown } from 'lucide-react';
import { useAutocomplete } from '@/hooks/use-autocomplete';

const API_BASE = '/api';
const IMG_BASE = '/images';
const LOGO_IMG = 'https://appstatic.app.nz/cutedsl/images/logo.webp';
const PER_PAGE = 48;

function slugify(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 72);
}

function imageSlug(id: string, prompt: string): string {
  const shortID = id.split('-')[0] ?? id.slice(0, 8);
  const slug = slugify(prompt);
  return slug ? `${slug}-${shortID}` : shortID;
}

interface GeneratedImage {
  id: string;
  prompt: string;
  width: number;
  height: number;
  file_path: string;
  thumb_path: string;
  med_path: string;
  file_size: number;
  model: string;
  seed: number;
  steps: number;
  created_at: string;
}

interface SearchResult {
  images: GeneratedImage[] | null;
  total: number;
  page: number;
  per_page: number;
  query: string;
}

export default function SearchPage() {
  const [query, setQuery] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [results, setResults] = useState<GeneratedImage[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);
  const [selectedImage, setSelectedImage] = useState<GeneratedImage | null>(null);
  const [imageCount, setImageCount] = useState(0);
  const [allowNSFW, setAllowNSFW] = useState(false);
  const [semanticSuggestions, setSemanticSuggestions] = useState<string[]>([]);
  const loaderRef = useRef<HTMLDivElement>(null);
  const autocomplete = useAutocomplete(searchInput);

  // Fetch total image count on mount
  useEffect(() => {
    fetch(`${API_BASE}/images/count`)
      .then(r => r.json())
      .then(data => setImageCount(data.count || 0))
      .catch(() => {});
  }, []);

  // Fetch images. Semantic (gobed) for queries, trigram browse for no-query.
  const fetchImages = useCallback(async (q: string, p: number, append: boolean = false) => {
    setLoading(true);
    try {
      let newImages: GeneratedImage[] = [];
      let newTotal = 0;

      if (q) {
        // Semantic: fetch a large top_k once — gobed returns ranked results,
        // pagination is handled client-side via slicing.
        const params = new URLSearchParams({ q, top_k: '240' });
        if (allowNSFW) params.set('allow_nsfw', 'true');
        const res = await fetch(`${API_BASE}/images/semantic?${params}`);
        const data = await res.json();
        const all: GeneratedImage[] = data.images || [];
        newTotal = all.length;
        newImages = all.slice((p - 1) * PER_PAGE, p * PER_PAGE);
      } else {
        // Browse (no query): paginated trigram / recent
        const params = new URLSearchParams({ page: String(p), per_page: String(PER_PAGE) });
        if (allowNSFW) params.set('allow_nsfw', 'true');
        const res = await fetch(`${API_BASE}/images?${params}`);
        const data: SearchResult = await res.json();
        newImages = data.images || [];
        newTotal = data.total;
      }

      setResults(prev => append ? [...prev, ...newImages] : newImages);
      setTotal(newTotal);
      setPage(p);
      setInitialLoad(false);
    } catch {
      setInitialLoad(false);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowNSFW]);

  // Initial load
  useEffect(() => {
    fetchImages('', 1);
  }, [fetchImages]);

  // Re-fetch when NSFW toggle changes
  useEffect(() => {
    if (!initialLoad) {
      setResults([]);
      setPage(1);
      fetchImages(query, 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowNSFW]);

  // Infinite scroll
  useEffect(() => {
    if (!loaderRef.current) return;
    const observer = new IntersectionObserver(
      entries => {
        if (entries[0].isIntersecting && !loading && results.length < total) {
          fetchImages(query, page + 1, true);
        }
      },
      { threshold: 0.1 }
    );
    observer.observe(loaderRef.current);
    return () => observer.disconnect();
  }, [loading, results.length, total, query, page, fetchImages]);

  // Fetch semantic suggestions as user types (shown below autocomplete)
  useEffect(() => {
    if (searchInput.length < 3) { setSemanticSuggestions([]); return; }
    const timer = setTimeout(() => {
      fetch(`${API_BASE}/search?q=${encodeURIComponent(searchInput)}&top_k=5`)
        .then(r => r.json())
        .then(data => {
          if (data.results) {
            setSemanticSuggestions(data.results.map((r: { prompt: string }) => r.prompt).slice(0, 5));
          }
        })
        .catch(() => {});
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setQuery(searchInput);
    setSemanticSuggestions([]);
    autocomplete.close();
    setResults([]);
    setPage(1);
    fetchImages(searchInput, 1);
  };

  const clearSearch = () => {
    setSearchInput('');
    setQuery('');
    setResults([]);
    setPage(1);
    fetchImages('', 1);
  };

  return (
    <div className="min-h-screen bg-pink-50">
      {/* Nav */}
      <nav className="w-full p-6 flex justify-between items-center max-w-7xl mx-auto">
        <Link href="/" className="flex items-center gap-2">
          <Image src={LOGO_IMG} alt="CuteDSL" width={40} height={40} className="rounded-lg" />
          <span className="font-fredoka text-3xl font-bold text-pink-600">CuteDSL</span>
        </Link>
        <div className="flex gap-6 font-bold text-slate-700">
          <Link href="/" className="hover:text-pink-500 transition-colors flex items-center gap-1"><ArrowLeft size={16} /> Home</Link>
          <Link href="/gallery" className="hover:text-pink-500 transition-colors">Gallery</Link>
          <Link href="/evals" className="hover:text-cyan-500 transition-colors">Evals</Link>
          <Link href="/blog" className="hover:text-purple-500 transition-colors">Blog</Link>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-6 pb-24">
        {/* Hero */}
        <div className="text-center py-12">
          <h1 className="font-fredoka text-5xl lg:text-7xl font-bold text-slate-800 mb-4">
            AI Art Gallery
          </h1>
          <p className="text-xl text-slate-600 max-w-2xl mx-auto font-medium mb-2">
            Browse {imageCount > 0 ? imageCount.toLocaleString() : '...'} AI-generated images. Search by prompt, explore styles, find inspiration.
          </p>
          <p className="text-sm text-slate-400">
            Generated with CuteDSL Z-Image Turbo
          </p>
        </div>

        {/* Search bar */}
        <form onSubmit={handleSearch} className="max-w-2xl mx-auto mb-12">
          <div className="relative">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={20} />
            <input
              type="text"
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              onKeyDown={e => {
                const result = autocomplete.handleKeyDown(e);
                if (result && result !== 'handled') {
                  setSearchInput(result);
                }
              }}
              onBlur={() => setTimeout(() => autocomplete.close(), 150)}
              placeholder="Search prompts... e.g. &quot;cyberpunk city&quot;, &quot;watercolor cat&quot;, &quot;fantasy landscape&quot;"
              className="w-full pl-12 pr-24 py-4 rounded-2xl border border-slate-200 bg-white shadow-sm text-lg focus:outline-none focus:ring-2 focus:ring-pink-300 focus:border-pink-300 transition-all"
            />
            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1">
              {searchInput && (
                <button type="button" onClick={clearSearch} className="p-2 text-slate-400 hover:text-slate-600">
                  <X size={18} />
                </button>
              )}
              <button type="submit" className="px-4 py-2 bg-pink-500 text-white rounded-xl font-bold hover:bg-pink-600 transition-colors">
                Search
              </button>
            </div>
            {/* Autocomplete word suggestions */}
            {(autocomplete.isOpen || semanticSuggestions.length > 0) && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white rounded-xl border border-slate-200 shadow-lg z-10 overflow-hidden">
                {autocomplete.isOpen && autocomplete.suggestions.map((s, i) => (
                  <button
                    key={`ac-${i}`}
                    type="button"
                    onMouseDown={e => e.preventDefault()}
                    onClick={() => {
                      const selected = autocomplete.selectSuggestion(i);
                      if (selected) setSearchInput(selected);
                    }}
                    className={`w-full text-left px-4 py-2.5 text-sm border-b border-slate-50 last:border-0 transition-colors ${
                      i === autocomplete.selectedIndex ? 'bg-pink-50 text-pink-700' : 'text-slate-600 hover:bg-pink-50'
                    }`}
                  >
                    <span className="text-slate-400">{s.typed}</span>
                    <span className="font-semibold text-slate-700">{s.completion}</span>
                  </button>
                ))}
                {/* Semantic suggestions below autocomplete */}
                {semanticSuggestions.length > 0 && (
                  <>
                    {autocomplete.isOpen && <div className="border-t border-slate-200 px-4 py-1.5 text-xs text-slate-400 bg-slate-50">Prompts</div>}
                    {semanticSuggestions.map((s, i) => (
                      <button
                        key={`sem-${i}`}
                        type="button"
                        onClick={() => { setSearchInput(s); setSemanticSuggestions([]); autocomplete.close(); setQuery(s); setResults([]); setPage(1); fetchImages(s, 1); }}
                        className="w-full text-left px-4 py-2.5 text-sm text-slate-600 hover:bg-pink-50 border-b border-slate-50 last:border-0 line-clamp-1"
                      >
                        {s}
                      </button>
                    ))}
                  </>
                )}
              </div>
            )}
          </div>
        </form>

        {/* Results info + NSFW toggle */}
        {!initialLoad && (
          <div className="flex justify-between items-center mb-6">
            <p className="text-slate-500 text-sm">
              {query ? (
                <>Showing {results.length} of {total.toLocaleString()} results for <strong className="text-slate-700">&quot;{query}&quot;</strong></>
              ) : (
                <>{total.toLocaleString()} images</>
              )}
            </p>
            <label className="flex items-center gap-2 text-sm text-slate-500 cursor-pointer select-none">
              <span>NSFW</span>
              <button
                onClick={() => setAllowNSFW(!allowNSFW)}
                className={`relative w-10 h-5 rounded-full transition-colors ${allowNSFW ? 'bg-pink-500' : 'bg-slate-300'}`}
              >
                <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${allowNSFW ? 'translate-x-5' : ''}`} />
              </button>
            </label>
          </div>
        )}

        {/* Image grid */}
        {initialLoad ? (
          <div className="flex items-center justify-center py-32">
            <Loader2 className="animate-spin text-pink-400" size={48} />
          </div>
        ) : results.length === 0 ? (
          <div className="text-center py-32">
            <ImageIcon className="mx-auto mb-4 text-slate-300" size={64} />
            <p className="text-xl text-slate-500 font-medium">
              {query ? `No images found for "${query}"` : 'No images yet. Run the generator to populate the gallery!'}
            </p>
            <p className="text-sm text-slate-400 mt-2">
              Try a different search term or browse all images
            </p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
              {results.map(img => (
                <button
                  key={img.id}
                  onClick={() => setSelectedImage(img)}
                  className="group relative aspect-square rounded-xl overflow-hidden bg-slate-100 border border-slate-200 hover:border-pink-300 hover:shadow-lg transition-all"
                >
                  <img
                    src={`${IMG_BASE}/${img.thumb_path || img.file_path}`}
                    alt={img.prompt}
                    loading="lazy"
                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                  />
                  <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <p className="text-white text-xs line-clamp-2 leading-tight">{img.prompt}</p>
                  </div>
                </button>
              ))}
            </div>

            {/* Infinite scroll trigger */}
            {results.length < total && (
              <div ref={loaderRef} className="flex justify-center py-12">
                {loading ? (
                  <Loader2 className="animate-spin text-pink-400" size={32} />
                ) : (
                  <button
                    onClick={() => fetchImages(query, page + 1, true)}
                    className="flex items-center gap-2 px-6 py-3 bg-white border border-slate-200 rounded-xl text-slate-600 font-bold hover:bg-pink-50 hover:border-pink-300 transition-all"
                  >
                    <ChevronDown size={18} />
                    Load more
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </main>

      {/* Lightbox modal */}
      {selectedImage && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
          onClick={() => setSelectedImage(null)}
        >
          <div
            className="bg-white rounded-2xl max-w-4xl w-full max-h-[90vh] overflow-y-auto shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <div className="relative">
              <img
                src={`${IMG_BASE}/${selectedImage.med_path || selectedImage.file_path}`}
                alt={selectedImage.prompt}
                className="w-full rounded-t-2xl"
              />
              <button
                onClick={() => setSelectedImage(null)}
                className="absolute top-4 right-4 p-2 bg-black/50 rounded-full text-white hover:bg-black/70 transition-colors"
              >
                <X size={20} />
              </button>
            </div>
            <div className="p-6">
              <p className="text-slate-700 text-lg leading-relaxed mb-4">{selectedImage.prompt}</p>
              <div className="flex flex-wrap gap-3 text-sm text-slate-400">
                <span className="bg-slate-50 border border-slate-200 px-3 py-1 rounded-lg">{selectedImage.width}x{selectedImage.height}</span>
                <span className="bg-slate-50 border border-slate-200 px-3 py-1 rounded-lg">{selectedImage.model}</span>
                <span className="bg-slate-50 border border-slate-200 px-3 py-1 rounded-lg">{selectedImage.steps} steps</span>
                {selectedImage.seed > 0 && (
                  <span className="bg-slate-50 border border-slate-200 px-3 py-1 rounded-lg">seed {selectedImage.seed}</span>
                )}
                <span className="bg-slate-50 border border-slate-200 px-3 py-1 rounded-lg">
                  {(selectedImage.file_size / 1024).toFixed(0)} KB
                </span>
              </div>
              <div className="mt-4 flex flex-wrap gap-3">
                <a
                  href={`/image/${imageSlug(selectedImage.id, selectedImage.prompt)}`}
                  className="px-4 py-2 bg-gradient-to-r from-pink-400 to-purple-400 text-white rounded-xl font-bold hover:shadow-lg hover:shadow-pink-300/50 transition-all text-sm"
                >
                  View page &amp; related →
                </a>
                <a
                  href={`${IMG_BASE}/${selectedImage.file_path}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-4 py-2 bg-pink-500 text-white rounded-xl font-bold hover:bg-pink-600 transition-colors text-sm"
                >
                  Full Resolution
                </a>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(selectedImage.prompt);
                  }}
                  className="px-4 py-2 bg-slate-100 text-slate-700 rounded-xl font-bold hover:bg-slate-200 transition-colors text-sm"
                >
                  Copy Prompt
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="bg-white/90 border-t border-pink-200 py-8">
        <div className="max-w-7xl mx-auto px-6 flex justify-between items-center">
          <p className="text-slate-400 text-sm">&copy; 2026 <a href="https://app.nz" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500">Applied Science Company</a></p>
          <div className="flex gap-4 text-sm font-bold">
            <Link href="/" className="text-slate-500 hover:text-pink-500">Home</Link>
            <Link href="/evals" className="text-slate-500 hover:text-cyan-500">Evals</Link>
            <Link href="/blog" className="text-slate-500 hover:text-purple-500">Blog</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
