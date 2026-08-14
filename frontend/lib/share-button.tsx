'use client';

import { useState } from 'react';
import { Check, Share2 } from 'lucide-react';

interface ShareButtonProps {
  title: string;
  text?: string;
  url: string;
  label?: string;
  className?: string;
}

export function ShareButton({ title, text, url, label = 'Share', className = '' }: ShareButtonProps) {
  const [copied, setCopied] = useState(false);

  const share = async () => {
    const absoluteURL = new URL(url, window.location.origin).toString();
    try {
      if (navigator.share) {
        await navigator.share({ title, text, url: absoluteURL });
        return;
      }
      await navigator.clipboard.writeText(absoluteURL);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch (error) {
      if ((error as DOMException)?.name !== 'AbortError') {
        await navigator.clipboard.writeText(absoluteURL);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1800);
      }
    }
  };

  return (
    <button type="button" onClick={share} className={className} aria-label={`${label}: ${title}`}>
      {copied ? <Check size={15} className="text-green-500" /> : <Share2 size={15} />}
      {copied ? 'Link copied' : label}
    </button>
  );
}
