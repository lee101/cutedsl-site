'use client';

import { useCallback, useEffect, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { ArrowLeft, Image as ImageIcon, Loader2, Search, Sparkles } from 'lucide-react';
import { ArtGenerator, type GalleryImage } from '../art-generator';
import { SiteFooter } from '../site-footer';

const API_BASE = '/api';
const IMG_BASE = '/images';
const LOGO_IMG = 'https://appstatic.app.nz/cutedsl/images/logo.webp';

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

export default function PlaygroundPage() {
  const [wallet, setWallet] = useState<string | null>(null);
  const [images, setImages] = useState<GalleryImage[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);

  const loadMyImages = useCallback(async (activeWallet: string) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ wallet: activeWallet, per_page: '80', page: '1' });
      const res = await fetch(`${API_BASE}/images?${params}`);
      const data = await res.json();
      if (res.ok) {
        setImages(data.images || []);
        setTotal(data.total || 0);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const savedWallet = localStorage.getItem('cutedsl_wallet');
    setWallet(savedWallet);
    if (savedWallet) loadMyImages(savedWallet);
  }, [loadMyImages]);

  const handleGenerated = (image: GalleryImage) => {
    setImages(prev => [image, ...prev.filter(img => img.id !== image.id)]);
    setTotal(prev => prev + 1);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-pink-50 via-white to-cyan-50">
      <nav aria-label="Main navigation" className="mx-auto flex w-full max-w-screen-2xl items-center justify-between px-6 py-5">
        <Link href="/" className="flex items-center gap-2">
          <Image src={LOGO_IMG} alt="CuteDSL home" width={40} height={40} className="rounded-lg" priority />
          <span className="font-fredoka text-3xl font-bold text-pink-600">CuteDSL</span>
        </Link>
        <div className="hidden gap-5 font-bold text-slate-700 sm:flex">
          <Link href="/gallery" className="flex items-center gap-1 hover:text-pink-500">
            <ArrowLeft size={16} /> Gallery
          </Link>
          <Link href="/search" className="hover:text-pink-500">Search</Link>
          <Link href="/account" className="hover:text-pink-500">Account</Link>
          <Link href="/docs" className="hover:text-blue-500">API Docs</Link>
        </div>
      </nav>

      <main className="mx-auto max-w-7xl px-4 pb-16 sm:px-6">
        <section className="py-8 sm:py-12">
          <div className="max-w-3xl">
            <h1 className="font-fredoka text-4xl font-bold text-slate-900 sm:text-6xl">
              Z-Image <span className="text-gradient-cute">Playground</span>
            </h1>
            <p className="mt-3 text-lg font-medium text-slate-600">
              Generate art, keep your prompt on the page, browse your own outputs, and jump into similar public gallery images.
            </p>
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-[minmax(0,520px)_1fr]">
          <div className="lg:sticky lg:top-4 lg:self-start">
            <ArtGenerator title="Generate Art" onGenerated={handleGenerated} />
          </div>

          <div className="min-h-[520px] rounded-2xl border border-pink-100 bg-white/80 p-4 shadow-sm sm:p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-fredoka text-3xl font-bold text-slate-900">Your Generations</h2>
                <p className="text-sm text-slate-500">
                  {wallet ? `${total.toLocaleString()} image${total === 1 ? '' : 's'} saved to your account` : 'Sign in from the generator to start a personal gallery.'}
                </p>
              </div>
              {wallet && (
                <button
                  onClick={() => loadMyImages(wallet)}
                  disabled={loading}
                  className="inline-flex items-center gap-2 rounded-xl border border-pink-200 bg-white px-4 py-2 text-sm font-bold text-slate-800 hover:bg-pink-50 disabled:opacity-60"
                >
                  {loading ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} className="text-pink-500" />}
                  Refresh
                </button>
              )}
            </div>

            {loading ? (
              <div className="flex h-80 items-center justify-center">
                <Loader2 className="animate-spin text-pink-500" size={36} />
              </div>
            ) : images.length === 0 ? (
              <div className="flex h-80 flex-col items-center justify-center rounded-xl border border-dashed border-pink-200 bg-pink-50/40 text-center">
                <ImageIcon size={44} className="mb-3 text-pink-300" />
                <div className="text-lg font-bold text-slate-800">No generated images here yet</div>
                <div className="mt-1 max-w-md text-sm text-slate-500">Use the generator on this page or from any gallery image to create and index your first result.</div>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
                {images.map((img) => (
                  <div key={img.id} className="group overflow-hidden rounded-xl border border-pink-100 bg-white shadow-sm">
                    <Link href={`/image/${imageSlug(img.id, img.prompt)}`} className="block bg-slate-950">
                      <img
                        src={`${IMG_BASE}/${img.thumb_path || img.med_path || img.file_path}`}
                        alt={img.prompt}
                        className="aspect-square w-full object-cover transition-transform group-hover:scale-[1.03]"
                        loading="lazy"
                      />
                    </Link>
                    <div className="p-3">
                      <p className="line-clamp-2 text-xs font-medium leading-snug text-slate-700">{img.prompt}</p>
                      <div className="mt-3 flex items-center justify-between gap-2">
                        <span className="text-xs text-slate-400">{img.steps || 8} steps</span>
                        <Link href={`/search?q=${encodeURIComponent(img.prompt)}`} className="inline-flex items-center gap-1 text-xs font-bold text-pink-600 hover:text-pink-700">
                          <Search size={12} /> Similar
                        </Link>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
