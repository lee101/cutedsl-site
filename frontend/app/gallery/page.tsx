'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import {
  ArrowLeft, Loader2, ImageIcon, X, ExternalLink, Copy, Check,
  Sparkles, Star, Heart, Search as SearchIcon, Wand2, Film, SlidersHorizontal,
  Wallet, Coins, RefreshCw, ArrowRight,
} from 'lucide-react';
import { useAutocomplete } from '@/hooks/use-autocomplete';
import { ShareButton } from '@/lib/share-button';
import { MediaGradeEditor } from '@/lib/media-grade-editor';

const API_BASE = '/api';
const IMG_BASE = '/images';
const LOGO_IMG = 'https://appstatic.app.nz/cutedsl/images/logo.webp';
const PER_PAGE = 60;

type ImageService = 'ra2' | 'zimage';

// ra2 art generator is the default image model; Z-Image Turbo stays selectable.
const IMAGE_SERVICES: { slug: ImageService; label: string; hint: string }[] = [
  { slug: 'ra2', label: 'ra2 art generator', hint: 'higher quality, ~2x slower' },
  { slug: 'zimage', label: 'Z-Image Turbo', hint: 'fastest' },
];

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

// Curated themes — link to /tag/<slug> SSR landing pages for SEO.
// Keep slugs aligned with server/curated_tags.go so pills route to rich pages.
const THEMES: { label: string; slug: string; emoji: string; color: string }[] = [
  { label: 'Fairies',      slug: 'fairy',      emoji: '🧚',   color: 'from-pink-300 to-purple-300' },
  { label: 'Dragons',      slug: 'dragon',     emoji: '🐉',   color: 'from-red-300 to-orange-300' },
  { label: 'Anime',        slug: 'anime',      emoji: '🎀',   color: 'from-pink-300 to-rose-300' },
  { label: 'Unicorns',     slug: 'unicorn',    emoji: '🦄',   color: 'from-fuchsia-300 to-pink-300' },
  { label: 'Landscapes',   slug: 'landscape',  emoji: '🌄',   color: 'from-cyan-300 to-blue-300' },
  { label: 'Galaxy',       slug: 'galaxy',     emoji: '🌌',   color: 'from-indigo-400 to-purple-500' },
  { label: 'Cyberpunk',    slug: 'cyberpunk',  emoji: '🌃',   color: 'from-fuchsia-400 to-cyan-400' },
  { label: 'Mermaids',     slug: 'mermaid',    emoji: '🧜‍♀️',  color: 'from-teal-300 to-cyan-400' },
  { label: 'Castles',      slug: 'castle',     emoji: '🏰',   color: 'from-stone-300 to-amber-300' },
  { label: 'Cherry Blossom', slug: 'cherry-blossom', emoji: '🌸', color: 'from-pink-200 to-rose-300' },
  { label: 'Witches',      slug: 'witch',      emoji: '🧙‍♀️',  color: 'from-purple-500 to-indigo-500' },
  { label: 'Robots',       slug: 'robot',      emoji: '🤖',   color: 'from-slate-300 to-cyan-300' },
];

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 72);
}

function imageSlug(id: string, prompt: string): string {
  const shortID = id.split('-')[0] ?? id.slice(0, 8);
  const slug = slugify(prompt);
  return slug ? `${slug}-${shortID}` : shortID;
}

const TAG_STOPWORDS = new Set([
  'the', 'and', 'with', 'from', 'that', 'this', 'into', 'over', 'under',
  'image', 'photo', 'art', 'style', 'very', 'highly', 'detailed',
]);

function promptTags(prompt: string): string[] {
  const seen = new Set<string>();
  return (prompt.toLowerCase().match(/[a-z0-9]+/g) || [])
    .filter(word => word.length >= 3 && !TAG_STOPWORDS.has(word))
    .filter(word => {
      if (seen.has(word)) return false;
      seen.add(word);
      return true;
    })
    .slice(0, 10);
}

