'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import Link from 'next/link';
import { ArrowRight, Check, CreditCard, Loader2, Lock, SlidersHorizontal, Sparkles, X } from 'lucide-react';
import { HTTPResponseError, parseJSONResponse } from '@/lib/http';

const API_BASE = '/api';
const IMG_BASE = '/images';

interface StripeEmbeddedCheckout {
  mount: (target: string | HTMLElement) => void;
  destroy: () => void;
}

interface StripeBrowserClient {
  initEmbeddedCheckout: (options: {
    clientSecret: string;
    onComplete?: () => void;
  }) => Promise<StripeEmbeddedCheckout>;
}

declare global {
  interface Window {
    Stripe?: (publishableKey: string) => StripeBrowserClient;
  }
}

let stripeJsPromise: Promise<void> | null = null;

function loadStripeJS() {
  if (typeof window === 'undefined') return Promise.reject(new Error('Stripe.js requires a browser'));
  if (window.Stripe) return Promise.resolve();
  if (stripeJsPromise) return stripeJsPromise;

  stripeJsPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[src="https://js.stripe.com/v3/"]');
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true });
      existing.addEventListener('error', () => reject(new Error('Failed to load Stripe.js')), { once: true });
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://js.stripe.com/v3/';
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Failed to load Stripe.js'));
    document.head.appendChild(script);
  });

  return stripeJsPromise;
}

export interface GalleryImage {
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

interface AuthResponse {
  user: {
    wallet_address: string;
    email?: string;
    api_key: string;
    unlimited_api?: boolean;
    subscription_plan?: string;
  };
  api_key: string;
}

interface StripeCheckoutResponse {
  client_secret?: string;
  publishable_key?: string;
}

interface ArtGeneratorProps {
  initialPrompt?: string;
  compact?: boolean;
  title?: string;
  showPlaygroundLink?: boolean;
  onGenerated?: (image: GalleryImage) => void;
}

function slightlyDifferentPrompt(prompt: string) {
  const base = prompt.trim() || 'a cinematic cute fantasy scene, detailed digital art';
  if (/variation|similar/i.test(base)) return base;
  return `${base}, similar composition, fresh color palette, new lighting, subtle variation`;
}

function errorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback;
}

function storeAuth(data: AuthResponse) {
  localStorage.setItem('cutedsl_wallet', data.user.wallet_address);
  localStorage.setItem('cutedsl_api_key', data.api_key);
  if (data.user.email) localStorage.setItem('cutedsl_email', data.user.email);
}

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}

function clampToStep(value: number, min: number, max: number, step: number) {
  return Math.round(clamp(value, min, max) / step) * step;
}

