'use client';

import { FormEvent, useState } from 'react';
import { Coins, Film, Image as ImageIcon, Sparkles } from 'lucide-react';
import Link from 'next/link';

const BAGS_URL = 'https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS';

export function SiteCreateBar() {
  const [kind, setKind] = useState<'image' | 'video'>('image');
  const [prompt, setPrompt] = useState('');

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = prompt.trim();
    const query = value ? `?prompt=${encodeURIComponent(value)}` : '';
    window.location.assign(kind === 'video' ? `/generations${query}` : `/${query}#try-it`);
  };

  return (
    <aside
      aria-label="Create with CuteDSL"
      className="fixed inset-x-2 bottom-2 z-40 w-auto rounded-lg border border-pink-200 bg-white/95 p-2 shadow-xl shadow-slate-900/15 backdrop-blur-xl sm:inset-x-3"
    >
      <form onSubmit={submit} className="flex flex-col gap-2 lg:flex-row lg:items-center">
        <div className="flex shrink-0 items-center rounded-md bg-slate-100 p-0.5" aria-label="Creation type">
          <button
            type="button"
            onClick={() => setKind('image')}
            aria-pressed={kind === 'image'}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded px-3 py-2 text-sm font-bold transition-colors ${kind === 'image' ? 'bg-white text-pink-600 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}
          >
            <ImageIcon size={16} /> Image
          </button>
          <button
            type="button"
            onClick={() => setKind('video')}
            aria-pressed={kind === 'video'}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded px-3 py-2 text-sm font-bold transition-colors ${kind === 'video' ? 'bg-white text-purple-600 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}
          >
            <Film size={16} /> Video
          </button>
        </div>

        <label htmlFor="site-create-prompt" className="sr-only">Describe what you want to create</label>
        <input
          id="site-create-prompt"
          value={prompt}
          onChange={event => setPrompt(event.target.value)}
          maxLength={4000}
          className="min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none placeholder:text-slate-400 focus:border-pink-400 focus:ring-2 focus:ring-pink-100"
          placeholder={kind === 'image' ? 'Describe an image…' : 'Describe a video and its motion…'}
        />
        <button type="submit" className="flex shrink-0 items-center justify-center gap-2 rounded-md bg-gradient-to-r from-pink-500 to-purple-600 px-5 py-2.5 text-sm font-bold text-white hover:from-pink-600 hover:to-purple-700">
          <Sparkles size={16} /> Create {kind}
        </button>

        <div className="flex shrink-0 items-center justify-center gap-3 px-1 text-xs font-bold sm:text-sm">
          <Link href="/#api" className="inline-flex items-center gap-1 text-slate-600 hover:text-pink-600">
            <Coins size={15} /> Sign up / add credits
          </Link>
          <a href={BAGS_URL} target="_blank" rel="noopener noreferrer" className="text-purple-600 hover:text-purple-800">
            Buy $CUTEDSL on Bags ↗
          </a>
        </div>
      </form>
    </aside>
  );
}
