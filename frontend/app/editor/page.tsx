'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';
import { MediaGradeEditor } from '@/lib/media-grade-editor';

type EditorMedia = { kind: 'image' | 'video'; src: string; title: string };

export default function EditorPage() {
  return <Suspense fallback={<EditorEmpty />}><EditorFromQuery /></Suspense>;
}

function EditorFromQuery() {
  const query = useSearchParams();
  const src = query.get('src') || '';
  const kind: EditorMedia['kind'] = query.get('kind') === 'video' ? 'video' : 'image';
  const media = src ? { kind, src, title: query.get('title') || 'CuteDSL media' } : null;

  if (media) {
    return <MediaGradeEditor {...media} onClose={() => window.history.length > 1 ? window.history.back() : window.location.assign(media.kind === 'video' ? '/video-gallery' : '/gallery')} />;
  }

  return <EditorEmpty />;
}

function EditorEmpty() {
  return (
    <main className="min-h-screen bg-slate-950 text-white grid place-items-center p-6">
      <div className="text-center max-w-md">
        <h1 className="font-fredoka text-3xl font-bold mb-3">Choose media to edit</h1>
        <p className="text-slate-400 mb-6">Open an image from the gallery or a video from your generation library.</p>
        <Link href="/gallery" className="inline-flex items-center gap-2 rounded-xl bg-white text-slate-950 px-5 py-3 font-bold"><ArrowLeft size={17} /> Browse gallery</Link>
      </div>
    </main>
  );
}