export default function GalleryPage() {
  const [images, setImages] = useState<GeneratedImage[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);
  const [imageCount, setImageCount] = useState(0);
  const [selectedImage, setSelectedImage] = useState<GeneratedImage | null>(null);
  const [editingImage, setEditingImage] = useState(false);
  const [copied, setCopied] = useState(false);
  const [editablePrompt, setEditablePrompt] = useState('');
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [credits, setCredits] = useState<number | null>(null);
  const [service, setService] = useState<ImageService>('ra2');
  const [servicePricesUSD, setServicePricesUSD] = useState<Record<ImageService, number>>({ ra2: 1, zimage: 1 });
  const generationPriceUSD = servicePricesUSD[service];
  const [connectingWallet, setConnectingWallet] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generatedImage, setGeneratedImage] = useState<string | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [needsPayment, setNeedsPayment] = useState(false);
  const [paymentAmount, setPaymentAmount] = useState('1');
  const [paymentLoading, setPaymentLoading] = useState(false);
  const [paymentResult, setPaymentResult] = useState<{
    intent_id: string;
    amount_ui: string;
    deposit_address: string;
    solana_pay_url?: string;
    status: 'pending' | 'paid';
  } | null>(null);
  const [paymentError, setPaymentError] = useState<string | null>(null);
  const paymentEventsRef = useRef<EventSource | null>(null);
  const [searchInput, setSearchInput] = useState('');
  const [searchFocused, setSearchFocused] = useState(false);
  const [semanticSuggestions, setSemanticSuggestions] = useState<string[]>([]);
  const loaderRef = useRef<HTMLDivElement>(null);
  const autocomplete = useAutocomplete(searchInput, searchFocused);

  useEffect(() => {
    const savedWallet = localStorage.getItem('cutedsl_wallet');
    const savedApiKey = localStorage.getItem('cutedsl_api_key');
    setWalletAddress(savedWallet);
    setApiKey(savedApiKey);

    fetch(`${API_BASE}/pricing`)
      .then(res => res.json())
      .then(data => {
        const list: { service: string; price_usd: number }[] = data.pricing || [];
        const priceFor = (slug: ImageService, fallback: number) => {
          const usd = Number(list.find(item => item.service === slug)?.price_usd);
          return Number.isFinite(usd) && usd > 0 ? usd : fallback;
        };
        setServicePricesUSD(prev => ({ ra2: priceFor('ra2', prev.ra2), zimage: priceFor('zimage', prev.zimage) }));
      })
      .catch(() => {});
  }, []);

  // Keep the top-up amount in step with the selected service price.
  useEffect(() => {
    setPaymentAmount(String(Math.max(1, Math.ceil(generationPriceUSD * 100) / 100)));
  }, [generationPriceUSD]);

  useEffect(() => {
    if (!walletAddress) {
      setCredits(null);
      return;
    }
    fetch(`${API_BASE}/balance?wallet=${encodeURIComponent(walletAddress)}`)
      .then(res => res.json())
      .then(data => {
        setCredits(Number(data.credits) || 0);
      })
      .catch(() => {});
  }, [walletAddress]);

  useEffect(() => {
    paymentEventsRef.current?.close();
    paymentEventsRef.current = null;
    if (selectedImage) {
      setEditablePrompt(selectedImage.prompt);
      setGeneratedImage(null);
      setGenerationError(null);
      setNeedsPayment(false);
      setPaymentError(null);
      setPaymentResult(null);
    }
  }, [selectedImage]);

  useEffect(() => {
    return () => paymentEventsRef.current?.close();
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/images/count`)
      .then(r => r.json())
      .then(data => setImageCount(data.count || 0))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (searchInput.trim().length < 3) {
      setSemanticSuggestions([]);
      return;
    }
    const timer = setTimeout(() => {
      fetch(`${API_BASE}/search?q=${encodeURIComponent(searchInput.trim())}&top_k=5`)
        .then(r => r.json())
        .then(data => setSemanticSuggestions(
          (data.results || []).map((result: { prompt: string }) => result.prompt).slice(0, 5)
        ))
        .catch(() => setSemanticSuggestions([]));
    }, 250);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const fetchImages = useCallback(async (p: number, append = false) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(p), per_page: String(PER_PAGE) });
      const res = await fetch(`${API_BASE}/images?${params}`);
      const data = await res.json();
      const imgs: GeneratedImage[] = data.images || [];
      setImages(prev => append ? [...prev, ...imgs] : imgs);
      setTotal(data.total || 0);
      setPage(p);
      setInitialLoad(false);
    } catch {
      setInitialLoad(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchImages(1);
  }, [fetchImages]);

  // Close lightbox with Escape
  useEffect(() => {
    if (!selectedImage || editingImage) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedImage(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [editingImage, selectedImage]);

  // Infinite scroll
  useEffect(() => {
    if (!loaderRef.current) return;
    const observer = new IntersectionObserver(
      entries => {
        if (entries[0].isIntersecting && !loading && images.length < total) {
          fetchImages(page + 1, true);
        }
      },
      { threshold: 0.1, rootMargin: '400px' }
    );
    observer.observe(loaderRef.current);
    return () => observer.disconnect();
  }, [loading, images.length, total, page, fetchImages]);

  const copyPrompt = async (prompt: string) => {
    await navigator.clipboard.writeText(prompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const connectWallet = async () => {
    setConnectingWallet(true);
    setGenerationError(null);
    try {
      const solana = (window as any).solana;
      let address = '';
      if (solana?.isPhantom) {
        const response = await solana.connect();
        address = response.publicKey.toString();
      } else {
        address = window.prompt('Enter your Solana wallet address:')?.trim() || '';
      }

      if (address.length < 30) {
        setGenerationError('A Solana wallet is required to continue.');
        return;
      }

      const res = await fetch(`${API_BASE}/auth/wallet`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wallet_address: address }),
      });
      const data = await res.json();
      if (!res.ok || !data.api_key) throw new Error(data.error || 'Wallet login failed');

      setWalletAddress(address);
      setApiKey(data.api_key);
      setCredits(Number(data.user?.credits) || 0);
      localStorage.setItem('cutedsl_wallet', address);
      localStorage.setItem('cutedsl_api_key', data.api_key);
    } catch (error) {
      setGenerationError(error instanceof Error ? error.message : 'Wallet login failed.');
    } finally {
      setConnectingWallet(false);
    }
  };

  const generateImage = async () => {
    const prompt = editablePrompt.trim();
    if (!prompt) {
      setGenerationError('Add a prompt before generating.');
      return;
    }
    if (!walletAddress || !apiKey) {
      setGenerationError('Log in with your Solana wallet to generate this image.');
      return;
    }

    setGenerating(true);
    setGeneratedImage(null);
    setGenerationError(null);
    setNeedsPayment(false);
    try {
      const res = await fetch(`${API_BASE}/service`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          service,
          prompt,
          width: 512,
          height: 512,
          num_steps: service === 'ra2' ? 20 : 4,
        }),
      });
      const data = await res.json();
      if (res.status === 402) {
        setNeedsPayment(true);
        setGenerationError('Add credits to generate this image.');
        return;
      }
      if (!res.ok) throw new Error(data.error || 'Image generation failed.');

      const imageBase64 = data.result?.image_base64;
      if (!imageBase64) throw new Error('The generation completed without an image preview.');
      setGeneratedImage(`data:image/webp;base64,${imageBase64}`);
      setCredits(typeof data.credits_remain === 'number' ? data.credits_remain : credits);
    } catch (error) {
      setGenerationError(error instanceof Error ? error.message : 'Image generation failed.');
    } finally {
      setGenerating(false);
    }
  };

  const createPayment = async () => {
    if (!walletAddress) {
      setGenerationError('Log in with your Solana wallet before paying.');
      return;
    }
    const amount = Number(paymentAmount);
    if (!Number.isFinite(amount) || amount < 1) {
      setPaymentError('Enter at least $1.00 to add generation credits.');
      return;
    }

    paymentEventsRef.current?.close();
    setPaymentLoading(true);
    setPaymentError(null);
    try {
      const res = await fetch(`${API_BASE}/crypto-checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wallet_address: walletAddress, method: 'cute', amount }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Could not start payment.');

      setPaymentResult({ ...data, status: 'pending' });
      const events = new EventSource(`${API_BASE}/crypto-checkout/${data.intent_id}/events`);
      paymentEventsRef.current = events;
      events.onmessage = event => {
        const status = JSON.parse(event.data).status;
        if (status === 'paid') {
          events.close();
          paymentEventsRef.current = null;
          setPaymentResult(previous => previous ? { ...previous, status: 'paid' } : previous);
          setTimeout(() => {
            setPaymentResult(null);
            setNeedsPayment(false);
            void generateImage();
          }, 800);
        } else if (status === 'expired' || status === 'failed') {
          events.close();
          paymentEventsRef.current = null;
          setPaymentError('This payment request expired. Start a new one to continue.');
        }
      };
      events.onerror = () => {
        // The checkout remains valid; the user can still use the Solana Pay link.
        setPaymentError('Payment status is temporarily unavailable. Your payment request is still active.');
      };
    } catch (error) {
      setPaymentError(error instanceof Error ? error.message : 'Could not start payment.');
    } finally {
      setPaymentLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-pink-50 via-purple-50 to-cyan-50 relative overflow-x-clip">
      {/* Floating sparkles (decorative, aria-hidden) */}
      <div aria-hidden className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-16 left-8 text-pink-300 animate-sparkle" style={{ animationDelay: '0s' }}><Sparkles size={22} /></div>
        <div className="absolute top-48 right-12 text-purple-300 animate-sparkle" style={{ animationDelay: '1s' }}><Star size={26} /></div>
        <div className="absolute top-1/3 left-1/4 text-cyan-300 animate-sparkle" style={{ animationDelay: '2s' }}><Sparkles size={18} /></div>
        <div className="absolute bottom-32 right-1/4 text-pink-300 animate-sparkle" style={{ animationDelay: '0.5s' }}><Heart size={20} /></div>
        <div className="absolute bottom-48 left-12 text-yellow-300 animate-sparkle" style={{ animationDelay: '1.5s' }}><Star size={24} /></div>
      </div>

      {/* Nav */}
      <nav aria-label="Main navigation" className="w-full px-6 py-5 flex justify-between items-center max-w-screen-2xl mx-auto relative z-10">
        <Link href="/" className="flex items-center gap-2">
          <Image src={LOGO_IMG} alt="CuteDSL home" width={40} height={40} className="rounded-lg" priority />
          <span className="font-fredoka text-3xl font-bold text-pink-600">CuteDSL</span>
        </Link>
        <div className="hidden sm:flex gap-5 font-bold text-slate-700">
          <Link href="/" className="hover:text-pink-500 transition-colors flex items-center gap-1">
            <ArrowLeft size={16} /> Home
          </Link>
          <Link href="/search" className="hover:text-pink-500 transition-colors">Search</Link>
          <Link href="/video-gallery" className="hover:text-purple-500 transition-colors">Videos</Link>
          <Link href="/evals" className="hover:text-cyan-500 transition-colors">Evals</Link>
          <Link href="/blog" className="hover:text-purple-500 transition-colors">Blog</Link>
          <Link href="/docs" className="hover:text-blue-500 transition-colors">API Docs</Link>
        </div>
      </nav>

      {/* Breadcrumb (SEO-friendly) */}
      <nav aria-label="Breadcrumb" className="max-w-screen-2xl mx-auto px-6 pt-2 pb-1 text-sm text-slate-500 relative z-10">
        <ol className="flex items-center gap-2">
          <li><Link href="/" className="hover:text-pink-500">Home</Link></li>
          <li aria-hidden>›</li>
          <li className="text-slate-700 font-semibold">Gallery</li>
        </ol>
      </nav>

      <main className="w-full max-w-none mx-auto pb-16 relative z-10">
        {/* Hero */}
        <section className="text-center px-4 py-5 sm:py-6">
          <h1 className="font-fredoka text-4xl sm:text-5xl lg:text-6xl font-bold text-slate-800 mb-2">
            AI Art <span className="text-gradient-cute">Gallery</span>
          </h1>
          <p className="text-base sm:text-lg text-slate-600 max-w-3xl mx-auto font-medium">
            {imageCount > 0 ? imageCount.toLocaleString() : '100,000+'} AI-generated images —
            fairies, fantasy, anime, landscapes &amp; more.
            Powered by <span className="text-pink-500 font-semibold">CuteDSL Z-Image Turbo</span>.
          </p>
          <form action="/search" method="get" className="relative max-w-3xl mx-auto mt-5 text-left">
            <label htmlFor="gallery-search" className="sr-only">Search gallery prompts</label>
            <SearchIcon className="absolute left-4 sm:left-5 top-1/2 -translate-y-1/2 text-slate-400 z-10" size={22} />
            <input
              id="gallery-search"
              name="q"
              type="search"
              value={searchInput}
              onChange={event => setSearchInput(event.target.value)}
              onFocus={() => setSearchFocused(true)}
              onKeyDown={event => {
                const result = autocomplete.handleKeyDown(event);
                if (result && result !== 'handled') setSearchInput(result);
              }}
              onBlur={() => setTimeout(() => autocomplete.close(), 150)}
              placeholder="Search art, styles, characters, places…"
              autoComplete="off"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={autocomplete.isOpen || semanticSuggestions.length > 0}
              aria-controls="gallery-search-suggestions"
              className="w-full h-14 sm:h-16 pl-12 sm:pl-14 pr-28 sm:pr-32 rounded-2xl sm:rounded-3xl border border-pink-200 bg-white/95 shadow-lg shadow-pink-100/70 text-base sm:text-lg text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-4 focus:ring-pink-200/70 focus:border-pink-400 transition-all"
            />
            <button
              type="submit"
              className="absolute right-2 top-1/2 -translate-y-1/2 px-4 sm:px-6 h-10 sm:h-12 bg-gradient-to-r from-pink-500 to-purple-500 text-white rounded-xl sm:rounded-2xl font-bold hover:shadow-lg hover:shadow-pink-300/50 transition-all"
            >
              Search
            </button>

            {(autocomplete.isOpen || semanticSuggestions.length > 0) && (
              <div
                id="gallery-search-suggestions"
                role="listbox"
                className="absolute top-full left-0 right-0 mt-2 bg-white rounded-2xl border border-slate-200 shadow-2xl z-40 overflow-hidden"
              >
                {autocomplete.isOpen && autocomplete.suggestions.map((suggestion, index) => (
                  <button
                    key={`${suggestion.value}-${index}`}
                    type="button"
                    role="option"
                    aria-selected={index === autocomplete.selectedIndex}
                    onMouseDown={event => event.preventDefault()}
                    onClick={() => {
                      const selected = autocomplete.selectSuggestion(index);
                      if (selected) setSearchInput(selected);
                    }}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 text-left text-sm border-b border-slate-50 transition-colors ${
                      index === autocomplete.selectedIndex ? 'bg-pink-50' : 'hover:bg-pink-50'
                    }`}
                  >
                    <SearchIcon size={15} className="shrink-0 text-slate-300" />
                    <span className="truncate"><span className="text-slate-500">{suggestion.typed}</span><strong className="text-slate-800">{suggestion.completion}</strong></span>
                  </button>
                ))}
                {semanticSuggestions.length > 0 && (
                  <div className="px-4 py-1.5 text-[11px] uppercase tracking-wider font-bold text-slate-400 bg-slate-50">Matching prompts</div>
                )}
                {semanticSuggestions.map((suggestion, index) => (
                  <Link
                    key={`${suggestion}-${index}`}
                    href={`/search?q=${encodeURIComponent(suggestion)}`}
                    className="flex items-center gap-3 px-4 py-2.5 text-sm text-slate-600 hover:bg-pink-50 border-t border-slate-50"
                  >
                    <Sparkles size={15} className="shrink-0 text-pink-400" />
                    <span className="truncate">{suggestion}</span>
                  </Link>
                ))}
              </div>
            )}
          </form>

          <div className="mt-3 flex flex-wrap justify-center gap-2">
            <Link
              href="/#models"
              className="inline-flex items-center gap-2 px-4 py-2 bg-white text-slate-700 rounded-full font-bold shadow-md border border-pink-100 hover:scale-105 transition-all"
            >
              <Sparkles size={16} className="text-pink-500" /> Generate your own
            </Link>
          </div>
        </section>

        {/* Theme pills — crawlable static links to /search */}
        <section aria-labelledby="themes-heading" className="mb-4 px-4 sm:mb-5">
          <h2 id="themes-heading" className="sr-only">Popular themes</h2>
          <div className="flex flex-wrap justify-center gap-1.5">
            {THEMES.map(t => (
              <Link
                key={t.slug}
                href={`/tag/${t.slug}`}
                prefetch={false}
                rel="tag"
                className={`px-3 py-1 rounded-full text-white text-xs sm:text-sm font-bold bg-gradient-to-r ${t.color} hover:scale-105 hover:shadow-md transition-all`}
                title={`${t.label} AI art gallery`}
              >
                <span className="mr-1" aria-hidden>{t.emoji}</span>{t.label}
              </Link>
            ))}
            <Link
              href="/tags"
              prefetch={false}
              className="px-3 py-1 rounded-full text-xs sm:text-sm font-bold bg-white text-slate-700 border border-pink-200 hover:bg-pink-50 hover:scale-105 transition-all"
            >
              More tags →
            </Link>
          </div>
        </section>

        {/* Image grid */}
        {initialLoad ? (
          <div className="flex items-center justify-center py-24">
            <Loader2 className="animate-spin text-pink-400" size={48} />
          </div>
        ) : images.length === 0 ? (
          <div className="text-center py-24">
            <ImageIcon className="mx-auto mb-4 text-slate-300" size={64} />
            <p className="text-xl text-slate-500 font-medium">No images yet.</p>
          </div>
        ) : (
          <>
            <div className="isolate grid grid-cols-[repeat(auto-fill,minmax(128px,1fr))] sm:grid-cols-[repeat(auto-fill,minmax(148px,1fr))] lg:grid-cols-[repeat(auto-fill,minmax(168px,1fr))] 2xl:grid-cols-[repeat(auto-fill,minmax(188px,1fr))] gap-0 items-start bg-slate-950">
              {images.map((img, idx) => (
                <a
                  key={img.id}
                  href={`/image/${imageSlug(img.id, img.prompt)}`}
                  onClick={e => {
                    // Open lightbox for normal clicks; allow new-tab via modifiers.
                    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                    e.preventDefault();
                    setSelectedImage(img);
                  }}
                  className="group relative z-0 block overflow-hidden bg-slate-950 cursor-zoom-in transform-gpu transition-transform duration-200 ease-out hover:z-20 hover:scale-[1.035] focus-visible:z-20 focus-visible:scale-[1.035] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-white motion-reduce:transition-none motion-reduce:hover:scale-100"
                  title={img.prompt}
                >
                  <img
                    src={`${IMG_BASE}/${img.thumb_path || img.med_path || img.file_path}`}
                    alt={img.prompt}
                    loading={idx < 4 ? 'eager' : 'lazy'}
                    decoding="async"
                    fetchPriority={idx < 2 ? 'high' : 'auto'}
                    width={img.width}
                    height={img.height}
                    className="w-full h-auto block"
                    style={{ aspectRatio: `${img.width} / ${img.height}` }}
                  />
                  <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 transition-opacity duration-200 flex flex-col justify-end p-2">
                    <p className="text-white text-xs leading-snug line-clamp-3 font-medium">
                      {img.prompt}
                    </p>
                  </div>
                </a>
              ))}
            </div>

            {images.length < total && (
              <div ref={loaderRef} className="flex justify-center py-10">
                {loading ? (
                  <Loader2 className="animate-spin text-pink-400" size={32} />
                ) : (
                  <div className="h-4" />
                )}
              </div>
            )}

            <p className="text-center text-slate-400 text-sm mt-4">
              Showing {images.length.toLocaleString()} of {total.toLocaleString()} images
            </p>
          </>
        )}

        {/* Crawlable intro / about section — gives SEO text content for the page shell */}
        <section aria-labelledby="about-gallery" className="max-w-3xl mx-4 sm:mx-auto mt-12 bg-white/70 backdrop-blur-sm rounded-3xl p-8 border border-pink-100 shadow-sm">
          <h2 id="about-gallery" className="font-fredoka text-3xl font-bold text-slate-800 mb-4 flex items-center gap-2">
            <Sparkles className="text-pink-500" size={24} /> About the Gallery
          </h2>
          <p className="text-slate-600 leading-relaxed mb-4">
            Every image here was generated with <strong>CuteDSL Z-Image Turbo</strong> — a fused-kernel
            acceleration of the Z-Image diffusion transformer that runs <strong>2× faster</strong> on
            RTX 5090 via custom Triton kernels and NVFP4 quantization. Prompts come from the
            community-curated <em>daspartho/stable-diffusion-prompts</em> dataset, covering
            fairies, dragons, anime, landscapes, cyberpunk, kawaii animals, space, and more.
          </p>
          <p className="text-slate-600 leading-relaxed mb-4">
            Click any image to see its <strong>prompt, seed, model, and related art</strong>.
            Every image has its own SEO-friendly page under <code className="bg-pink-50 px-1.5 py-0.5 rounded text-pink-700">/image/...</code>,
            and the full catalog is indexed in the <Link href="/sitemap.xml" className="text-pink-500 hover:text-pink-600 underline">image sitemap</Link>.
          </p>
          <p className="text-slate-600 leading-relaxed">
            Want to generate your own? <Link href="/#api" className="text-pink-500 hover:text-pink-600 font-semibold">Grab an API key</Link>,
            deposit some $CUTEDSL, and call <code className="bg-pink-50 px-1.5 py-0.5 rounded text-pink-700">POST /api/service</code> with <code className="bg-pink-50 px-1.5 py-0.5 rounded text-pink-700">service: &quot;ra2&quot;</code> for
            the default ra2 art generator, or <code className="bg-pink-50 px-1.5 py-0.5 rounded text-pink-700">service: &quot;zimage&quot;</code> for the faster
            Z-Image Turbo engine.
          </p>
        </section>
      </main>

      {/* Lightbox */}
      {selectedImage && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Image detail"
          className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-0 sm:p-4 backdrop-blur-sm"
          onClick={() => setSelectedImage(null)}
        >
          <div
            className="bg-white w-full h-full sm:h-auto sm:max-w-[min(96vw,1280px)] sm:max-h-[94vh] sm:rounded-2xl overflow-y-auto lg:overflow-hidden shadow-2xl lg:grid lg:grid-cols-[minmax(0,1fr)_380px]"
            onClick={e => e.stopPropagation()}
          >
            <div className="relative bg-black flex items-center justify-center min-h-[42vh] lg:h-[94vh] lg:max-h-[900px]">
              <img
                src={`${IMG_BASE}/${selectedImage.med_path || selectedImage.file_path}`}
                alt={selectedImage.prompt}
                width={selectedImage.width}
                height={selectedImage.height}
                className="block w-full h-full max-h-[68vh] lg:max-h-full object-contain bg-black"
              />
              <button
                onClick={() => setSelectedImage(null)}
                aria-label="Close"
                className="absolute top-3 right-3 lg:hidden p-2 bg-black/60 hover:bg-black/80 rounded-full text-white transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            <aside className="relative p-5 sm:p-6 lg:h-[94vh] lg:max-h-[900px] lg:overflow-y-auto">
              <button
                onClick={() => setSelectedImage(null)}
                aria-label="Close"
                className="hidden lg:block absolute top-4 right-4 p-2 bg-slate-100 hover:bg-slate-200 rounded-full text-slate-600 transition-colors"
              >
                <X size={18} />
              </button>

              <div className="pr-10 mb-4">
                <p className="text-xs font-bold uppercase tracking-[0.16em] text-pink-500 mb-1">Create from this image</p>
                <h2 className="font-fredoka text-2xl font-bold text-slate-900">Make Similar Art</h2>
              </div>

              <label htmlFor="gallery-generation-prompt" className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">
                Your prompt
              </label>
              <textarea
                id="gallery-generation-prompt"
                value={editablePrompt}
                onChange={event => {
                  setEditablePrompt(event.target.value);
                  setGenerationError(null);
                  setNeedsPayment(false);
                }}
                rows={5}
                maxLength={4000}
                disabled={Boolean(paymentResult)}
                className="w-full resize-y rounded-xl border border-pink-200 bg-pink-50/80 p-3 text-sm leading-relaxed text-slate-700 outline-none transition focus:border-pink-400 focus:ring-2 focus:ring-pink-200"
                aria-describedby="gallery-prompt-help"
              />
              <p id="gallery-prompt-help" className="mt-1 text-xs text-slate-400">
                Edit the prompt, then generate a new image without leaving the gallery.
              </p>

              <div className="mb-5">
                <p className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Explore similar tags</p>
                <div className="flex flex-wrap gap-1.5">
                  {promptTags(selectedImage.prompt).map(tag => (
                    <Link
                      key={tag}
                      href={`/tag/${encodeURIComponent(tag)}`}
                      prefetch={false}
                      rel="tag"
                      className="px-2.5 py-1 rounded-full bg-purple-50 border border-purple-200 text-purple-700 text-xs font-semibold hover:bg-purple-100 hover:border-purple-300 transition-colors"
                    >
                      {tag}
                    </Link>
                  ))}
                </div>
              </div>

              <div className="mt-5 rounded-2xl border border-pink-200 bg-gradient-to-br from-pink-50 to-purple-50 p-4">
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div>
                    <p className="text-sm font-bold text-slate-800">Generate on this page</p>
                    <p className="text-xs text-slate-500">One image costs about ${generationPriceUSD.toFixed(2)} in credits.</p>
                  </div>
                  {walletAddress && credits !== null && (
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-white px-2 py-1 text-xs font-bold text-slate-600 border border-pink-100">
                      <Coins size={13} className="text-yellow-500" /> {Math.floor(credits).toLocaleString()}
                    </span>
                  )}
                </div>

                <div className="mb-3">
                  <p className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-1.5">Model</p>
                  <div className="flex gap-1 rounded-xl border border-pink-100 bg-white/70 p-1">
                    {IMAGE_SERVICES.map(option => (
                      <button
                        key={option.slug}
                        type="button"
                        onClick={() => {
                          setService(option.slug);
                          setGeneratedImage(null);
                          setGenerationError(null);
                        }}
                        className={`flex-1 rounded-lg px-3 py-2 text-xs font-bold transition ${service === option.slug ? 'bg-gradient-to-r from-pink-500 to-purple-500 text-white shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                      >
                        {option.label}
                        <span className={`block text-[10px] font-medium ${service === option.slug ? 'text-white/80' : 'text-slate-400'}`}>
                          {option.hint} &middot; ${servicePricesUSD[option.slug].toFixed(2)}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                {!walletAddress || !apiKey ? (
                  <button
                    type="button"
                    onClick={connectWallet}
                    disabled={connectingWallet}
                    className="w-full flex items-center justify-center gap-2 px-4 py-3.5 bg-gradient-to-r from-pink-500 to-purple-500 text-white rounded-xl font-bold shadow-lg shadow-pink-200 hover:shadow-xl transition-all disabled:opacity-60"
                  >
                    {connectingWallet ? <RefreshCw size={18} className="animate-spin" /> : <Wallet size={18} />}
                    {connectingWallet ? 'Logging in…' : 'Log in with Solana wallet'}
                  </button>
                ) : needsPayment ? (
                  <div className="space-y-3">
                    <p className="text-xs text-slate-600">Your balance is too low. Add credits, then generation will start automatically when payment is confirmed.</p>
                    {!paymentResult ? (
                      <div className="flex gap-2">
                        <label className="relative flex-1">
                          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm font-bold text-slate-400">$</span>
                          <input
                            type="number"
                            min="1"
                            step="0.01"
                            value={paymentAmount}
                            onChange={event => setPaymentAmount(event.target.value)}
                            className="w-full rounded-xl border border-slate-200 bg-white py-3 pl-7 pr-3 text-sm outline-none focus:border-pink-400 focus:ring-2 focus:ring-pink-200"
                            aria-label="Payment amount in US dollars"
                          />
                        </label>
                        <button
                          type="button"
                          onClick={createPayment}
                          disabled={paymentLoading}
                          className="flex items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-sm font-bold text-white transition hover:bg-slate-800 disabled:opacity-60"
                        >
                          {paymentLoading ? <RefreshCw size={16} className="animate-spin" /> : <Wallet size={16} />}
                          Pay &amp; continue
                        </button>
                      </div>
                    ) : (
                      <div className="rounded-xl border border-pink-200 bg-white p-3 text-sm">
                        {paymentResult.status === 'paid' ? (
                          <p className="flex items-center gap-2 font-bold text-green-600"><Check size={16} /> Payment received. Generating…</p>
                        ) : (
                          <>
                            <p className="font-bold text-slate-700">Send {paymentResult.amount_ui} $CUTEDSL to:</p>
                            <div className="mt-2 flex items-center gap-2">
                              <code className="min-w-0 flex-1 break-all rounded-lg bg-slate-100 px-2 py-2 text-xs text-slate-600">{paymentResult.deposit_address}</code>
                              <button type="button" onClick={() => copyPrompt(paymentResult.deposit_address)} className="shrink-0 rounded-lg p-2 hover:bg-slate-100" aria-label="Copy payment address">
                                {copied ? <Check size={16} className="text-green-500" /> : <Copy size={16} className="text-slate-400" />}
                              </button>
                            </div>
                            {paymentResult.solana_pay_url && (
                              <a href={paymentResult.solana_pay_url} className="mt-2 inline-flex items-center gap-1 text-xs font-bold text-purple-600 hover:text-purple-700">
                                Open in wallet <ArrowRight size={13} />
                              </a>
                            )}
                            <p className="mt-2 text-xs text-slate-400">Waiting for payment confirmation…</p>
                          </>
                        )}
                      </div>
                    )}
                    {paymentError && <p className="text-xs font-medium text-red-600">{paymentError}</p>}
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={generateImage}
                    disabled={generating || !editablePrompt.trim()}
                    className="w-full flex items-center justify-center gap-2 px-4 py-3.5 bg-gradient-to-r from-pink-500 to-purple-500 text-white rounded-xl font-bold shadow-lg shadow-pink-200 hover:shadow-xl transition-all disabled:opacity-60"
                  >
                    {generating ? <RefreshCw size={18} className="animate-spin" /> : <Wand2 size={18} />}
                    {generating ? 'Generating…' : 'Generate image'}
                  </button>
                )}
                {generationError && <p className="mt-2 text-xs font-medium text-red-600">{generationError}</p>}
                {generatedImage && (
                  <div className="mt-4 border-t border-pink-100 pt-4">
                    <p className="mb-2 text-xs font-bold uppercase tracking-wider text-pink-500">Your generated image</p>
                    <img src={generatedImage} alt={`Generated from ${editablePrompt}`} className="w-full rounded-xl bg-slate-950 shadow-lg" />
                    <a href={generatedImage} download="cutedsl-gallery-generation.webp" className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-bold text-slate-700 border border-slate-200 hover:bg-slate-50">
                      Download image <ArrowRight size={14} />
                    </a>
                  </div>
                )}
              </div>
              <Link
                href={`/generations?prompt=${encodeURIComponent(selectedImage.prompt)}&first_frame=${encodeURIComponent(`https://cutedsl.cc${IMG_BASE}/${selectedImage.file_path}`)}`}
                className="mt-2 w-full flex items-center justify-center gap-2 px-4 py-3 bg-slate-900 text-white rounded-xl font-bold hover:bg-slate-800 transition-colors"
              >
                <Film size={18} />
                Animate this artwork
              </Link>
              <button
                onClick={() => setEditingImage(true)}
                className="mt-2 w-full flex items-center justify-center gap-2 px-4 py-3 bg-purple-50 border border-purple-200 text-purple-800 rounded-xl font-bold hover:bg-purple-100 transition-colors"
              >
                <SlidersHorizontal size={18} />
                Grade &amp; export
              </button>

              <div className="flex flex-wrap gap-2 text-xs text-slate-400 my-5 pt-5 border-t border-slate-100">
                <span className="bg-slate-50 border border-slate-200 px-2.5 py-1 rounded-lg">
                  {selectedImage.width}×{selectedImage.height}
                </span>
                <span className="bg-slate-50 border border-slate-200 px-2.5 py-1 rounded-lg">
                  {selectedImage.model}
                </span>
                <span className="bg-slate-50 border border-slate-200 px-2.5 py-1 rounded-lg">
                  {selectedImage.steps} steps
                </span>
                {selectedImage.seed > 0 && (
                  <span className="bg-slate-50 border border-slate-200 px-2.5 py-1 rounded-lg">
                    seed {selectedImage.seed}
                  </span>
                )}
              </div>

              <div className="grid grid-cols-2 gap-2">
                <a
                  href={`/image/${imageSlug(selectedImage.id, selectedImage.prompt)}`}
                  className="col-span-2 flex items-center justify-center gap-1.5 px-4 py-2 bg-slate-900 text-white rounded-xl font-bold hover:bg-slate-800 transition-colors text-sm"
                >
                  <ExternalLink size={14} />
                  View full page &amp; related art
                </a>
                <a
                  href={`${IMG_BASE}/${selectedImage.file_path}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-4 py-2 bg-slate-100 text-slate-700 text-center rounded-xl font-bold hover:bg-slate-200 transition-colors text-sm"
                >
                  Full res
                </a>
                <button
                  onClick={() => copyPrompt(selectedImage.prompt)}
                  className="flex items-center justify-center gap-1.5 px-4 py-2 bg-slate-100 text-slate-700 rounded-xl font-bold hover:bg-slate-200 transition-colors text-sm"
                >
                  {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
                  {copied ? 'Copied!' : 'Copy prompt'}
                </button>
                <ShareButton
                  title="CuteDSL AI artwork"
                  text={selectedImage.prompt}
                  url={`/image/${imageSlug(selectedImage.id, selectedImage.prompt)}`}
                  className="col-span-2 flex items-center justify-center gap-1.5 px-4 py-2 bg-purple-50 text-purple-700 rounded-xl font-bold hover:bg-purple-100 transition-colors text-sm"
                />
              </div>
            </aside>
          </div>
        </div>
      )}

      {selectedImage && editingImage && (
        <MediaGradeEditor
          kind="image"
          src={`${IMG_BASE}/${selectedImage.file_path}`}
          title={selectedImage.prompt}
          onClose={() => setEditingImage(false)}
        />
      )}

      {/* Footer */}
      <footer className="bg-white/90 border-t border-pink-200 py-8 relative z-10">
        <div className="max-w-screen-2xl mx-auto px-6 flex flex-col sm:flex-row justify-between items-center gap-3">
          <p className="text-slate-400 text-sm">
            &copy; 2026{' '}
            <a href="https://app.nz" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500">
              Applied AI NZ
            </a>
          </p>
          <div className="flex flex-wrap gap-4 text-sm font-bold justify-center">
            <Link href="/" className="text-slate-500 hover:text-pink-500">Home</Link>
            <Link href="/search" className="text-slate-500 hover:text-pink-500">Search</Link>
            <Link href="/video-gallery" className="text-slate-500 hover:text-purple-500">Videos</Link>
            <Link href="/evals" className="text-slate-500 hover:text-cyan-500">Evals</Link>
            <Link href="/blog" className="text-slate-500 hover:text-purple-500">Blog</Link>
            <Link href="/docs" className="text-slate-500 hover:text-blue-500">API Docs</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
