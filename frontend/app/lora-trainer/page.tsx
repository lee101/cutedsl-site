'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { ArrowLeft, Upload, X, Loader2, Play, Lock, Sparkles, Check } from 'lucide-react';
import { useAuth } from '@/hooks/use-auth';
import { staticAssetPath } from '@/lib/static-assets';

const LOGO_IMG = staticAssetPath('/images/logo.webp');

interface UploadItem {
  file: File;
  preview: string;
  caption: string;
  status: 'pending' | 'uploading' | 'done' | 'error';
  publicUrl?: string;
  error?: string;
  progress: number;
}

interface TrainingJob {
  job_id: string;
  status: string;
  progress: number;
  model: string;
  dataset_name?: string;
  image_count?: number;
  loss?: number;
  output_path?: string;
  error?: string;
  note?: string;
}

export default function LoraTrainerPage() {
  const { apiKey, isLoggedIn } = useAuth();
  const [items, setItems] = useState<UploadItem[]>([]);
  const [datasetName, setDatasetName] = useState('');
  const [modelType, setModelType] = useState<'zimage' | 'chronos2'>('zimage');
  const [loraR, setLoraR] = useState(16);
  const [loraAlpha, setLoraAlpha] = useState(32);
  const [learningRate, setLearningRate] = useState(0.0001);
  const [numSteps, setNumSteps] = useState(500);
  const [isUploading, setIsUploading] = useState(false);
  const [isTraining, setIsTraining] = useState(false);
  const [job, setJob] = useState<TrainingJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropRef = useRef<HTMLDivElement>(null);

  // Cleanup object URLs on unmount
  useEffect(() => {
    return () => { items.forEach(it => URL.revokeObjectURL(it.preview)); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll training job
  useEffect(() => {
    if (!job || !apiKey) return;
    if (job.status === 'completed' || job.status === 'failed') return;
    const id = setInterval(async () => {
      try {
        const res = await fetch(`/api/train/${job.job_id}`, {
          headers: { Authorization: `Bearer ${apiKey}` },
        });
        if (res.ok) {
          const data = await res.json();
          setJob(data);
          if (data.status === 'completed' || data.status === 'failed') {
            setIsTraining(false);
          }
        }
      } catch {/* ignore */}
    }, 2000);
    return () => clearInterval(id);
  }, [job, apiKey]);

  const addFiles = useCallback((files: FileList | File[]) => {
    const arr = Array.from(files).filter(f => f.type.startsWith('image/'));
    const newItems: UploadItem[] = arr.map(f => ({
      file: f,
      preview: URL.createObjectURL(f),
      caption: '',
      status: 'pending' as const,
      progress: 0,
    }));
    setItems(prev => [...prev, ...newItems]);
  }, []);

  const removeItem = (i: number) => {
    setItems(prev => {
      URL.revokeObjectURL(prev[i].preview);
      return prev.filter((_, idx) => idx !== i);
    });
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.files) addFiles(e.dataTransfer.files);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const updateCaption = (i: number, caption: string) => {
    setItems(prev => prev.map((it, idx) => (idx === i ? { ...it, caption } : it)));
  };

  // Upload one file via presigned PUT, returns the public URL
  const uploadOne = async (item: UploadItem, dataset: string, idx: number): Promise<string> => {
    const presignRes = await fetch(
      `/api/uploads/presign?filename=${encodeURIComponent(item.file.name)}&content_type=${encodeURIComponent(item.file.type || 'image/jpeg')}&dataset=${encodeURIComponent(dataset)}`,
      { headers: { Authorization: `Bearer ${apiKey}` } }
    );
    if (!presignRes.ok) {
      const e = await presignRes.json().catch(() => ({}));
      throw new Error(e.error || `Presign failed (${presignRes.status})`);
    }
    const { upload_url, public_url } = await presignRes.json();

    // PUT direct to R2 using XHR for progress
    await new Promise<void>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', upload_url);
      xhr.setRequestHeader('Content-Type', item.file.type || 'application/octet-stream');
      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) {
          const pct = Math.round((e.loaded / e.total) * 100);
          setItems(prev => prev.map((it, i) => (i === idx ? { ...it, progress: pct } : it)));
        }
      });
      xhr.onload = () => xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`Upload failed: ${xhr.status} ${xhr.responseText}`));
      xhr.onerror = () => reject(new Error('Network error during upload'));
      xhr.send(item.file);
    });

    return public_url;
  };

  const startTraining = async () => {
    setError(null);
    if (!datasetName.trim()) { setError('Dataset name is required'); return; }
    if (items.length === 0) { setError('Add at least one image'); return; }

    setIsUploading(true);
    const uploadedUrls: string[] = [];
    const uploadedCaptions: string[] = [];

    try {
      for (let i = 0; i < items.length; i++) {
        setItems(prev => prev.map((it, idx) => (idx === i ? { ...it, status: 'uploading' } : it)));
        try {
          const url = await uploadOne(items[i], datasetName, i);
          uploadedUrls.push(url);
          uploadedCaptions.push(items[i].caption);
          setItems(prev => prev.map((it, idx) => (idx === i ? { ...it, status: 'done', publicUrl: url, progress: 100 } : it)));
        } catch (e) {
          const msg = e instanceof Error ? e.message : 'Upload failed';
          setItems(prev => prev.map((it, idx) => (idx === i ? { ...it, status: 'error', error: msg } : it)));
        }
      }

      if (uploadedUrls.length === 0) throw new Error('All uploads failed');

      setIsUploading(false);
      setIsTraining(true);

      const trainRes = await fetch('/api/train/start', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          model: modelType,
          dataset_name: datasetName,
          image_urls: uploadedUrls,
          captions: uploadedCaptions,
          lora_r: loraR,
          lora_alpha: loraAlpha,
          learning_rate: learningRate,
          num_steps: numSteps,
        }),
      });
      const data = await trainRes.json();
      if (!trainRes.ok) {
        throw new Error(data.error || `Training kickoff failed (${trainRes.status})`);
      }
      // The wrapped response is { result: {job_id, ...}, credits_used, ... }
      setJob(data.result || data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Training failed');
      setIsUploading(false);
      setIsTraining(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white">
      <nav className="w-full p-6 flex justify-between items-center max-w-7xl mx-auto">
        <Link href="/" className="flex items-center gap-2">
          <Image src={LOGO_IMG} alt="CuteDSL" width={40} height={40} className="rounded-lg" />
          <span className="font-fredoka text-3xl font-bold text-pink-600">CuteDSL</span>
        </Link>
        <div className="flex gap-6 font-bold text-slate-700">
          <Link href="/" className="hover:text-pink-500 transition-colors flex items-center gap-1"><ArrowLeft size={16} /> Home</Link>
          <Link href="/docs" className="hover:text-purple-500 transition-colors">Docs</Link>
        </div>
      </nav>

      <main className="max-w-5xl mx-auto px-6 pb-24">
        <div className="py-10">
          <div className="flex items-center gap-3 mb-3">
            <Sparkles className="text-pink-500" size={28} />
            <h1 className="font-fredoka text-4xl lg:text-5xl font-bold text-slate-800">LoRA Trainer</h1>
          </div>
          <p className="text-lg text-slate-600 max-w-2xl">
            Fine-tune Z-Image with your own images. Drag & drop your dataset, optionally add captions, and kick off training. Cost: <b className="text-pink-600">$5</b> per job.
          </p>
        </div>

        {!isLoggedIn ? (
          <div className="bg-white rounded-2xl border border-slate-200 p-10 text-center shadow-sm">
            <Lock size={36} className="text-slate-300 mx-auto mb-3" />
            <p className="text-slate-600 mb-4">Connect your wallet on the homepage to use the LoRA trainer.</p>
            <Link href="/" className="inline-flex items-center gap-2 bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold px-6 py-2.5 rounded-full shadow-lg hover:scale-105 transition-all">
              Connect Wallet
            </Link>
          </div>
        ) : (
          <div className="space-y-8">
            {/* Dataset config */}
            <section className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
              <h2 className="text-xl font-bold text-slate-800 mb-4">1. Dataset</h2>
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-bold text-slate-700 mb-1">Dataset name *</label>
                  <input
                    type="text"
                    value={datasetName}
                    onChange={(e) => setDatasetName(e.target.value)}
                    placeholder="my-watercolor-style"
                    className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-300"
                  />
                  <p className="text-xs text-slate-400 mt-1">Lowercase letters, numbers, dashes only.</p>
                </div>
                <div>
                  <label className="block text-sm font-bold text-slate-700 mb-1">Base model</label>
                  <select
                    value={modelType}
                    onChange={(e) => setModelType(e.target.value as 'zimage' | 'chronos2')}
                    className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-300"
                  >
                    <option value="zimage">Z-Image Turbo</option>
                    <option value="chronos2">Chronos-2 (time series)</option>
                  </select>
                </div>
              </div>
            </section>

            {/* Image upload */}
            <section className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
              <h2 className="text-xl font-bold text-slate-800 mb-4">2. Training Images</h2>

              <div
                ref={dropRef}
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                onClick={() => fileInputRef.current?.click()}
                className="border-2 border-dashed border-slate-300 rounded-xl p-8 text-center cursor-pointer hover:border-pink-400 hover:bg-pink-50/30 transition-colors"
              >
                <Upload size={32} className="text-slate-400 mx-auto mb-2" />
                <p className="text-slate-600 font-medium">Drag & drop images here, or click to browse</p>
                <p className="text-xs text-slate-400 mt-1">JPG, PNG, WebP. 10–50 images recommended.</p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  multiple
                  className="hidden"
                  onChange={(e) => e.target.files && addFiles(e.target.files)}
                />
              </div>

              {items.length > 0 && (
                <div className="mt-5 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                  {items.map((it, i) => (
                    <div key={i} className="relative bg-slate-50 border border-slate-200 rounded-xl overflow-hidden">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={it.preview} alt="preview" className="w-full h-32 object-cover" />
                      {it.status === 'uploading' && (
                        <div className="absolute inset-x-0 top-0 h-1 bg-slate-200">
                          <div className="h-full bg-pink-400 transition-all" style={{ width: `${it.progress}%` }} />
                        </div>
                      )}
                      {it.status === 'done' && (
                        <div className="absolute top-2 right-2 bg-green-500 text-white rounded-full p-1"><Check size={12} /></div>
                      )}
                      {it.status === 'error' && (
                        <div className="absolute top-2 right-2 bg-red-500 text-white rounded-full p-1"><X size={12} /></div>
                      )}
                      <button
                        onClick={() => removeItem(i)}
                        className="absolute top-2 left-2 bg-white/90 hover:bg-white rounded-full p-1 shadow-sm"
                        title="Remove"
                      >
                        <X size={12} className="text-slate-600" />
                      </button>
                      <div className="p-2">
                        <input
                          type="text"
                          value={it.caption}
                          onChange={(e) => updateCaption(i, e.target.value)}
                          placeholder="caption (optional)"
                          className="w-full bg-white border border-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-pink-300"
                        />
                        {it.error && <p className="text-xs text-red-500 mt-1 truncate" title={it.error}>{it.error}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {items.length > 0 && (
                <p className="mt-3 text-sm text-slate-500">{items.length} image{items.length !== 1 ? 's' : ''} ready</p>
              )}
            </section>

            {/* Hyperparameters */}
            <section className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
              <h2 className="text-xl font-bold text-slate-800 mb-4">3. Hyperparameters</h2>
              <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div>
                  <label className="block text-sm font-bold text-slate-700 mb-1">LoRA rank (r)</label>
                  <input type="number" value={loraR} onChange={(e) => setLoraR(parseInt(e.target.value, 10) || 16)} className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-300" />
                </div>
                <div>
                  <label className="block text-sm font-bold text-slate-700 mb-1">LoRA alpha</label>
                  <input type="number" value={loraAlpha} onChange={(e) => setLoraAlpha(parseInt(e.target.value, 10) || 32)} className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-300" />
                </div>
                <div>
                  <label className="block text-sm font-bold text-slate-700 mb-1">Learning rate</label>
                  <input type="number" step="0.00001" value={learningRate} onChange={(e) => setLearningRate(parseFloat(e.target.value) || 0.0001)} className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-300" />
                </div>
                <div>
                  <label className="block text-sm font-bold text-slate-700 mb-1">Steps</label>
                  <input type="number" value={numSteps} onChange={(e) => setNumSteps(parseInt(e.target.value, 10) || 500)} className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-300" />
                </div>
              </div>
            </section>

            {/* Action */}
            <section className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
              <h2 className="text-xl font-bold text-slate-800 mb-4">4. Train</h2>
              <button
                onClick={startTraining}
                disabled={isUploading || isTraining || items.length === 0 || !datasetName.trim()}
                className="flex items-center gap-2 bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold px-7 py-3 rounded-xl shadow-lg hover:shadow-pink-300/50 hover:scale-[1.02] transition-all disabled:opacity-50 disabled:hover:scale-100"
              >
                {isUploading ? <><Loader2 size={18} className="animate-spin" /> Uploading…</> :
                 isTraining ? <><Loader2 size={18} className="animate-spin" /> Training…</> :
                 <><Play size={18} /> Start training ($5 in $CUTEDSL)</>}
              </button>

              {error && (
                <div className="mt-4 bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">{error}</div>
              )}

              {job && (
                <div className="mt-6 border-t border-slate-100 pt-6 space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="font-bold text-slate-800">Job <code className="text-xs text-slate-500">{job.job_id}</code></h3>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                      job.status === 'completed' ? 'bg-green-100 text-green-700' :
                      job.status === 'failed' ? 'bg-red-100 text-red-700' :
                      'bg-blue-100 text-blue-700'
                    }`}>{job.status}</span>
                  </div>
                  <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                    <div className="h-full bg-gradient-to-r from-pink-400 to-purple-400 transition-all" style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} />
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm text-slate-600">
                    <div><span className="text-slate-400">Model:</span> {job.model}</div>
                    {job.image_count !== undefined && <div><span className="text-slate-400">Images:</span> {job.image_count}</div>}
                    {job.loss !== undefined && <div><span className="text-slate-400">Loss:</span> {job.loss.toFixed(4)}</div>}
                    {job.output_path && <div className="col-span-2"><span className="text-slate-400">Output:</span> <code className="text-xs">{job.output_path}</code></div>}
                  </div>
                  {job.error && <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{job.error}</div>}
                  {job.note && <div className="text-xs text-slate-500">{job.note}</div>}
                </div>
              )}
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
