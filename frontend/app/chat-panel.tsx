'use client';

import { useEffect, useState } from 'react';

type ChatModel = { id: string; label: string; price_usd: number };

export function ChatPanel({ apiKey, onNeedAccount }: { apiKey: string | null; onNeedAccount: () => void }) {
  const [models, setModels] = useState<ChatModel[]>([]);
  const [model, setModel] = useState('openpaths/auto-cheap');
  const [prompt, setPrompt] = useState('');
  const [reply, setReply] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch('/api/chat/models').then((r) => r.json()).then((d) => d?.models && setModels(d.models)).catch(() => {});
  }, []);

  const price = models.find((m) => m.id === model)?.price_usd;

  async function send() {
    if (!apiKey) return onNeedAccount();
    if (!prompt.trim()) return;
    setBusy(true);
    setStatus('');
    setReply('');
    try {
      const res = await fetch('/api/service', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({ service: 'chat_generate', model, prompt: prompt.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Request failed (${res.status})`);
      setReply(data?.result?.text || JSON.stringify(data?.result ?? data));
    } catch (err: any) {
      setStatus(err?.message || 'Chat failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section id="chat" className="mt-6 rounded-[26px] border border-slate-200 bg-white p-4 shadow-[0_22px_70px_rgba(15,23,42,.08)] sm:p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-extrabold uppercase tracking-wider text-slate-500">Chat</h2>
        <select value={model} onChange={(e) => setModel(e.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-bold text-slate-800 outline-none focus:border-pink-400">
          {models.length === 0 && <option value={model}>Auto Cheap</option>}
          {models.map((m) => (
            <option key={m.id} value={m.id}>{m.label} · ${m.price_usd.toFixed(3)}</option>
          ))}
        </select>
        {price !== undefined && <span className="text-xs font-bold text-slate-500">${price.toFixed(3)} / request</span>}
      </div>
      <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} maxLength={8000} rows={3} placeholder="Ask anything…" className="mt-3 w-full rounded-xl border border-slate-200 p-3 text-sm text-slate-800 outline-none focus:border-pink-400" />
      <button onClick={send} disabled={busy} className="mt-3 rounded-xl bg-pink-600 px-4 py-2.5 text-sm font-extrabold text-white disabled:opacity-60">{busy ? 'Thinking…' : 'Send'}</button>
      {status && <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3 text-sm font-bold text-slate-600" role="status">{status}</div>}
      {reply && <div className="mt-3 whitespace-pre-wrap rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-800">{reply}</div>}
    </section>
  );
}
