import Link from 'next/link';
import type { ReactNode } from 'react';

// Stopwords — kept in sync with server/prompt_pages.go:stopwords.
const STOPWORDS = new Set([
  'the', 'a', 'an', 'of', 'in', 'with', 'and', 'for', 'to', 'at', 'by', 'on',
  'as', 'is', 'are', 'was', 'be', 'has', 'from', 'that', 'this', 'it', 'its',
  'or', 'not', 'but', 'so', 'if', 'into', 'over', 'under', 'very', 'just',
  'than', 'then', 'through', 'upon', 'about', 'against', 'after', 'before',
  'between', 'while', 'style', 'art', 'image', 'photo',
]);

function slugify(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 72);
}

// linkifyPrompt splits a prompt into words and punctuation, rendering
// "significant" words (>= 3 chars, not stopwords) as /tag/<slug> links.
// Mirrors server/tag_pages.go:linkifyPrompt for visual/UX consistency.
export function linkifyPrompt(
  prompt: string,
  opts: { className?: string } = {}
): ReactNode[] {
  if (!prompt) return [];
  const cls =
    opts.className ??
    'text-pink-700 font-semibold hover:bg-pink-100 hover:text-pink-600 border-b border-dotted border-pink-300 hover:border-transparent rounded px-0.5 transition-colors';

  // Split keeping separators: groups of [A-Za-z0-9]+ vs the rest.
  const parts = prompt.split(/([A-Za-z0-9]+)/);
  const out: ReactNode[] = [];
  parts.forEach((part, i) => {
    if (!part) return;
    const isWord = /^[A-Za-z0-9]+$/.test(part);
    if (!isWord) {
      out.push(part);
      return;
    }
    const lower = part.toLowerCase();
    if (lower.length < 3 || STOPWORDS.has(lower)) {
      out.push(part);
      return;
    }
    const slug = slugify(lower);
    if (!slug) {
      out.push(part);
      return;
    }
    out.push(
      <Link
        key={`w-${i}`}
        href={`/tag/${encodeURIComponent(slug)}`}
        prefetch={false}
        rel="tag"
        className={cls}
      >
        {part}
      </Link>
    );
  });
  return out;
}
