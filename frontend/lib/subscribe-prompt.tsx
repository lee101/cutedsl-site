'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { Check, CreditCard, Sparkles, X } from 'lucide-react';
import { HTTPResponseError } from '@/lib/http';
import { track } from '@/lib/analytics';

export const SUBSCRIBE_PATH = '/account';

export type PaywallReason = 'login' | 'subscribe';

export interface PaywallInfo {
  reason: PaywallReason;
  message?: string;
  subscribeUrl: string;
}

// Maps a 401/402 API error (paywall contract) to a subscribe prompt.
export function paywallFromError(err: unknown): PaywallInfo | null {
  if (!(err instanceof HTTPResponseError) || (err.status !== 401 && err.status !== 402)) return null;
  const data = (err.data && typeof err.data === 'object' ? err.data : {}) as Record<string, unknown>;
  const e = (data.error && typeof data.error === 'object' ? data.error : {}) as Record<string, unknown>;
  const url = typeof e.subscribe_url === 'string' ? e.subscribe_url : SUBSCRIBE_PATH;
  let path = SUBSCRIBE_PATH;
  try {
    const u = new URL(url, window.location.origin);
    if (u.origin === window.location.origin || u.hostname.endsWith('cutedsl.cc')) path = u.pathname + u.search;
  } catch {}
  return {
    reason: err.status === 401 ? 'login' : 'subscribe',
    message: typeof e.message === 'string' ? e.message : err.message,
    subscribeUrl: path,
  };
}

const PERKS = [
  'Unlimited ra2 image generation and edits',
  '$10 in monthly rollover credits for video and other models',
  'Same API key works in the playground and your code',
];

export function SubscribeCard({ info, onClose, compact }: { info: PaywallInfo; onClose?: () => void; compact?: boolean }) {
  const title = info.reason === 'login' ? 'Sign in to edit with ra2' : 'Unlock unlimited image edits';
  const surface = compact ? 'docs_inline' : 'docs_modal';
  useEffect(() => {
    track('paywall_open', { surface, reason: info.reason, page: window.location.pathname });
  }, [surface, info.reason]);
  return (
    <div
      data-testid="subscribe-prompt"
      className="relative overflow-hidden rounded-2xl border border-pink-200 bg-gradient-to-br from-pink-50 via-white to-purple-50 p-6 shadow-lg shadow-pink-100"
    >
      {onClose && (
        <button onClick={onClose} className="absolute right-3 top-3 rounded-lg p-2 text-slate-400 hover:bg-white" aria-label="Close">
          <X size={16} />
        </button>
      )}
      <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-white px-3 py-1 text-xs font-bold text-pink-600 shadow-sm">
        <Sparkles size={14} /> CuteDSL Monthly
      </div>
      <h3 className="font-fredoka text-2xl font-bold text-slate-900">{title}</h3>
      <div className="mt-2 text-3xl font-bold text-slate-950">
        $14 <span className="text-base font-semibold text-slate-500">/ month</span>
        <span className="ml-2 text-sm font-semibold text-emerald-600">or $140 / year</span>
      </div>
      {!compact && (
        <ul className="mt-4 space-y-2">
          {PERKS.map(p => (
            <li key={p} className="flex items-start gap-2 text-sm text-slate-700">
              <Check size={16} className="mt-0.5 shrink-0 text-emerald-500" /> {p}
            </li>
          ))}
        </ul>
      )}
      {info.message && info.reason === 'subscribe' && (
        <p className="mt-3 text-xs text-slate-500">{info.message}</p>
      )}
      <Link
        href={info.subscribeUrl}
        data-testid="subscribe-cta"
        onClick={() => track(info.reason === 'login' ? 'paywall_signup_clicked' : 'paywall_subscribe_clicked', { surface })}
        className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-pink-500 to-purple-500 px-5 py-3 text-sm font-bold text-white shadow-lg hover:shadow-pink-300/50 hover:scale-[1.01] transition-all"
      >
        <CreditCard size={16} /> {info.reason === 'login' ? 'Sign in and subscribe' : 'Subscribe now'}
      </Link>
      <p className="mt-2 text-center text-xs text-slate-500">Secure Stripe checkout. Cancel anytime. Pay-as-you-go credits also available.</p>
    </div>
  );
}

export function SubscribeModal({ info, onClose }: { info: PaywallInfo; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/60 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="Subscribe">
      <div className="w-full max-w-md">
        <SubscribeCard info={info} onClose={onClose} />
      </div>
    </div>
  );
}
