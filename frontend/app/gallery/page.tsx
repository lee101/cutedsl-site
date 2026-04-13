'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { ArrowLeft, Loader2, ImageIcon, X, ExternalLink, Copy, Check } from 'lucide-react';

const API_BASE = '/api';
const IMG_BASE = '/images';
const LOGO_IMG = 'https://appstatic.app.nz/cutedsl/images/logo.webp';
const PER_PAGE = 60;

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

  // Infinite scroll
  useEffect(() => {
    if (!loaderRef.current) return;
    const observer = new IntersectionObserver(
      entries => {
        if (entries[0].isIntersecting && !loading && images.length < total) {
          fetchImages(page + 1, true);
        }
      },
      { threshold: 0.1 }
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
    <div className="min-h-screen bg-pink-50">
      {/* Nav */}
      <nav className="w-full px-6 py-5 flex justify-between items-center max-w-screen-2xl mx-auto">
        <Link href="/" className="flex items-center gap-2">
          <Image src={LOGO_IMG} alt="CuteDSL" width={40} height={40} className="rounded-lg" />
          <span className="font-fredoka text-3xl font-bold text-pink-600">CuteDSL</span>
        </Link>
        <div className="flex gap-6 font-bold text-slate-700">
          <Link href="/" className="hover:text-pink-500 transition-colors flex items-center gap-1">
            <ArrowLeft size={16} /> Home
          </Link>
          <Link href="/search" className="hover:text-pink-500 transition-colors">Search</Link>
          <Link href="/evals" className="hover:text-cyan-500 transition-colors">Evals</Link>
          <Link href="/blog" className="hover:text-purple-500 transition-colors">Blog</Link>
        </div>
      </nav>

      <main className="max-w-screen-2xl mx-auto px-4 pb-24">
        {/* Hero */}
        <div className="text-center py-10">
          <h1 className="font-fredoka text-5xl lg:text-7xl font-bold text-slate-800 mb-3">
            AI Art Gallery
          </h1>
          <p className="text-lg text-slate-500 max-w-xl mx-auto">
            {imageCount > 0 ? imageCount.toLocaleString() : '...'} images generated with{' '}
            <span className="text-pink-500 font-semibold">CuteDSL Z-Image Turbo</span>
          </p>
        </div>

        {/* Pinterest masonry grid */}
        {initialLoad ? (
          <div className="flex items-center justify-center py-32">
            <Loader2 className="animate-spin text-pink-400" size={48} />
          </div>
        ) : images.length === 0 ? (
          <div className="text-center py-32">
            <ImageIcon className="mx-auto mb-4 text-slate-300" size={64} />
            <p className="text-xl text-slate-500 font-medium">No images yet.</p>
          </div>
        ) : (
          <>
            {/* CSS columns masonry */}
            <div
              style={{
                columns: 'var(--gallery-cols, 2)',
                columnGap: '0.75rem',
              }}
              className="[--gallery-cols:2] sm:[--gallery-cols:3] md:[--gallery-cols:4] lg:[--gallery-cols:5] xl:[--gallery-cols:6] 2xl:[--gallery-cols:7]"
            >
              {images.map(img => (
                <div
                  key={img.id}
                  className="break-inside-avoid mb-3 group relative rounded-xl overflow-hidden bg-white border border-slate-100 shadow-sm hover:shadow-xl hover:border-pink-200 transition-all duration-200 cursor-pointer"
                  onClick={() => setSelectedImage(img)}
                >
                  <img
                    src={`${IMG_BASE}/${img.med_path || img.thumb_path || img.file_path}`}
                    alt={img.prompt}
                    loading="lazy"
                    className="w-full block"
                    style={{ aspectRatio: `${img.width} / ${img.height}` }}
                  />
                  {/* Hover overlay */}
                  <div className="absolute inset-0 bg-gradient-to-t from-black/75 via-black/20 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex flex-col justify-end p-3">
                    <p className="text-white text-xs leading-snug line-clamp-3 font-medium">
                      {img.prompt}
                    </p>
                  </div>
                </div>
              ))}
            </div>

            {/* Infinite scroll trigger */}
            {images.length < total && (
              <div ref={loaderRef} className="flex justify-center py-16">
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
      </main>

      {/* Lightbox */}
      {selectedImage && (
        <div
          className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4 backdrop-blur-sm"
          onClick={() => setSelectedImage(null)}
        >
          <div
            className="bg-white rounded-2xl max-w-2xl w-full max-h-[92vh] overflow-y-auto shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            {/* Image */}
            <div className="relative">
              <img
                src={`${IMG_BASE}/${selectedImage.med_path || selectedImage.file_path}`}
                alt={selectedImage.prompt}
                className="w-full rounded-t-2xl block"
              />
              <button
                onClick={() => setSelectedImage(null)}
                className="absolute top-3 right-3 p-2 bg-black/50 hover:bg-black/70 rounded-full text-white transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Info */}
            <div className="p-5">
              <p className="text-slate-800 text-base leading-relaxed mb-4 font-medium">
                {selectedImage.prompt}
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
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="bg-white/90 border-t border-pink-200 py-8">
        <div className="max-w-screen-2xl mx-auto px-6 flex justify-between items-center">
          <p className="text-slate-400 text-sm">
            &copy; 2026{' '}
            <a href="https://app.nz" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500">
              Applied Science Company
            </a>
          </p>
          <div className="flex gap-4 text-sm font-bold">
            <Link href="/" className="text-slate-500 hover:text-pink-500">Home</Link>
            <Link href="/search" className="text-slate-500 hover:text-pink-500">Search</Link>
            <Link href="/evals" className="text-slate-500 hover:text-cyan-500">Evals</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
