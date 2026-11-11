import type { Metadata } from 'next';
import Image from 'next/image';
import Link from 'next/link';
import {
  ArrowRight,
  AudioLines,
  Boxes,
  ExternalLink,
  Film,
  ImagePlus,
  Mic2,
  Move3d,
  Music2,
  Palette,
  ScanLine,
  Sparkles,
  Video,
} from 'lucide-react';
import { SiteFooter } from '../site-footer';
import { staticAssetPath } from '@/lib/static-assets';

const MANIFOLD = 'https://manifoldgen.com';

export const metadata: Metadata = {
  title: 'AI Creator Tools — Music, H3 Video & Animation',
  description:
    'Launch AI music studios, H3 video and character animation, video remake, voice, image generation, and the native CuteDSL playground from one creator hub.',
  alternates: { canonical: 'https://cutedsl.cc/tools' },
  openGraph: {
    type: 'website',
    url: 'https://cutedsl.cc/tools',
    siteName: 'CuteDSL',
    title: 'CuteDSL Creator Tools — Music, H3 Video & Animation',
    description: 'Create songs, animate characters, remake videos, and generate images from one AI creator hub.',
    images: [{ url: staticAssetPath('/images/og-image.webp'), width: 1360, height: 768, alt: 'CuteDSL creator tools' }],
  },
};

type Tool = {
  name: string;
  eyebrow: string;
  description: string;
  href: string;
  icon: typeof Sparkles;
  accent: string;
  surface: string;
  provider?: 'CuteDSL' | 'ManifoldGen';
};

const audioTools: Tool[] = [
  {
    name: 'Song Composer',
    eyebrow: 'PROMPT TO FULL SONG',
    description: 'Start with an idea. The composer develops the arrangement and lyrics, then Music3 records the finished track.',
    href: `${MANIFOLD}/tools/music-generator`,
    icon: Music2,
    accent: 'text-fuchsia-700',
    surface: 'from-fuchsia-100 to-pink-50 border-fuchsia-200',
    provider: 'ManifoldGen',
  },
  {
    name: 'Lyria 3 Music Studio',
    eyebrow: 'MUSIC DIRECTION',
    description: 'Direct complete songs, scores, vocal hooks, and loops with timed sections and production notes.',
    href: `${MANIFOLD}/tools/lyria`,
    icon: AudioLines,
    accent: 'text-violet-700',
    surface: 'from-violet-100 to-indigo-50 border-violet-200',
    provider: 'ManifoldGen',
  },
  {
    name: 'Gemini Voice Director',
    eyebrow: 'MULTI-SPEAKER VOICE',
    description: 'Stage expressive narration and two-person scenes with voice, accent, pace, and emotion controls.',
    href: `${MANIFOLD}/tools/gemini-tts`,
    icon: Mic2,
    accent: 'text-cyan-700',
    surface: 'from-cyan-100 to-sky-50 border-cyan-200',
    provider: 'ManifoldGen',
  },
];

