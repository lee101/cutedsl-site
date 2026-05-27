'use client';

import Image from 'next/image';
import Link from 'next/link';
import { STATIC_BASE_URL } from '@/lib/static-assets';

const IMG_BASE = `${STATIC_BASE_URL}/images`;

const exploreLinks = [
  { label: 'Home', href: '/' },
  { label: 'AI Art Gallery', href: '/gallery' },
  { label: 'Art Playground', href: '/playground' },
  { label: 'Search Images', href: '/search' },
  { label: 'Evals & Benchmarks', href: '/evals' },
  { label: 'Blog', href: '/blog' },
  { label: 'API Docs', href: '/docs' },
  { label: 'LoRA Trainer', href: '/lora-trainer' },
  { label: 'Account', href: '/account' },
];

const modelLinks = [
  { label: 'Z-Image Turbo', href: '/docs/zimage' },
  { label: 'Chronos2 Forecasting', href: '/docs/chronos2' },
  { label: 'Text to Speech', href: '/docs/tts' },
  { label: 'Speech to Text', href: '/docs/stt' },
  { label: 'Gemma4 Vision', href: '/docs/gemma4' },
  { label: 'Image Captioning', href: '/docs/caption' },
  { label: 'Flux Image', href: '/docs/flux_image' },
  { label: 'LTX Video', href: '/docs/ltx_video' },
];

const ecosystemLinks = [
  { label: 'Applied AI NZ', href: 'https://app.nz' },
  { label: 'Netwrck', href: 'https://netwrck.com' },
  { label: 'Helix', href: 'https://helix.app.nz' },
  { label: 'Dictatorflow', href: 'https://dictatorflow.com' },
  { label: 'eBank', href: 'https://ebank.nz' },
  { label: 'BitBank', href: 'https://bitbank.nz' },
  { label: 'Text-Generator.io', href: 'https://text-generator.io' },
  { label: 'Codex Infinity', href: 'https://codex-infinity.com' },
];

const projectLinks = [
  { label: 'BigMultiplayerChess', href: 'https://bigmultiplayerchess.com' },
  { label: 'Evangeler', href: 'https://evangeler.com' },
  { label: 'reWord Game', href: 'https://rewordgame.com' },
  { label: 'How.nz', href: 'https://how.nz' },
  { label: 'Ring.nz', href: 'https://ring.nz' },
  { label: 'SiteSim', href: 'https://sitesim.net' },
  { label: 'DataTables', href: 'https://datatables.app.nz' },
  { label: 'CuteDSL GitHub', href: 'https://github.com/lee101/cutedsl' },
];

function FooterColumn({ title, links }: { title: string; links: { label: string; href: string }[] }) {
  return (
    <div>
      <h4 className="font-bold text-slate-800 mb-4">{title}</h4>
      <ul className="space-y-2 text-sm text-slate-500 font-medium">
        {links.map((link) => (
          <li key={`${title}-${link.href}`}>
            {link.href.startsWith('/') ? (
              <Link href={link.href} className="hover:text-pink-500 transition-colors">
                {link.label}
              </Link>
            ) : (
              <a href={link.href} target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500 transition-colors">
                {link.label}
              </a>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SiteFooter() {
  return (
    <footer className="bg-white/95 border-t border-pink-200 py-12 relative z-10">
      <div className="max-w-7xl mx-auto px-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-8 mb-10">
          <div className="sm:col-span-2">
            <div className="flex items-center gap-2 mb-4">
              <Image src={`${IMG_BASE}/logo.webp`} alt="CuteDSL" width={32} height={32} className="rounded-lg" />
              <span className="font-fredoka text-2xl font-bold text-slate-800">CuteDSL</span>
            </div>
            <p className="text-slate-500 font-medium max-w-sm">
              SOTA model acceleration, image generation, forecasting, speech, and multimodal inference. Built by{' '}
              <a href="https://app.nz" target="_blank" rel="noopener noreferrer" className="text-indigo-500 hover:text-indigo-700 underline">
                Applied AI NZ
              </a>
              .
            </p>
          </div>

          <FooterColumn title="Explore" links={exploreLinks} />
          <FooterColumn title="Models" links={modelLinks} />
          <FooterColumn title="Applied AI NZ" links={ecosystemLinks} />
          <FooterColumn title="Projects" links={projectLinks} />
        </div>

        <div className="border-t border-slate-200 pt-8 flex flex-col md:flex-row justify-between items-center gap-4">
          <p className="text-slate-400 font-medium text-sm">
            &copy; 2026{' '}
            <a href="https://app.nz" target="_blank" rel="noopener noreferrer" className="hover:text-indigo-500 transition-colors">
              Applied AI NZ
            </a>
            . All rights reserved.
          </p>
          <div className="flex flex-wrap justify-center gap-x-4 gap-y-2 text-sm font-bold">
            <a href="https://x.com/leeleepenkman" target="_blank" rel="noopener noreferrer" className="text-slate-400 hover:text-pink-500 transition-colors">X</a>
            <a href="https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS" target="_blank" rel="noopener noreferrer" className="text-slate-400 hover:text-purple-500 transition-colors">Buy $CUTEDSL</a>
            <a href="https://app.nz" target="_blank" rel="noopener noreferrer" className="text-slate-400 hover:text-indigo-500 transition-colors">app.nz</a>
          </div>
        </div>
      </div>
    </footer>
  );
}
