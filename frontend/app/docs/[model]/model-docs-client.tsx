'use client';

import { useState, useRef } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { ArrowLeft, Copy, Check, Play, Loader2, Download, ChevronRight, Lock } from 'lucide-react';
import { useAuth, replaceApiKey } from '@/hooks/use-auth';
import { MODEL_MAP, CATEGORY_LABELS, CATEGORY_COLORS, type ModelConfig, type ModelParam } from '@/lib/models';

const API_BASE = '/api';
const LOGO_IMG = 'https://appstatic.app.nz/cutedsl/images/logo.webp';

function ParamInput({ param, value, onChange }: { param: ModelParam; value: string; onChange: (v: string) => void }) {
  if (param.options) {
    return (
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-300"
      >
        <option value="">Select...</option>
        {param.options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  }

  if (param.type === 'string' && (param.name === 'prompt' || param.name === 'text')) {
    return (
      <textarea
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={param.placeholder || ''}
        rows={3}
        className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-300 resize-y"
      />
    );
  }

  if (['float[]', 'float[][]', 'object[]', 'string[]'].includes(param.type)) {
    return (
      <textarea
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={param.placeholder || `JSON ${param.type}`}
        rows={3}
        className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-pink-300 resize-y"
      />
    );
  }

  return (
    <input
      type={param.type === 'string' ? 'text' : 'number'}
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={param.placeholder || (param.default !== undefined ? String(param.default) : '')}
      step={param.type === 'float' ? '0.1' : '1'}
      className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-300"
    />
  );
}

function ResponseRenderer({ config, result }: { config: ModelConfig; result: Record<string, unknown> }) {
  if (config.responseType === 'image') {
    const base64 = result.image_base64 as string | undefined;
    const url = result.image_url as string | undefined;
    const src = base64 ? `data:image/webp;base64,${base64}` : url;
    if (!src) return <pre className="text-sm text-slate-300 overflow-x-auto">{JSON.stringify(result, null, 2)}</pre>;
    return (
      <div className="space-y-3">
        <img src={src} alt="Generated" className="rounded-xl max-w-full shadow-lg" />
        <a href={src} download="generated.webp" className="inline-flex items-center gap-1 text-sm text-pink-500 hover:text-pink-700">
          <Download size={14} /> Download
        </a>
      </div>
    );
  }

  if (config.responseType === 'audio') {
    const base64 = result.audio_base64 as string | undefined;
    const url = result.audio_url as string | undefined;
    const src = base64 ? `data:audio/wav;base64,${base64}` : url;
    if (!src) return <pre className="text-sm text-slate-300 overflow-x-auto">{JSON.stringify(result, null, 2)}</pre>;
    return (
      <div className="space-y-3">
        <audio controls src={src} className="w-full" />
        <a href={src} download="audio.wav" className="inline-flex items-center gap-1 text-sm text-pink-500 hover:text-pink-700">
          <Download size={14} /> Download
        </a>
      </div>
    );
  }

  if (config.responseType === 'video') {
    const url = result.video_url as string | undefined;
    if (!url) return <pre className="text-sm text-slate-300 overflow-x-auto">{JSON.stringify(result, null, 2)}</pre>;
    return (
      <div className="space-y-3">
        <video controls src={url} className="rounded-xl max-w-full shadow-lg" />
        <a href={url} download className="inline-flex items-center gap-1 text-sm text-pink-500 hover:text-pink-700">
          <Download size={14} /> Download
        </a>
      </div>
    );
  }

  return <pre className="text-sm text-slate-300 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(result, null, 2)}</pre>;
}

export default function ModelDocsClient({ slug }: { slug: string }) {
  const config = MODEL_MAP[slug];
  const { apiKey, isLoggedIn } = useAuth();
  const [copiedCurl, setCopiedCurl] = useState(false);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  if (!config) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-slate-800 mb-2">Model not found</h1>
          <Link href="/docs" className="text-pink-500 hover:text-pink-700 underline">Back to docs</Link>
        </div>
      </div>
    );
  }

  const copyCurl = () => {
    navigator.clipboard.writeText(replaceApiKey(config.curlExample, apiKey));
    setCopiedCurl(true);
    setTimeout(() => setCopiedCurl(false), 2000);
  };

  const setField = (name: string, value: string) => {
    setFormValues(prev => ({ ...prev, [name]: value }));
  };

  const buildPayload = () => {
    const payload: Record<string, unknown> = { service: config.slug };
    for (const param of config.params) {
      const raw = formValues[param.name];
      if (!raw && raw !== '0') {
        if (param.required) throw new Error(`${param.name} is required`);
        continue;
      }
      if (param.type === 'int') {
        payload[param.name] = parseInt(raw, 10);
      } else if (param.type === 'float') {
        payload[param.name] = parseFloat(raw);
      } else if (['float[]', 'float[][]', 'object[]', 'string[]'].includes(param.type)) {
        payload[param.name] = JSON.parse(raw);
      } else {
        payload[param.name] = raw;
      }
    }
    return payload;
  };

  const runPlayground = async () => {
    setError(null);
    setResponse(null);
    setLoading(true);
    try {
      const payload = buildPayload();
      const res = await fetch(`${API_BASE}/service`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`,
        },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || `Request failed (${res.status})`);
      } else {
        setResponse(data);
        setTimeout(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 100);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed');
    } finally {
      setLoading(false);
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
          <Link href="/evals" className="hover:text-cyan-500 transition-colors">Evals</Link>
        </div>
      </nav>

      <main className="max-w-5xl mx-auto px-6 pb-24">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-slate-400 mb-6">
          <Link href="/docs" className="hover:text-pink-500 transition-colors">Docs</Link>
          <ChevronRight size={14} />
          <span className="text-slate-700 font-medium">{config.name}</span>
        </div>

        {/* Header */}
        <div className="mb-10">
          <div className="flex items-center gap-3 mb-3">
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${CATEGORY_COLORS[config.category]}`}>
              {CATEGORY_LABELS[config.category]}
            </span>
            {config.pricingTier === 'third-party' && (
              <span className="text-xs font-medium text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">third-party proxy</span>
            )}
          </div>
          <h1 className="font-fredoka text-4xl lg:text-5xl font-bold text-slate-800 mb-3">{config.name}</h1>
          <p className="text-lg text-slate-600 max-w-2xl">{config.description}</p>
          <p className="mt-2 text-sm font-bold text-pink-600">{config.pricingNote}</p>
        </div>

        {/* Parameters Table */}
        <section className="mb-12">
          <h2 className="text-xl font-bold text-slate-800 mb-4">Parameters</h2>
          <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200">
                    <th className="text-left px-5 py-3 font-bold text-slate-600">Parameter</th>
                    <th className="text-left px-5 py-3 font-bold text-slate-600">Type</th>
                    <th className="text-left px-5 py-3 font-bold text-slate-600">Required</th>
                    <th className="text-left px-5 py-3 font-bold text-slate-600">Default</th>
                    <th className="text-left px-5 py-3 font-bold text-slate-600">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {config.params.map((param, i) => (
                    <tr key={param.name} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50/50'}>
                      <td className="px-5 py-3 font-mono text-pink-600 font-bold">{param.name}</td>
                      <td className="px-5 py-3 text-slate-500">{param.type}</td>
                      <td className="px-5 py-3">
                        {param.required ? (
                          <span className="text-red-500 font-bold text-xs">required</span>
                        ) : (
                          <span className="text-slate-400 text-xs">optional</span>
                        )}
                      </td>
                      <td className="px-5 py-3 font-mono text-xs text-slate-500">
                        {param.default !== undefined ? String(param.default) : '\u2014'}
                      </td>
                      <td className="px-5 py-3 text-slate-600">
                        {param.description}
                        {param.options && (
                          <span className="block text-xs text-slate-400 mt-1">
                            Options: {param.options.join(', ')}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* Code Example */}
        <section className="mb-12">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold text-slate-800">Example Request</h2>
            <button onClick={copyCurl} className="flex items-center gap-1 text-sm text-slate-400 hover:text-pink-500 transition-colors">
              {copiedCurl ? <><Check size={14} className="text-green-500" /> Copied</> : <><Copy size={14} /> Copy</>}
            </button>
          </div>
          <pre className="bg-slate-900 text-slate-100 rounded-2xl p-6 text-sm overflow-x-auto leading-relaxed shadow-sm">
            {replaceApiKey(config.curlExample, apiKey)}
          </pre>
          {isLoggedIn && (
            <p className="text-xs text-green-600 mt-2 flex items-center gap-1">
              <Check size={12} /> Using your real API key
            </p>
          )}
        </section>

        {/* Example Response */}
        <section className="mb-12">
          <h2 className="text-xl font-bold text-slate-800 mb-4">Example Response</h2>
          <pre className="bg-slate-900 text-slate-100 rounded-2xl p-6 text-sm overflow-x-auto leading-relaxed shadow-sm">
            {JSON.stringify(config.responseExample, null, 2)}
          </pre>
        </section>

        {/* Playground */}
        <section className="mb-12">
          <h2 className="text-xl font-bold text-slate-800 mb-4 flex items-center gap-2">
            <Play size={20} className="text-pink-500" /> Playground
          </h2>

          {!isLoggedIn ? (
            <div className="bg-white rounded-2xl border border-slate-200 p-8 text-center shadow-sm">
              <Lock size={32} className="text-slate-300 mx-auto mb-3" />
              <p className="text-slate-600 mb-3">Connect your wallet to try the playground.</p>
              <Link href="/" className="inline-flex items-center gap-2 bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold px-6 py-2 rounded-full shadow-lg hover:shadow-pink-300/50 hover:scale-105 transition-all">
                Connect Wallet
              </Link>
            </div>
          ) : (
            <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
              <div className="grid gap-4 mb-6">
                {config.params.map(param => (
                  <div key={param.name}>
                    <label className="block text-sm font-bold text-slate-700 mb-1">
                      {param.name}
                      {param.required && <span className="text-red-400 ml-1">*</span>}
                      {param.default !== undefined && (
                        <span className="text-slate-400 font-normal ml-2">default: {String(param.default)}</span>
                      )}
                    </label>
                    <ParamInput
                      param={param}
                      value={formValues[param.name] || ''}
                      onChange={v => setField(param.name, v)}
                    />
                  </div>
                ))}
              </div>

              <button
                onClick={runPlayground}
                disabled={loading}
                className="flex items-center gap-2 bg-gradient-to-r from-pink-400 to-purple-400 text-white font-bold px-6 py-3 rounded-xl shadow-lg hover:shadow-pink-300/50 hover:scale-[1.02] transition-all disabled:opacity-50 disabled:hover:scale-100"
              >
                {loading ? <><Loader2 size={18} className="animate-spin" /> Running...</> : <><Play size={18} /> Run</>}
              </button>

              {/* Error */}
              {error && (
                <div className="mt-4 bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
                  {error}
                </div>
              )}

              {/* Response */}
              {response && (
                <div ref={resultRef} className="mt-6 border-t border-slate-100 pt-6">
                  <h3 className="font-bold text-slate-800 mb-3">Result</h3>

                  {/* Render service result */}
                  <div className="bg-slate-900 rounded-xl p-5 mb-4">
                    <ResponseRenderer config={config} result={response.result as Record<string, unknown>} />
                  </div>

                  {/* Credits info */}
                  <div className="flex gap-4 text-sm">
                    <div className="bg-pink-50 border border-pink-200 rounded-lg px-3 py-2">
                      <span className="text-pink-600 font-bold">{String(response.credits_used)}</span>
                      <span className="text-pink-500 ml-1">credits used</span>
                    </div>
                    <div className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
                      <span className="text-slate-700 font-bold">{String(response.credits_remain)}</span>
                      <span className="text-slate-500 ml-1">remaining</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        {/* Back to docs */}
        <div className="text-center">
          <Link href="/docs" className="text-pink-500 hover:text-pink-700 font-bold flex items-center gap-1 justify-center">
            <ArrowLeft size={16} /> Back to all services
          </Link>
        </div>
      </main>
    </div>
  );
}
