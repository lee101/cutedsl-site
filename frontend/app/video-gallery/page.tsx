'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, ExternalLink, Film, Loader2, Plus, Sparkles } from 'lucide-react';
import { ShareButton } from '@/lib/share-button';

interface PublicVideo {
  job_id: string;
  prompt: string;
  status: string;
  result?: { video_url?: string; codec?: string; output_format?: string };
  created_at: string;
}

function videoMIME(source: string): string {
  return source.toLowerCase().includes('.mp4') ? 'video/mp4' : 'video/webm; codecs=av01';
}

export default function VideoGalleryPage() {
  const [videos, setVideos] = useState<PublicVideo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/videos?limit=60')
      .then(response => response.json())
      .then(data => setVideos(data.videos || []))
      .catch(() => setVideos([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (videos.length === 0) return;
    const selected = new URLSearchParams(window.location.search).get('video');
    if (!selected) return;
    window.requestAnimationFrame(() => {
      document.getElementById(selected)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }, [videos]);

  return (
    <main className="min-h-screen bg-[#07070b] text-white">
      <nav className="px-5 py-5 flex justify-between items-center max-w-screen-2xl mx-auto">
        <Link href="/gallery" className="inline-flex items-center gap-2 text-slate-300 hover:text-white font-bold"><ArrowLeft size={17} /> Image gallery</Link>
        <Link href="/generations" className="inline-flex items-center gap-2 rounded-full bg-white text-slate-950 px-4 py-2 font-bold"><Plus size={16} /> Create video</Link>
      </nav>
      <header className="max-w-4xl mx-auto text-center px-5 py-12 sm:py-16">
        <p className="text-purple-400 uppercase tracking-[0.2em] text-xs font-bold mb-3">CuteDSL × ManifoldGen</p>
        <h1 className="font-fredoka text-5xl sm:text-7xl font-bold mb-4">Video, in motion.</h1>
        <p className="text-slate-400 text-lg">A curated wall of published AI generations, delivered with AV1-first source assets.</p>
      </header>

      {loading ? <Loader2 className="animate-spin text-purple-400 mx-auto mt-16" size={42} /> : videos.length === 0 ? (
        <section className="max-w-xl mx-auto text-center px-5 py-24">
          <Film className="mx-auto text-slate-700 mb-4" size={58} />
          <h2 className="text-2xl font-bold mb-2">The reel is developing</h2>
          <p className="text-slate-500 mb-6">Published generations will appear here automatically when their durable jobs complete.</p>
          <Link href="/generations" className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-pink-500 to-purple-600 px-5 py-3 font-bold"><Sparkles size={17} /> Make the first one</Link>
        </section>
      ) : (
        <section className="grid sm:grid-cols-2 xl:grid-cols-3 gap-px bg-white/10">
          {videos.map(video => {
            const source = video.result?.video_url || '';
            return <article id={video.job_id} key={video.job_id} className="group bg-[#0c0c12] overflow-hidden">
              <video controls muted loop playsInline preload="metadata" className="w-full aspect-video object-cover bg-black">
                <source src={source} type={videoMIME(source)} />
                <a href={source}>Open AV1 video</a>
              </video>
              <div className="p-4">
                <p className="text-sm text-slate-200 leading-relaxed line-clamp-3">{video.prompt}</p>
                <div className="flex items-center gap-4 mt-4 text-xs font-bold">
                  <a href={source} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-cyan-300 hover:text-cyan-200"><ExternalLink size={14} /> {source.toLowerCase().includes('.webm') ? 'AV1 source' : 'Source video'}</a>
                  <ShareButton title="CuteDSL AI video" text={video.prompt} url={`/video-gallery?video=${encodeURIComponent(video.job_id)}`} className="inline-flex items-center gap-1.5 text-purple-300 hover:text-purple-200" />
                </div>
              </div>
            </article>;
          })}
        </section>
      )}
    </main>
  );
}
