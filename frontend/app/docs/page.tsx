'use client';

import { useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { ArrowLeft, ArrowRight, Copy, Check, Lock, Key, BookOpen } from 'lucide-react';
import { useAuth, replaceApiKey } from '@/hooks/use-auth';
import { MODELS, CATEGORY_LABELS, CATEGORY_COLORS } from '@/lib/models';

const LOGO_IMG = 'https://appstatic.app.nz/cutedsl/images/logo.webp';

export default function DocsPage() {
  const { apiKey, isLoggedIn } = useAuth();
  const [copied, setCopied] = useState(false);

  const copyKey = () => {
    if (!apiKey) return;
    navigator.clipboard.writeText(apiKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
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
          <Link href="/evals" className="hover:text-cyan-500 transition-colors">Evals</Link>
          <Link href="/blog" className="hover:text-purple-500 transition-colors">Blog</Link>
        </div>
      </nav>

      <main className="max-w-5xl mx-auto px-6 pb-24">
        {/* Hero */}
        <div className="py-12">
          <h1 className="font-fredoka text-5xl lg:text-6xl font-bold text-slate-800 mb-4">API Documentation</h1>
          <p className="text-lg text-slate-600 max-w-2xl">
            All CuteDSL services use a single unified endpoint. Authenticate with your API key, specify the service, and send your request.
          </p>
        </div>

        {/* Authentication */}
        <section className="mb-16">
          <h2 className="text-2xl font-bold text-slate-800 mb-4 flex items-center gap-2">
            <Key size={22} className="text-pink-500" /> Authentication
          </h2>
          <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
            {isLoggedIn ? (
              <div>
                <p className="text-slate-600 mb-3">Your API key:</p>
                <div className="flex items-center gap-3 bg-slate-50 rounded-xl px-4 py-3 font-mono text-sm border border-slate-200">
                  <span className="text-slate-500">Authorization: Bearer</span>
                  <span className="text-pink-600 font-bold">{apiKey}</span>
                  <button onClick={copyKey} className="ml-auto text-slate-400 hover:text-pink-500 transition-colors">
                    {copied ? <Check size={16} className="text-green-500" /> : <Copy size={16} />}
                  </button>
                </div>
                <p className="text-xs text-green-600 mt-2 flex items-center gap-1">
                  <Check size={12} /> API key auto-populated in all code examples below
                </p>
              </div>
            ) : (
              <div className="flex items-start gap-4">
                <Lock size={20} className="text-slate-400 mt-1 shrink-0" />
                <div>
                  <p className="text-slate-600 mb-2">
                    Connect your Solana wallet on the <Link href="/" className="text-pink-500 hover:text-pink-700 underline">homepage</Link> to get your API key.
                  </p>
                  <p className="text-sm text-slate-500">
                    Once connected, your real API key will automatically replace <code className="bg-slate-100 px-1 rounded text-xs">YOUR_API_KEY</code> in all code examples on this page.
                  </p>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* Base Endpoint */}
        <section className="mb-16">
          <h2 className="text-2xl font-bold text-slate-800 mb-4 flex items-center gap-2">
            <BookOpen size={22} className="text-purple-500" /> Quick Start
          </h2>
          <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
            <p className="text-slate-600 mb-4">
              All services share a single endpoint: <code className="bg-slate-100 px-2 py-0.5 rounded text-sm font-bold">POST /api/service</code>
            </p>
            <pre className="bg-slate-900 text-slate-100 rounded-xl p-5 text-sm overflow-x-auto leading-relaxed">
{replaceApiKey(`curl -X POST https://cutedsl.app.nz/api/service \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "service": "<service_name>",
    ...service-specific parameters
  }'`, apiKey)}
            </pre>
          </div>
        </section>

        {/* Response Format */}
        <section className="mb-16">
          <h2 className="text-2xl font-bold text-slate-800 mb-4">Response Format</h2>
          <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
            <p className="text-slate-600 mb-4">All responses follow this envelope:</p>
            <pre className="bg-slate-900 text-slate-100 rounded-xl p-5 text-sm overflow-x-auto leading-relaxed">
{`{
  "result": { ... },        // Service-specific response data
  "credits_used": 1000,     // $CUTEDSL tokens deducted
  "credits_remain": 49000,  // Remaining balance
  "usd_equivalent": 1.00    // USD value of credits used
}`}
            </pre>
            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
              <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                <span className="font-bold text-red-700">401</span> <span className="text-red-600">— Invalid or missing API key</span>
              </div>
              <div className="bg-orange-50 border border-orange-200 rounded-lg p-3">
                <span className="font-bold text-orange-700">402</span> <span className="text-orange-600">— Insufficient $CUTEDSL credits</span>
              </div>
            </div>
          </div>
        </section>

        {/* Model Cards */}
        <section>
          <h2 className="text-2xl font-bold text-slate-800 mb-6">Available Services</h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {MODELS.map(model => (
              <Link
                key={model.slug}
                href={`/docs/${model.slug}`}
                className="group bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:shadow-md hover:border-pink-300 transition-all"
              >
                <div className="flex items-start justify-between mb-3">
                  <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${CATEGORY_COLORS[model.category]}`}>
                    {CATEGORY_LABELS[model.category]}
                  </span>
                  {model.pricingTier === 'third-party' && (
                    <span className="text-xs text-slate-400 font-medium">via proxy</span>
                  )}
                </div>
                <h3 className="font-bold text-slate-800 text-lg mb-1 group-hover:text-pink-600 transition-colors">{model.name}</h3>
                <p className="text-sm text-slate-500 mb-3 line-clamp-2">{model.description}</p>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-400">{model.pricingNote}</span>
                  <span className="text-pink-500 group-hover:translate-x-1 transition-transform">
                    <ArrowRight size={16} />
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