const motionTools: Tool[] = [
  {
    name: 'H3 Video Studio',
    eyebrow: 'TEXT / IMAGE TO VIDEO',
    description: 'Generate H3 clips with first-frame control, seamless loops, native audio, and AV1 delivery through the CuteDSL API.',
    href: '/docs/h3_video',
    icon: Video,
    accent: 'text-teal-700',
    surface: 'from-teal-100 to-cyan-50 border-teal-200',
    provider: 'CuteDSL',
  },
  {
    name: 'Character Animator',
    eyebrow: 'CHARACTER + PERFORMANCE',
    description: 'Transfer movement, expression, and timing from a driving clip into a new character with Wan Animate.',
    href: `${MANIFOLD}/tools/character-animator`,
    icon: Move3d,
    accent: 'text-orange-700',
    surface: 'from-orange-100 to-amber-50 border-orange-200',
    provider: 'ManifoldGen',
  },
  {
    name: 'Pose Motion Space',
    eyebrow: 'H3 MOTION CONTROL',
    description: 'Use an ordinary performance video to drive the pose and timing of a new person, creature, or illustrated character.',
    href: `${MANIFOLD}/tools/pose-video`,
    icon: Boxes,
    accent: 'text-blue-700',
    surface: 'from-blue-100 to-indigo-50 border-blue-200',
    provider: 'ManifoldGen',
  },
  {
    name: 'Depth Video Space',
    eyebrow: 'H3 SPATIAL CONTROL',
    description: 'Restyle a moving scene while holding its depth, camera path, and three-dimensional volume together.',
    href: `${MANIFOLD}/tools/depth-video`,
    icon: ScanLine,
    accent: 'text-emerald-700',
    surface: 'from-emerald-100 to-teal-50 border-emerald-200',
    provider: 'ManifoldGen',
  },
  {
    name: 'Video Remake Agent',
    eyebrow: 'FULL-LENGTH RESTYLE',
    description: 'Detect shots, establish a coherent visual direction, rebuild the video, and preserve its timeline and soundtrack.',
    href: `${MANIFOLD}/tools/video-remake`,
    icon: Film,
    accent: 'text-rose-700',
    surface: 'from-rose-100 to-orange-50 border-rose-200',
    provider: 'ManifoldGen',
  },
];

const imageTools: Tool[] = [
  {
    name: 'Z-Image Playground',
    eyebrow: 'FAST IMAGE GENERATION',
    description: 'Generate and save CuteDSL Z-Image artwork, then explore related prompts and public gallery results.',
    href: '/playground',
    icon: Sparkles,
    accent: 'text-pink-700',
    surface: 'from-pink-100 to-rose-50 border-pink-200',
    provider: 'CuteDSL',
  },
  {
    name: 'Anima Art Studio',
    eyebrow: 'CHARACTER ART',
    description: 'Design anime-native characters and polished illustrations in a focused visual studio.',
    href: `${MANIFOLD}/tool/anima`,
    icon: Palette,
    accent: 'text-purple-700',
    surface: 'from-purple-100 to-fuchsia-50 border-purple-200',
    provider: 'ManifoldGen',
  },
  {
    name: 'H3 Image',
    eyebrow: 'VISUAL WORLD MODEL',
    description: 'Create high-detail finished frames, or use a source image to preserve identity and geometry while editing.',
    href: `${MANIFOLD}/tools/h3-image`,
    icon: ImagePlus,
    accent: 'text-sky-700',
    surface: 'from-sky-100 to-cyan-50 border-sky-200',
    provider: 'ManifoldGen',
  },
];

function ToolCard({ tool }: { tool: Tool }) {
  const Icon = tool.icon;
  const external = tool.href.startsWith('http');
  const content = (
    <>
      <div className={`mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-white/85 shadow-sm ${tool.accent}`}>
        <Icon size={25} />
      </div>
      <div className={`text-xs font-black tracking-[0.16em] ${tool.accent}`}>{tool.eyebrow}</div>
      <h3 className="mt-2 font-fredoka text-2xl font-bold text-slate-900">{tool.name}</h3>
      <p className="mt-3 flex-1 text-sm font-medium leading-6 text-slate-600">{tool.description}</p>
      <div className="mt-6 flex items-center justify-between gap-3 text-sm font-extrabold text-slate-800">
        <span className="rounded-full bg-white/75 px-3 py-1 text-xs text-slate-500">{tool.provider}</span>
        <span className="inline-flex items-center gap-1.5">Launch {external ? <ExternalLink size={15} /> : <ArrowRight size={15} />}</span>
      </div>
    </>
  );
  const classes = `group flex min-h-72 flex-col rounded-3xl border bg-gradient-to-br p-6 shadow-sm transition hover:-translate-y-1 hover:shadow-xl ${tool.surface}`;

  return external ? <a href={tool.href} className={classes}>{content}</a> : <Link href={tool.href} className={classes}>{content}</Link>;
}

