'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import {
  ArrowLeft, Loader2, ImageIcon, X, ExternalLink, Copy, Check,
  Sparkles, Star, Heart, Search as SearchIcon,
} from 'lucide-react';
import { linkifyPrompt } from '@/lib/prompt-linkify';
import { SiteFooter } from '../site-footer';
import { ArtGenerator } from '../art-generator';

const API_BASE = '/api';
const IMG_BASE = '/images';
const LOGO_IMG = 'https://appstatic.app.nz/cutedsl/images/logo.webp';
const PER_PAGE = 72;

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

export default function GalleryPage() {
  const [images, setImages] = useState<GeneratedImage[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);
  const [imageCount, setImageCount] = useState(0);
  const [selectedImage, setSelectedImage] = useState<GeneratedImage | null>(null);
  const [copied, setCopied] = useState(false);
  const loaderRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`${API_BASE}/images/count`)
      .then(r => r.json())
      .then(data => setImageCount(data.count || 0))
      .catch(() => {});
  }, []);

  const fetchImages = useCallback(async (p: number, append = false) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(p), per_page: String(PER_PAGE), skip_total: 'true' });
      const res = await fetch(`${API_BASE}/images?${params}`);
      const data = await res.json();
      const imgs: GeneratedImage[] = data.images || [];
      setImages(prev => append ? [...prev, ...imgs] : imgs);
      if (typeof data.total === 'number' && data.total > 0) {
        setTotal(data.total);
      }
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
    if (!selectedImage) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedImage(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedImage]);

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

  return (
    <div className="min-h-screen bg-gradient-to-br from-pink-50 via-purple-50 to-cyan-50 relative">
      {/* Floating sparkles (decorative, aria-hidden) */}
      <div aria-hidden className="fixed inset-0 pointer-events-none hidden overflow-hidden lg:block">
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
          <Link href="/playground" className="hover:text-pink-500 transition-colors">Playground</Link>
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

      <main className="w-full max-w-none mx-auto px-2 sm:px-3 lg:px-4 pb-16 relative z-10">
        {/* Hero */}
        <section className="text-center py-5 sm:py-6">
          <h1 className="font-fredoka text-4xl sm:text-5xl lg:text-6xl font-bold text-slate-800 mb-2">
            AI Art <span className="text-gradient-cute">Gallery</span>
          </h1>
          <p className="text-base sm:text-lg text-slate-600 max-w-3xl mx-auto font-medium">
            {imageCount > 0 ? imageCount.toLocaleString() : '100,000+'} AI-generated images —
            fairies, fantasy, anime, landscapes &amp; more.
            Powered by <span className="text-pink-500 font-semibold">CuteDSL Z-Image Turbo</span>.
          </p>
          <div className="mt-3 flex flex-wrap justify-center gap-2">
            <Link
              href="/search"
              className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-pink-400 to-purple-400 text-white rounded-full font-bold shadow-md hover:shadow-pink-300/50 hover:scale-105 transition-all"
            >
              <SearchIcon size={16} /> Search prompts
            </Link>
            <Link
              href="/playground"
              className="inline-flex items-center gap-2 px-4 py-2 bg-white text-slate-700 rounded-full font-bold shadow-md border border-pink-100 hover:scale-105 transition-all"
            >
              <Sparkles size={16} className="text-pink-500" /> Generate your own
            </Link>
          </div>
        </section>

        {/* Theme pills — crawlable static links to /search */}
        <section aria-labelledby="themes-heading" className="mb-4 sm:mb-5 px-1">
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
        <section aria-label="Gallery results" className="min-h-[75vh]">
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
            <div className="grid grid-cols-[repeat(auto-fill,minmax(128px,1fr))] sm:grid-cols-[repeat(auto-fill,minmax(148px,1fr))] lg:grid-cols-[repeat(auto-fill,minmax(168px,1fr))] 2xl:grid-cols-[repeat(auto-fill,minmax(188px,1fr))] gap-1.5 sm:gap-2 items-start">
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
                  className="content-visibility-auto group relative block cursor-pointer overflow-hidden rounded-md border border-pink-100 bg-white shadow-sm transition-[border-color,box-shadow,transform] duration-150 hover:-translate-y-0.5 hover:border-pink-300 hover:shadow-lg"
                  title={img.prompt}
                >
                  <img
                    src={`${IMG_BASE}/${img.thumb_path || img.med_path || img.file_path}`}
                    alt={img.prompt}
                    loading={idx < 8 ? 'eager' : 'lazy'}
                    decoding="async"
                    fetchPriority={idx < 4 ? 'high' : 'auto'}
                    width={img.width}
                    height={img.height}
                    className="w-full h-auto block"
                    style={{ aspectRatio: `${img.width} / ${img.height}` }}
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex flex-col justify-end p-2">
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
        </section>

        {/* Crawlable intro / about section — gives SEO text content for the page shell */}
        <section aria-labelledby="about-gallery" className="content-visibility-auto max-w-3xl mx-auto mt-12 bg-white/80 rounded-3xl p-8 border border-pink-100 shadow-sm">
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
            Every image has its own SEO-friendly page under <code className="bg-pink-50 px-1.5 py-0.5 rounded text-pink-600">/image/...</code>,
            and the full catalog is indexed in the <Link href="/sitemap.xml" className="text-pink-500 hover:text-pink-600 underline">image sitemap</Link>.
          </p>
          <p className="text-slate-600 leading-relaxed">
            Want to generate your own? <Link href="/#api" className="text-pink-500 hover:text-pink-600 font-semibold">Grab an API key</Link>,
            deposit some $CUTEDSL, and call <code className="bg-pink-50 px-1.5 py-0.5 rounded text-pink-600">POST /api/service</code> with <code className="bg-pink-50 px-1.5 py-0.5 rounded text-pink-600">service: &quot;zimage&quot;</code>.
          </p>
        </section>
      </main>

      {/* Lightbox */}
      {selectedImage && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Image detail"
          className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-2 sm:p-4 backdrop-blur-sm"
          onClick={() => setSelectedImage(null)}
        >
          <div
            className="bg-white rounded-2xl w-full max-w-[min(96vw,1100px)] max-h-[94vh] overflow-y-auto shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <div className="relative">
              <img
                src={`${IMG_BASE}/${selectedImage.med_path || selectedImage.file_path}`}
                alt={selectedImage.prompt}
                width={selectedImage.width}
                height={selectedImage.height}
                className="w-full max-h-[76vh] rounded-t-2xl block object-contain bg-black"
                style={{ aspectRatio: `${selectedImage.width} / ${selectedImage.height}` }}
              />
              <button
                onClick={() => setSelectedImage(null)}
                aria-label="Close"
                className="absolute top-3 right-3 p-2 bg-black/50 hover:bg-black/70 rounded-full text-white transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            <div className="p-5">
              <p className="text-slate-800 text-base leading-relaxed mb-4 font-medium">
                {linkifyPrompt(selectedImage.prompt)}
              </p>
              <div className="flex flex-wrap gap-2 text-xs text-slate-400 mb-5">
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

              <div className="flex flex-wrap gap-2">
                <a
                  href={`/image/${imageSlug(selectedImage.id, selectedImage.prompt)}`}
                  className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-pink-500 to-purple-500 text-white rounded-xl font-bold hover:shadow-lg hover:shadow-pink-300/50 transition-all text-sm"
                >
                  <ExternalLink size={14} />
                  View page &amp; related
                </a>
                <a
                  href={`${IMG_BASE}/${selectedImage.file_path}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-4 py-2 bg-pink-500 text-white rounded-xl font-bold hover:bg-pink-600 transition-colors text-sm"
                >
                  Full res
                </a>
                <button
                  onClick={() => copyPrompt(selectedImage.prompt)}
                  className="flex items-center gap-1.5 px-4 py-2 bg-slate-100 text-slate-700 rounded-xl font-bold hover:bg-slate-200 transition-colors text-sm"
                >
                  {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
                  {copied ? 'Copied!' : 'Copy prompt'}
                </button>
              </div>

              <div className="mt-5">
                <ArtGenerator
                  compact
                  title="Make Similar Art"
                  initialPrompt={selectedImage.prompt}
                  onGenerated={(image) => {
                    setImages(prev => [image, ...prev]);
                    setTotal(prev => prev + 1);
                    setImageCount(prev => prev + 1);
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      )}

      <SiteFooter />
    </div>
  );
}
