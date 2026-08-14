'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Download, Eye, Film, ImageIcon, Loader2, Pause, Play, RotateCcw, SlidersHorizontal, X } from 'lucide-react';
import { DEFAULT_ADJUSTMENTS, StudioRenderer, type StudioAdjustments } from './media-grade-renderer';

type MediaGradeEditorProps = {
  kind: 'image' | 'video';
  src: string;
  title?: string;
  onClose: () => void;
};

type Control = {
  key: keyof StudioAdjustments;
  label: string;
  min: number;
  max: number;
  step: number;
  degrees?: boolean;
};

const CONTROLS: Control[] = [
  { key: 'exposure', label: 'Exposure', min: -2, max: 2, step: 0.01 },
  { key: 'brightness', label: 'Brightness', min: -0.5, max: 0.5, step: 0.01 },
  { key: 'contrast', label: 'Contrast', min: -0.8, max: 1, step: 0.01 },
  { key: 'highlights', label: 'Highlights', min: -1, max: 1, step: 0.01 },
  { key: 'shadows', label: 'Shadows', min: -1, max: 1, step: 0.01 },
  { key: 'saturation', label: 'Saturation', min: -1, max: 1, step: 0.01 },
  { key: 'temperature', label: 'Temperature', min: -1, max: 1, step: 0.01 },
  { key: 'tint', label: 'Tint', min: -1, max: 1, step: 0.01 },
  { key: 'shadowHue', label: 'Lowlight hue', min: -180, max: 180, step: 1, degrees: true },
  { key: 'midtoneHue', label: 'Midtone hue', min: -180, max: 180, step: 1, degrees: true },
  { key: 'highlightHue', label: 'Highlight hue', min: -180, max: 180, step: 1, degrees: true },
  { key: 'fade', label: 'Fade', min: 0, max: 1, step: 0.01 },
  { key: 'vignette', label: 'Vignette', min: 0, max: 1, step: 0.01 },
  { key: 'grain', label: 'Grain', min: 0, max: 1, step: 0.01 },
];

const PRESETS: { name: string; colors: string; values: Partial<StudioAdjustments> }[] = [
  { name: 'Clean', colors: '#a8b1bf,#48515e', values: {} },
  { name: 'Cinema', colors: '#d4975e,#183c4d', values: { contrast: 0.18, saturation: -0.08, temperature: 0.16, vignette: 0.22 } },
  { name: 'Chrome', colors: '#c5e6f7,#58677f', values: { contrast: 0.3, highlights: 0.14, temperature: -0.18 } },
  { name: 'Ember', colors: '#ff9c52,#55221d', values: { temperature: 0.44, tint: 0.08, shadows: -0.12 } },
  { name: 'Mist', colors: '#d6e2e4,#76849b', values: { fade: 0.58, contrast: -0.18, highlights: 0.22 } },
  { name: 'Noir', colors: '#e2e2e2,#242424', values: { saturation: -1, contrast: 0.28, grain: 0.14 } },
];

function fit(width: number, height: number, maxWidth: number, maxHeight: number) {
  const scale = Math.min(1, maxWidth / Math.max(1, width), maxHeight / Math.max(1, height));
  return {
    width: Math.max(2, Math.round(width * scale / 2) * 2),
    height: Math.max(2, Math.round(height * scale / 2) * 2),
  };
}

function proxiedSource(src: string) {
  if (!/^https?:\/\//i.test(src)) return src;
  if (typeof window === 'undefined') return src;
  try {
    if (new URL(src).origin === window.location.origin) return src;
  } catch {
    return src;
  }
  return `/api/media-proxy?url=${encodeURIComponent(src)}`;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2_000);
}