function ToolSection({ id, eyebrow, title, copy, tools }: { id: string; eyebrow: string; title: string; copy: string; tools: Tool[] }) {
  return (
    <section id={id} className="scroll-mt-8 py-12 sm:py-16">
      <div className="max-w-3xl">
        <div className="text-xs font-black tracking-[0.2em] text-pink-600">{eyebrow}</div>
        <h2 className="mt-3 font-fredoka text-3xl font-bold text-slate-900 sm:text-5xl">{title}</h2>
        <p className="mt-3 text-base font-medium leading-7 text-slate-600 sm:text-lg">{copy}</p>
      </div>
      <div className="mt-8 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {tools.map((tool) => <ToolCard key={tool.name} tool={tool} />)}
      </div>
    </section>
  );
}

export default function ToolsPage() {
  return (
    <div className="min-h-screen bg-[linear-gradient(145deg,#fff1f7_0%,#ffffff_40%,#ecfeff_100%)]">
      <nav aria-label="Main navigation" className="mx-auto flex w-full max-w-7xl items-center justify-between px-6 py-5">
        <Link href="/" className="flex items-center gap-2">
          <Image src={staticAssetPath('/images/logo.webp')} alt="CuteDSL home" width={40} height={40} className="rounded-lg" priority />
          <span className="font-fredoka text-3xl font-bold text-pink-600">CuteDSL</span>
        </Link>
        <div className="flex items-center gap-4 text-sm font-bold text-slate-700 sm:gap-6">
          <Link href="/gallery" className="hidden hover:text-pink-600 sm:inline">Gallery</Link>
          <Link href="/docs" className="hover:text-blue-600">API</Link>
          <Link href="/account" className="rounded-full bg-slate-950 px-4 py-2 text-white hover:bg-slate-800">Account</Link>
        </div>
      </nav>

      <main className="mx-auto max-w-7xl px-6 pb-16">
        <header className="py-16 text-center sm:py-24">
          <div className="mx-auto inline-flex items-center gap-2 rounded-full border border-pink-200 bg-white/80 px-4 py-2 text-xs font-black tracking-[0.14em] text-pink-700 shadow-sm">
            <Sparkles size={15} /> CUTEDSL + MANIFOLDGEN
          </div>
          <h1 className="mx-auto mt-7 max-w-5xl font-fredoka text-5xl font-bold leading-[1.02] text-slate-900 sm:text-7xl">
            One launchpad for <span className="text-gradient-cute">music, motion, and worlds.</span>
          </h1>
          <p className="mx-auto mt-6 max-w-3xl text-lg font-medium leading-8 text-slate-600 sm:text-xl">
            Use CuteDSL&apos;s fast native models and API alongside ManifoldGen&apos;s production-ready creative studios. Pick a space and start making.
          </p>
          <div className="mt-9 flex flex-wrap justify-center gap-3">
            <a href="#music" className="rounded-full bg-fuchsia-600 px-5 py-2.5 text-sm font-extrabold text-white shadow-lg shadow-fuchsia-500/20">Make music</a>
            <a href="#motion" className="rounded-full bg-teal-600 px-5 py-2.5 text-sm font-extrabold text-white shadow-lg shadow-teal-500/20">Animate video</a>
            <a href="#images" className="rounded-full border border-pink-200 bg-white px-5 py-2.5 text-sm font-extrabold text-slate-800">Create images</a>
          </div>
        </header>

        <ToolSection id="music" eyebrow="MUSIC & VOICE" title="Build the soundtrack." copy="Go from a loose idea to a structured song, direct a score section by section, or stage expressive spoken scenes." tools={audioTools} />
        <ToolSection id="motion" eyebrow="H3 VIDEO & ANIMATION" title="Give every frame a pulse." copy="Generate clips from scratch, animate a character from a performance, preserve pose or depth, or coherently remake a longer video." tools={motionTools} />
        <ToolSection id="images" eyebrow="IMAGE SPACES" title="Find the world before it moves." copy="Sketch quickly with Z-Image, develop a character in Anima, or create high-detail H3 frames ready for animation." tools={imageTools} />
      </main>

      <SiteFooter />
    </div>
  );
}
