'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, ExternalLink, Film, Loader2, RefreshCw, Sparkles, Wand2 } from 'lucide-react';
import { ShareButton } from '@/lib/share-button';

interface GenerationJob {
  job_id: string;
  service: string;
  kind: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  prompt: string;
  result?: Record<string, unknown>;
  error?: string;
  is_public: boolean;
  created_at: string;
  updated_at: string;
}

const activeStatus = new Set(['queued', 'processing']);

function videoURL(job: GenerationJob): string {
  return typeof job.result?.video_url === 'string' ? job.result.video_url : '';
}

function videoMIME(source: string): string {
  return source.toLowerCase().includes('.mp4') ? 'video/mp4' : 'video/webm; codecs=av01';
}

export default function GenerationsPage() {
  const [apiKey, setAPIKey] = useState('');
  const [jobs, setJobs] = useState<GenerationJob[]>([]);
  const [prompt, setPrompt] = useState('');
  const [firstFrame, setFirstFrame] = useState('');
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [size, setSize] = useState('preview');
  const [duration, setDuration] = useState(5);
  const [publishOnFinish, setPublishOnFinish] = useState(false);
  const [estimatedUSD, setEstimatedUSD] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const loadJobs = useCallback(async (key: string) => {
    if (!key) return;
    try {
      const response = await fetch('/api/generations?limit=50', {
        headers: { Authorization: `Bearer ${key}` },
      });
      if (!response.ok) throw new Error('Could not load your generation queue');
      const data = await response.json();
      setJobs(data.jobs || []);
      setError('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load generations');
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshJob = useCallback(async (job: GenerationJob, key: string) => {
    if (!activeStatus.has(job.status)) return job;
    try {
      const response = await fetch(`/api/generations/${encodeURIComponent(job.job_id)}`, {
        headers: { Authorization: `Bearer ${key}` },
      });
      const data = await response.json();
      return data.job || job;
    } catch {
      return job;
    }
  }, []);

  useEffect(() => {
    const key = localStorage.getItem('cutedsl_api_key') || '';
    setAPIKey(key);
    const query = new URLSearchParams(window.location.search);
    setPrompt(query.get('prompt') || 'A glass hummingbird glides above moonlit trumpet flowers; slow macro orbit, dawn mist, delicate reflections, cinematic motion');
    setFirstFrame(query.get('first_frame') || '');
    if (key) loadJobs(key);
    else setLoading(false);
  }, [loadJobs]);

  useEffect(() => {
    fetch('/api/generations/pricing')
      .then(response => response.json())
      .then(data => {
        const tiers = data.video_pricing?.tiers || [];
        const tier = tiers.find((item: { size: string }) => item.size === size);
        const point = tier?.prices?.find((item: { duration_seconds: number }) => item.duration_seconds === duration);
        setEstimatedUSD(typeof point?.price_usd === 'number' ? point.price_usd : null);
      })
      .catch(() => setEstimatedUSD(null));
  }, [duration, size]);

  useEffect(() => {
    if (!apiKey || !jobs.some(job => activeStatus.has(job.status))) return;
    const timer = window.setInterval(async () => {
      const refreshed = await Promise.all(jobs.map(job => refreshJob(job, apiKey)));
      setJobs(refreshed);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [apiKey, jobs, refreshJob]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!apiKey || !prompt.trim()) return;
    setSubmitting(true);
    setError('');
    try {
      const response = await fetch('/api/generations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({
          prompt: prompt.trim(), first_frame: firstFrame.trim(), aspect_ratio: aspectRatio,
          size, duration, num_steps: 20, output_format: 'webm-av1',
          include_audio: true, structured_prompt: true, publish_on_finish: publishOnFinish,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not queue generation');
      setJobs(previous => [data.job, ...previous]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not queue generation');
    } finally {
      setSubmitting(false);
    }
  };

  const setPublished = async (job: GenerationJob, published: boolean) => {
    const response = await fetch(`/api/generations/${encodeURIComponent(job.job_id)}/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({ public: published }),
    });
    const data = await response.json();
    if (response.ok && data.job) {
      setJobs(previous => previous.map(item => item.job_id === job.job_id ? data.job : item));
    }
  };

  return (
    <main className="min-h-screen bg-slate-950 text-white">
      <nav className="max-w-7xl mx-auto px-5 py-5 flex justify-between items-center">
        <Link href="/gallery" className="inline-flex items-center gap-2 text-slate-300 hover:text-white font-bold"><ArrowLeft size={17} /> Gallery</Link>
        <Link href="/video-gallery" className="inline-flex items-center gap-2 text-purple-300 hover:text-purple-200 font-bold"><Film size={17} /> Video gallery</Link>
      </nav>

      <section className="max-w-7xl mx-auto px-5 pt-8 pb-16 grid lg:grid-cols-[420px_minmax(0,1fr)] gap-8">
        <div>
          <p className="text-pink-400 uppercase tracking-[0.18em] text-xs font-bold mb-2">Powered by ManifoldGen</p>
          <h1 className="font-fredoka text-4xl sm:text-5xl font-bold mb-3">Create, leave, come back.</h1>
          <p className="text-slate-400 mb-7">Your video runs as a durable queued job. Closing this page will not cancel it, and the result remains in your library.</p>

          {!apiKey ? (
            <div className="rounded-2xl border border-amber-400/30 bg-amber-400/10 p-5 text-amber-100">
              Connect your CuteDSL wallet first so this queue has a private owner.
              <Link href="/" className="mt-4 flex justify-center rounded-xl bg-white text-slate-950 px-4 py-3 font-bold">Connect wallet</Link>
            </div>
          ) : (
            <form onSubmit={submit} className="rounded-3xl border border-white/10 bg-white/[0.06] p-5 space-y-4 sticky top-5">
              <label className="block">
                <span className="block text-sm font-bold text-slate-200 mb-2">Describe the motion</span>
                <textarea value={prompt} onChange={event => setPrompt(event.target.value)} rows={7} required maxLength={4000} className="w-full rounded-xl bg-slate-900 border border-white/10 p-3 text-sm leading-relaxed outline-none focus:ring-2 focus:ring-pink-500 resize-y" />
              </label>
              <label className="block">
                <span className="block text-sm font-bold text-slate-200 mb-2">First frame URL <span className="text-slate-500 font-normal">optional</span></span>
                <input type="url" value={firstFrame} onChange={event => setFirstFrame(event.target.value)} placeholder="https://…" className="w-full rounded-xl bg-slate-900 border border-white/10 px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-pink-500" />
              </label>
              <div className="grid grid-cols-3 gap-2">
                <select value={aspectRatio} onChange={event => setAspectRatio(event.target.value)} aria-label="Aspect ratio" className="rounded-xl bg-slate-900 border border-white/10 px-2 py-2.5 text-sm"><option>16:9</option><option>9:16</option><option>1:1</option></select>
                <select value={size} onChange={event => setSize(event.target.value)} aria-label="Output size" className="rounded-xl bg-slate-900 border border-white/10 px-2 py-2.5 text-sm"><option value="preview">Preview</option><option value="balanced">Balanced</option><option value="native">Native</option></select>
                <select value={duration} onChange={event => setDuration(Number(event.target.value))} aria-label="Duration" className="rounded-xl bg-slate-900 border border-white/10 px-2 py-2.5 text-sm"><option value={5}>5 sec</option><option value={10}>10 sec</option><option value={15}>15 sec</option></select>
              </div>
              <label className="flex items-start gap-2 text-sm text-slate-400 cursor-pointer"><input type="checkbox" checked={publishOnFinish} onChange={event => setPublishOnFinish(event.target.checked)} className="mt-1 accent-pink-500" /><span>Publish to the indexed video gallery when complete</span></label>
              <button disabled={submitting} className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-pink-500 to-purple-600 px-4 py-3.5 font-bold disabled:opacity-60">
                {submitting ? <Loader2 className="animate-spin" size={18} /> : <Wand2 size={18} />}{submitting ? 'Submitting…' : 'Queue AV1 video'}
              </button>
              <p className="text-xs text-slate-500">AV1 WebM · persistent job · generated audio included{estimatedUSD !== null ? ` · estimated $${estimatedUSD.toFixed(2)}` : ''}</p>
            </form>
          )}
        </div>

        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-fredoka text-2xl font-bold">My generations</h2>
            {apiKey && <button onClick={() => loadJobs(apiKey)} className="p-2 text-slate-400 hover:text-white" aria-label="Refresh generations"><RefreshCw size={18} /></button>}
          </div>
          {error && <p className="mb-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-200 px-4 py-3">{error}</p>}
          {loading ? <Loader2 className="animate-spin text-purple-400 mt-12 mx-auto" size={36} /> : jobs.length === 0 ? (
            <div className="rounded-3xl border border-dashed border-white/15 py-20 text-center text-slate-500"><Sparkles className="mx-auto mb-3" />Your queued generations will appear here.</div>
          ) : (
            <div className="space-y-4">
              {jobs.map(job => {
                const source = videoURL(job);
                return <article key={job.job_id} className="rounded-2xl overflow-hidden border border-white/10 bg-white/[0.05]">
                  {source && <video controls playsInline preload="metadata" className="w-full max-h-[520px] bg-black"><source src={source} type={videoMIME(source)} /><a href={source}>Open video</a></video>}
                  <div className="p-4">
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold ${job.status === 'completed' ? 'bg-emerald-400/15 text-emerald-300' : job.status === 'failed' ? 'bg-red-400/15 text-red-300' : 'bg-purple-400/15 text-purple-300'}`}>
                        {activeStatus.has(job.status) && <Loader2 size={12} className="animate-spin" />}{job.status}
                      </span>
                      <time className="text-xs text-slate-500">{new Date(job.created_at).toLocaleString()}</time>
                    </div>
                    <p className="text-sm text-slate-200 leading-relaxed">{job.prompt}</p>
                    {job.error && <p className="text-sm text-red-300 mt-2">{job.error}</p>}
                    {job.status === 'completed' && source && <div className="flex flex-wrap items-center gap-3 mt-4 text-sm font-bold">
                      <a href={source} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-cyan-300 hover:text-cyan-200"><ExternalLink size={15} /> {source.toLowerCase().includes('.webm') ? 'AV1 source' : 'Source video'}</a>
                      <button onClick={() => setPublished(job, !job.is_public)} className="text-pink-300 hover:text-pink-200">{job.is_public ? 'Remove from gallery' : 'Publish to gallery'}</button>
                      <ShareButton title="CuteDSL AI video" text={job.prompt} url={job.is_public ? `/video-gallery?video=${encodeURIComponent(job.job_id)}` : source} className="inline-flex items-center gap-1.5 text-purple-300 hover:text-purple-200" />
                    </div>}
                  </div>
                </article>;
              })}
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