function waitForEvent(target: EventTarget, success: string, failure = 'error') {
  return new Promise<void>((resolve, reject) => {
    const done = () => { cleanup(); resolve(); };
    const failed = () => { cleanup(); reject(new Error('Media could not be loaded')); };
    const cleanup = () => {
      target.removeEventListener(success, done);
      target.removeEventListener(failure, failed);
    };
    target.addEventListener(success, done, { once: true });
    target.addEventListener(failure, failed, { once: true });
  });
}

export function MediaGradeEditor({ kind, src, title = 'Untitled media', onClose }: MediaGradeEditorProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<StudioRenderer | null>(null);
  const sourceRef = useRef<HTMLImageElement | HTMLVideoElement | null>(null);
  const frameRequestRef = useRef<number>(0);
  const adjustmentsRef = useRef<StudioAdjustments>({ ...DEFAULT_ADJUSTMENTS });
  const compareRef = useRef(false);
  const [adjustments, setAdjustments] = useState<StudioAdjustments>({ ...DEFAULT_ADJUSTMENTS });
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [comparing, setComparing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportProgress, setExportProgress] = useState(0);
  const [imageFormat, setImageFormat] = useState<'webp' | 'jpeg'>('webp');
  const [error, setError] = useState('');
  const sourceURL = useMemo(() => proxiedSource(src), [src]);

  adjustmentsRef.current = adjustments;
  compareRef.current = comparing;

  const draw = useCallback((source = sourceRef.current, seed = 0) => {
    if (!source || !rendererRef.current) return;
    rendererRef.current.draw(source, compareRef.current ? DEFAULT_ADJUSTMENTS : adjustmentsRef.current, seed);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    setReady(false);
    setError('');
    let cancelled = false;
    let video: HTMLVideoElement | null = null;
    let previewReady = false;
    const renderer = new StudioRenderer(canvas, { preserveDrawingBuffer: true });
    rendererRef.current = renderer;

    if (kind === 'image') {
      const image = new Image();
      image.decoding = 'async';
      image.onload = () => {
        if (cancelled) return;
        const dimensions = fit(image.naturalWidth, image.naturalHeight, 1600, 1100);
        renderer.resize(dimensions.width, dimensions.height);
        sourceRef.current = image;
        draw(image);
        setReady(true);
      };
      image.onerror = () => setError('This image could not be opened for editing.');
      image.src = sourceURL;
    } else {
      video = document.createElement('video');
      video.preload = 'auto';
      video.playsInline = true;
      video.crossOrigin = 'anonymous';
      video.src = sourceURL;
      sourceRef.current = video;
      video.addEventListener('loadedmetadata', () => {
        if (cancelled || !video) return;
        const dimensions = fit(video.videoWidth, video.videoHeight, 1600, 1000);
        renderer.resize(dimensions.width, dimensions.height);
        setDuration(video.duration || 0);
      });
      video.addEventListener('loadeddata', () => {
        if (cancelled || !video) return;
        draw(video);
        previewReady = true;
        setReady(true);
      });
      video.addEventListener('timeupdate', () => {
        if (!video) return;
        setCurrentTime(video.currentTime);
      });
      video.addEventListener('play', () => setPlaying(true));
      video.addEventListener('pause', () => { setPlaying(false); draw(video); });
      video.addEventListener('ended', () => { setPlaying(false); draw(video); });
      video.addEventListener('error', () => setError('This video could not be decoded in your browser.'));
      const renderFrame = (_now: number, metadata: VideoFrameCallbackMetadata) => {
        if (!video || cancelled) return;
        draw(video, Math.round(metadata.mediaTime * 24));
        if (!previewReady) {
          previewReady = true;
          setReady(true);
        }
        frameRequestRef.current = video.requestVideoFrameCallback(renderFrame);
      };
      frameRequestRef.current = video.requestVideoFrameCallback(renderFrame);
      video.load();
    }

    return () => {
      cancelled = true;
      if (video) {
        video.pause();
        if (frameRequestRef.current) video.cancelVideoFrameCallback(frameRequestRef.current);
        video.removeAttribute('src');
        video.load();
      }
      sourceRef.current = null;
      renderer.destroy();
      rendererRef.current = null;
    };
  }, [draw, kind, sourceURL]);

  useEffect(() => { draw(); }, [adjustments, comparing, draw]);

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !exporting) onClose();
      if (event.key === ' ' && kind === 'video' && !exporting) {
        event.preventDefault();
        const video = sourceRef.current as HTMLVideoElement | null;
        if (video) void (video.paused ? video.play() : Promise.resolve(video.pause()));
      }
    };
    window.addEventListener('keydown', keydown);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener('keydown', keydown);
    };
  }, [exporting, kind, onClose]);

  const update = (key: keyof StudioAdjustments, value: number) => {
    setAdjustments(current => ({ ...current, [key]: value }));
  };

  const exportImage = async () => {
    const image = sourceRef.current;
    if (!(image instanceof HTMLImageElement)) return;
    setExporting(true);
    setError('');
    let exportRenderer: StudioRenderer | null = null;
    try {
      const dimensions = fit(image.naturalWidth, image.naturalHeight, 4096, 4096);
      const canvas = document.createElement('canvas');
      exportRenderer = new StudioRenderer(canvas, { preserveDrawingBuffer: true });
      exportRenderer.resize(dimensions.width, dimensions.height);
      exportRenderer.draw(image, adjustments, 0, { fxaa: true });
      const mime = imageFormat === 'jpeg' ? 'image/jpeg' : 'image/webp';
      const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(value => value ? resolve(value) : reject(new Error('Image export failed')), mime, 0.94));
      downloadBlob(blob, `cutedsl-graded.${imageFormat === 'jpeg' ? 'jpg' : 'webp'}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Image export failed.');
    } finally {
      exportRenderer?.destroy();
      setExporting(false);
    }
  };

  const exportVideo = async () => {
    const video = sourceRef.current;
    if (!(video instanceof HTMLVideoElement) || !video.videoWidth || !video.duration) return;
    if (typeof MediaRecorder === 'undefined') {
      setError('Edited video export is not supported in this browser.');
      return;
    }
    setExporting(true);
    setExportProgress(0);
    setError('');
    const originalTime = video.currentTime;
    const wasPaused = video.paused;
    let exportRenderer: StudioRenderer | null = null;
    let exportStream: MediaStream | null = null;
    let recorder: MediaRecorder | null = null;
    try {
      const dimensions = fit(video.videoWidth, video.videoHeight, 1920, 1080);
      const canvas = document.createElement('canvas');
      exportRenderer = new StudioRenderer(canvas, { preserveDrawingBuffer: true });
      exportRenderer.resize(dimensions.width, dimensions.height);
      const fps = 30;
      exportStream = canvas.captureStream(fps);
      const capture = video as HTMLVideoElement & { captureStream?: () => MediaStream };
      const sourceStream = capture.captureStream?.();
      sourceStream?.getAudioTracks().forEach(track => exportStream?.addTrack(track));
      const candidates = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm'];
      const mimeType = candidates.find(candidate => MediaRecorder.isTypeSupported(candidate)) || '';
      const activeRecorder = new MediaRecorder(exportStream, mimeType ? { mimeType, videoBitsPerSecond: 8_000_000 } : undefined);
      recorder = activeRecorder;
      const chunks: BlobPart[] = [];
      activeRecorder.addEventListener('dataavailable', event => { if (event.data.size) chunks.push(event.data); });
      const stopped = waitForEvent(activeRecorder, 'stop');
      const ended = waitForEvent(video, 'ended');
      activeRecorder.start(500);
      video.currentTime = 0;
      const drawExportFrame = (_now: number, metadata: VideoFrameCallbackMetadata) => {
        if (activeRecorder.state === 'inactive' || !exportRenderer) return;
        exportRenderer.draw(video, adjustments, Math.round(metadata.mediaTime * fps));
        setExportProgress(Math.min(1, metadata.mediaTime / video.duration));
        video.requestVideoFrameCallback(drawExportFrame);
      };
      video.requestVideoFrameCallback(drawExportFrame);
      await video.play();
      await ended;
      activeRecorder.stop();
      await stopped;
      const blob = new Blob(chunks, { type: activeRecorder.mimeType || 'video/webm' });
      if (!blob.size) throw new Error('The browser produced an empty video export.');
      downloadBlob(blob, 'cutedsl-graded.webm');
      setExportProgress(1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Video export failed.');
    } finally {
      if (recorder?.state !== 'inactive') recorder?.stop();
      exportStream?.getTracks().forEach(track => track.stop());
      exportRenderer?.destroy();
      video.currentTime = Math.min(originalTime, video.duration || originalTime);
      if (!wasPaused) void video.play();
      setExporting(false);
    }
  };

  const togglePlayback = () => {
    const video = sourceRef.current;
    if (!(video instanceof HTMLVideoElement)) return;
    if (video.paused) void video.play(); else video.pause();
  };

  return (
    <div role="dialog" aria-modal="true" aria-label={`${kind} colour editor`} className="fixed inset-0 z-[100] bg-[#08090d] text-white flex flex-col">
      <header className="h-14 shrink-0 border-b border-white/10 px-3 sm:px-5 flex items-center justify-between gap-3 bg-[#111319]">
        <div className="min-w-0 flex items-center gap-3">
          <span className="w-8 h-8 grid place-items-center rounded-lg bg-purple-500/15 text-purple-300">{kind === 'video' ? <Film size={17} /> : <ImageIcon size={17} />}</span>
          <div className="min-w-0"><p className="font-bold text-sm truncate">{title}</p><p className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Non-destructive colour editor</p></div>
        </div>
        <div className="flex items-center gap-2">
          <button disabled={exporting} onClick={() => setAdjustments({ ...DEFAULT_ADJUSTMENTS })} className="hidden sm:inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-white/10 text-xs font-bold text-slate-300 hover:bg-white/5 disabled:opacity-40"><RotateCcw size={14} /> Reset</button>
          <button disabled={exporting} onPointerDown={() => setComparing(true)} onPointerUp={() => setComparing(false)} onPointerLeave={() => setComparing(false)} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-white/10 text-xs font-bold text-slate-300 hover:bg-white/5 disabled:opacity-40"><Eye size={14} /> Before</button>
          <button onClick={onClose} disabled={exporting} aria-label="Close editor" className="w-9 h-9 grid place-items-center rounded-lg hover:bg-white/10 disabled:opacity-40"><X size={19} /></button>
        </div>
      </header>

      <div className="min-h-0 flex-1 grid grid-rows-[minmax(45dvh,1fr)_minmax(0,1fr)] lg:grid-rows-1 lg:grid-cols-[minmax(0,1fr)_350px]">
        <section className="min-h-[45dvh] relative bg-black grid place-items-center overflow-hidden p-3 sm:p-6">
          {!ready && !error && <div className="absolute inset-0 grid place-items-center"><Loader2 className="animate-spin text-purple-400" size={38} /></div>}
          <canvas ref={canvasRef} onClick={kind === 'video' ? togglePlayback : undefined} className={`max-w-full max-h-full object-contain shadow-2xl ${kind === 'video' ? 'cursor-pointer' : ''}`} />
          {kind === 'video' && ready && (
            <div className="absolute left-4 right-4 bottom-4 sm:left-8 sm:right-8 flex items-center gap-3 rounded-xl bg-black/70 backdrop-blur-md border border-white/10 px-3 py-2">
              <button onClick={togglePlayback} disabled={exporting} className="w-8 h-8 grid place-items-center rounded-full bg-white text-black disabled:opacity-50">{playing ? <Pause size={15} /> : <Play size={15} className="ml-0.5" />}</button>
              <input aria-label="Video position" type="range" min="0" max={duration || 1} step="0.01" value={currentTime} disabled={exporting} onChange={event => { const video = sourceRef.current as HTMLVideoElement | null; if (video) { video.currentTime = Number(event.target.value); setCurrentTime(video.currentTime); draw(video); } }} className="min-w-0 flex-1 accent-purple-400" />
              <output className="text-[11px] tabular-nums text-slate-300">{Math.floor(currentTime)}s / {Math.ceil(duration)}s</output>
            </div>
          )}
        </section>

        <aside className="min-h-0 overflow-y-auto border-t lg:border-t-0 lg:border-l border-white/10 bg-[#111319] p-4 sm:p-5">
          <div className="flex items-center gap-2 mb-3"><SlidersHorizontal size={16} className="text-purple-300" /><h2 className="font-bold">Look &amp; tone</h2></div>
          <div className="grid grid-cols-3 gap-2 mb-5">
            {PRESETS.map(preset => <button key={preset.name} onClick={() => setAdjustments({ ...DEFAULT_ADJUSTMENTS, ...preset.values })} disabled={exporting} className="text-left p-1.5 rounded-lg border border-white/10 bg-white/[.025] hover:border-purple-400/60 disabled:opacity-40"><span className="block h-8 rounded-md mb-1.5" style={{ background: `linear-gradient(135deg, ${preset.colors})` }} /><b className="text-[10px] px-0.5">{preset.name}</b></button>)}
          </div>

          <div className="space-y-3.5">
            {CONTROLS.map(control => (
              <label key={control.key} className="block">
                <span className="flex justify-between text-[11px] font-bold text-slate-300 mb-1"><span>{control.label}</span><output className="text-slate-500 tabular-nums">{control.degrees ? `${Math.round(adjustments[control.key])}°` : Math.round(adjustments[control.key] * 100)}</output></span>
                <input type="range" min={control.min} max={control.max} step={control.step} value={adjustments[control.key]} disabled={exporting} onChange={event => update(control.key, Number(event.target.value))} className="block w-full accent-purple-400 disabled:opacity-40" />
              </label>
            ))}
          </div>

          <div className="sticky bottom-0 -mx-5 mt-6 p-5 border-t border-white/10 bg-[#111319]/95 backdrop-blur-xl">
            {kind === 'image' && <div className="grid grid-cols-2 gap-2 mb-2"><button onClick={() => setImageFormat('webp')} className={`py-2 rounded-lg border text-xs font-bold ${imageFormat === 'webp' ? 'border-purple-400 bg-purple-500/15 text-purple-200' : 'border-white/10 text-slate-400'}`}>WebP</button><button onClick={() => setImageFormat('jpeg')} className={`py-2 rounded-lg border text-xs font-bold ${imageFormat === 'jpeg' ? 'border-purple-400 bg-purple-500/15 text-purple-200' : 'border-white/10 text-slate-400'}`}>JPEG</button></div>}
            <button disabled={!ready || exporting} onClick={kind === 'image' ? exportImage : exportVideo} className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-pink-500 to-purple-600 px-4 py-3 font-bold disabled:opacity-40">
              {exporting ? <Loader2 className="animate-spin" size={17} /> : <Download size={17} />}
              {exporting ? (kind === 'video' ? `Rendering ${Math.round(exportProgress * 100)}%` : 'Exporting…') : `Export edited ${kind}`}
            </button>
            <p className="text-[10px] text-slate-500 text-center mt-2">{kind === 'video' ? 'Exports WebM in real time; audio is retained when supported.' : 'Rendered locally at source resolution, up to 4096px.'}</p>
            {error && <p role="alert" className="mt-3 text-xs text-rose-300 bg-rose-500/10 border border-rose-400/20 rounded-lg p-2.5">{error}</p>}
          </div>
        </aside>
      </div>
    </div>
  );
}