export function ArtGenerator({ initialPrompt = '', compact = false, title = 'Make Similar Art', showPlaygroundLink = true, onGenerated }: ArtGeneratorProps) {
  const [prompt, setPrompt] = useState(() => slightlyDifferentPrompt(initialPrompt));
  const [wallet, setWallet] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [authOpen, setAuthOpen] = useState(false);
  const [paymentOpen, setPaymentOpen] = useState(false);
  const [loadingAuth, setLoadingAuth] = useState(false);
  const [loadingCheckout, setLoadingCheckout] = useState(false);
  const [loadingGenerate, setLoadingGenerate] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [resultURL, setResultURL] = useState<string | null>(null);
  const [savedImage, setSavedImage] = useState<GalleryImage | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [steps, setSteps] = useState(8);
  const [guidance, setGuidance] = useState(3.5);
  const [seed, setSeed] = useState('');
  const [publishableKey, setPublishableKey] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const checkoutRef = useRef<HTMLDivElement | null>(null);
  const embeddedCheckoutRef = useRef<StripeEmbeddedCheckout | null>(null);

  useEffect(() => {
    const savedPrompt = localStorage.getItem('cutedsl_last_art_prompt');
    if (!initialPrompt && savedPrompt) setPrompt(savedPrompt);
    setWallet(localStorage.getItem('cutedsl_wallet'));
    setApiKey(localStorage.getItem('cutedsl_api_key'));
    setEmail(localStorage.getItem('cutedsl_email') || '');
  }, [initialPrompt]);

  useEffect(() => {
    if (!clientSecret || !publishableKey || !checkoutRef.current) return;
    let cancelled = false;

    const mount = async () => {
      try {
        embeddedCheckoutRef.current?.destroy();
        embeddedCheckoutRef.current = null;
        await loadStripeJS();
        if (cancelled) return;
        const stripe = window.Stripe?.(publishableKey);
        if (!stripe) throw new Error('Stripe.js did not initialize');
        const checkout = await stripe.initEmbeddedCheckout({
          clientSecret,
          onComplete: () => {
            setStatus('Subscription complete. You can generate from this page now.');
            setClientSecret('');
            setPaymentOpen(false);
          },
        });
        if (cancelled) {
          checkout.destroy();
          return;
        }
        embeddedCheckoutRef.current = checkout;
        checkout.mount(checkoutRef.current!);
      } catch (err) {
        setStatus(errorMessage(err, 'Failed to load checkout'));
        setClientSecret('');
      }
    };

    mount();
    return () => {
      cancelled = true;
      embeddedCheckoutRef.current?.destroy();
      embeddedCheckoutRef.current = null;
    };
  }, [clientSecret, publishableKey]);

  const signIn = async () => {
    if (!email.includes('@') || password.length < 8) {
      setStatus('Enter an email and a password with at least 8 characters.');
      return;
    }
    setLoadingAuth(true);
    setStatus(null);
    try {
      const res = await fetch(`${API_BASE}/auth/email-login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      const data = await parseJSONResponse<AuthResponse>(res, 'Sign in failed');
      storeAuth(data);
      setWallet(data.user.wallet_address);
      setApiKey(data.api_key);
      setAuthOpen(false);
      setStatus('Signed in. Add the monthly plan or generate with existing credits.');
    } catch (err) {
      setStatus(errorMessage(err, 'Sign in failed'));
    } finally {
      setLoadingAuth(false);
    }
  };

  const startMonthlyCheckout = async () => {
    const activeWallet = wallet || localStorage.getItem('cutedsl_wallet');
    if (!activeWallet) {
      setAuthOpen(true);
      return;
    }
    setLoadingCheckout(true);
    setStatus(null);
    try {
      const res = await fetch(`${API_BASE}/stripe-checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          wallet_address: activeWallet,
          type: 'subscription',
          plan: 'monthly',
          return_url: `${window.location.origin}${window.location.pathname}?payment=success&session_id={CHECKOUT_SESSION_ID}`,
        }),
      });
      const data = await parseJSONResponse<StripeCheckoutResponse>(res, 'Checkout failed');
      if (!data.client_secret || !data.publishable_key) throw new Error('Stripe checkout did not return an embedded client secret');
      setPublishableKey(data.publishable_key);
      setClientSecret(data.client_secret);
      setPaymentOpen(true);
    } catch (err) {
      setStatus(errorMessage(err, 'Checkout failed'));
    } finally {
      setLoadingCheckout(false);
    }
  };

  const generate = useCallback(async () => {
    const activeKey = apiKey || localStorage.getItem('cutedsl_api_key');
    if (!activeKey) {
      setAuthOpen(true);
      return;
    }
    const cleanPrompt = prompt.trim();
    if (cleanPrompt.length < 4) {
      setStatus('Prompt is too short.');
      return;
    }
    localStorage.setItem('cutedsl_last_art_prompt', cleanPrompt);
    const normalizedWidth = clampToStep(width, 512, 1536, 64);
    const normalizedHeight = clampToStep(height, 512, 1536, 64);
    const normalizedSteps = Math.round(clamp(steps, 4, 40));
    const normalizedGuidance = Number(clamp(guidance, 1, 12).toFixed(1));
    const parsedSeed = seed.trim() ? Number.parseInt(seed.trim(), 10) : 0;
    if (seed.trim() && !Number.isFinite(parsedSeed)) {
      setStatus('Seed must be a whole number.');
      return;
    }
    setWidth(normalizedWidth);
    setHeight(normalizedHeight);
    setSteps(normalizedSteps);
    setGuidance(normalizedGuidance);
    setLoadingGenerate(true);
    setStatus(null);
    setResultURL(null);
    setSavedImage(null);
    try {
      const res = await fetch(`${API_BASE}/service`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${activeKey}` },
        body: JSON.stringify({
          service: 'zimage',
          prompt: cleanPrompt,
          width: normalizedWidth,
          height: normalizedHeight,
          num_steps: normalizedSteps,
          guidance: normalizedGuidance,
          ...(parsedSeed > 0 ? { seed: parsedSeed } : {}),
        }),
      });
      const data = await parseJSONResponse<any>(res, 'Generation failed').catch(err => {
        if (err instanceof HTTPResponseError) {
          if (err.status === 401) setAuthOpen(true);
          if (err.status === 402) setPaymentOpen(true);
        }
        throw err;
      });
      if (data.result?.image_base64) setResultURL(`data:image/webp;base64,${data.result.image_base64}`);
      const galleryImage = data.saved_image || data.result?.gallery_image;
      if (galleryImage) {
        setSavedImage(galleryImage);
        setResultURL(`${IMG_BASE}/${galleryImage.med_path || galleryImage.file_path}`);
        onGenerated?.(galleryImage);
      }
      setStatus(data.unlimited_api ? 'Generated with unlimited UI access.' : 'Generated and added to the gallery.');
    } catch (err) {
      setStatus(errorMessage(err, 'Generation failed'));
    } finally {
      setLoadingGenerate(false);
    }
  }, [apiKey, guidance, height, onGenerated, prompt, seed, steps, width]);

  return (
    <div className={`rounded-2xl border border-pink-100 bg-white shadow-sm ${compact ? 'p-4' : 'p-5 sm:p-6'}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="font-fredoka text-2xl font-bold text-slate-900">{title}</h3>
          <p className="text-sm text-slate-500">$12/mo includes unlimited UI generations and $12 API credits.</p>
        </div>
        {showPlaygroundLink && (
          <Link href="/playground" className="hidden items-center gap-1 rounded-lg px-3 py-2 text-sm font-bold text-pink-600 hover:bg-pink-50 sm:inline-flex">
            Playground <ArrowRight size={14} />
          </Link>
        )}
      </div>

      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={compact ? 3 : 4}
        className="w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-800 outline-none focus:border-pink-400 focus:bg-white focus:ring-2 focus:ring-pink-100"
        placeholder="Describe the image you want to generate..."
      />
      <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/70">
        <button
          type="button"
          onClick={() => setAdvancedOpen(open => !open)}
          className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm font-bold text-slate-800 hover:bg-white/70"
          aria-expanded={advancedOpen}
        >
          <span className="inline-flex items-center gap-2">
            <SlidersHorizontal size={16} className="text-pink-500" />
            Settings
          </span>
          <span className="text-xs font-semibold text-slate-500">
            {width}x{height} | {steps} steps | CFG {guidance}
          </span>
        </button>
        {advancedOpen && (
          <div className="grid gap-3 border-t border-slate-200 px-4 py-4 sm:grid-cols-2">
            <label className="block text-xs font-bold uppercase text-slate-500">
              Width
              <input
                type="number"
                min={512}
                max={1536}
                step={64}
                value={width}
                onChange={(e) => setWidth(Number(e.target.value))}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-800 outline-none focus:border-pink-400"
              />
            </label>
            <label className="block text-xs font-bold uppercase text-slate-500">
              Height
              <input
                type="number"
                min={512}
                max={1536}
                step={64}
                value={height}
                onChange={(e) => setHeight(Number(e.target.value))}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-800 outline-none focus:border-pink-400"
              />
            </label>
            <label className="block text-xs font-bold uppercase text-slate-500">
              Steps
              <input
                type="number"
                min={4}
                max={40}
                step={1}
                value={steps}
                onChange={(e) => setSteps(Number(e.target.value))}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-800 outline-none focus:border-pink-400"
              />
            </label>
            <label className="block text-xs font-bold uppercase text-slate-500">
              Guidance
              <input
                type="number"
                min={1}
                max={12}
                step={0.1}
                value={guidance}
                onChange={(e) => setGuidance(Number(e.target.value))}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-800 outline-none focus:border-pink-400"
              />
            </label>
            <label className="block text-xs font-bold uppercase text-slate-500 sm:col-span-2">
              Seed
              <input
                type="number"
                min={1}
                step={1}
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
                placeholder="Random"
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-800 outline-none focus:border-pink-400"
              />
            </label>
          </div>
        )}
      </div>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <button
          onClick={generate}
          disabled={loadingGenerate}
          className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-pink-500 to-purple-500 px-5 py-3 text-sm font-bold text-white shadow-sm hover:shadow-lg disabled:opacity-60"
        >
          {loadingGenerate ? <Loader2 size={17} className="animate-spin" /> : <Sparkles size={17} />}
          Generate
        </button>
        <button
          onClick={() => (wallet && apiKey ? startMonthlyCheckout() : setAuthOpen(true))}
          disabled={loadingCheckout}
          className="inline-flex items-center justify-center gap-2 rounded-xl border border-pink-200 bg-white px-5 py-3 text-sm font-bold text-slate-800 hover:bg-pink-50 disabled:opacity-60"
        >
          {loadingCheckout ? <Loader2 size={17} className="animate-spin" /> : <CreditCard size={17} />}
          $12/mo
        </button>
      </div>

      {status && (
        <div className={`mt-3 rounded-lg border px-3 py-2 text-sm ${status.toLowerCase().includes('failed') || status.toLowerCase().includes('insufficient') || status.toLowerCase().includes('required') ? 'border-red-200 bg-red-50 text-red-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
          {status}
        </div>
      )}

      {resultURL && (
        <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-slate-950">
          <img src={resultURL} alt={prompt} className="mx-auto block max-h-[520px] w-full object-contain" />
        </div>
      )}

      {savedImage && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm">
          <span className="inline-flex items-center gap-1 text-emerald-700"><Check size={14} /> Indexed in gallery</span>
          <Link href={`/search?q=${encodeURIComponent(savedImage.prompt)}`} className="font-bold text-pink-600 hover:text-pink-700">
            Browse similar art
          </Link>
        </div>
      )}

      {authOpen && (
        <Modal title="Sign In To Generate" onClose={() => setAuthOpen(false)}>
          <div className="space-y-3">
            <div className="rounded-lg border border-pink-100 bg-pink-50 px-3 py-2 text-sm text-slate-700">
              Sign in or create an account inline. Your prompt is kept on this page.
            </div>
            <label className="block text-xs font-bold uppercase text-slate-500">
              Email
              <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-3 text-base font-normal text-slate-800 outline-none focus:border-pink-400" />
            </label>
            <label className="block text-xs font-bold uppercase text-slate-500">
              Password
              <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-3 text-base font-normal text-slate-800 outline-none focus:border-pink-400" />
            </label>
            <button onClick={signIn} disabled={loadingAuth} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-slate-950 px-4 py-3 text-sm font-bold text-white disabled:opacity-60">
              {loadingAuth ? <Loader2 size={16} className="animate-spin" /> : <Lock size={16} />}
              Continue
            </button>
            <p className="text-xs text-slate-500">New emails create an account automatically.</p>
          </div>
        </Modal>
      )}

      {paymentOpen && (
        <Modal title="Unlock Unlimited UI Generation" onClose={() => { setPaymentOpen(false); setClientSecret(''); }}>
          <div className="space-y-4">
            <div className="rounded-xl border border-pink-100 bg-pink-50 p-4">
              <div className="text-3xl font-bold text-slate-950">$12 <span className="text-base font-semibold text-slate-500">/ month</span></div>
              <div className="mt-1 text-sm text-slate-600">Unlimited generations in the web UI plus $12 in API credits each checkout.</div>
            </div>
            {clientSecret ? (
              <div className="rounded-lg border border-slate-200 bg-white p-2">
                <div ref={checkoutRef} className="min-h-[480px]" />
              </div>
            ) : (
              <button onClick={startMonthlyCheckout} disabled={loadingCheckout} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-pink-600 px-4 py-3 text-sm font-bold text-white disabled:opacity-60">
                {loadingCheckout ? <Loader2 size={16} className="animate-spin" /> : <CreditCard size={16} />}
                Start Monthly Plan
              </button>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}

function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={title}>
      <div className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-5 shadow-2xl">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h3 className="font-fredoka text-2xl font-bold text-slate-900">{title}</h3>
          <button onClick={onClose} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
