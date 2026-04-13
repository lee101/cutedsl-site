import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'AI Art Gallery — CuteDSL',
  description:
    'Explore 100,000+ AI-generated images created with CuteDSL Z-Image Turbo. Beautiful art, fantasy characters, landscapes, and more.',
  alternates: { canonical: 'https://cutedsl.app.nz/gallery' },
  openGraph: {
    title: 'CuteDSL AI Art Gallery',
    description:
      'Browse 100,000+ AI-generated images powered by CuteDSL Z-Image Turbo on Solana.',
    url: 'https://cutedsl.app.nz/gallery',
  },
};

export default function GalleryLayout({ children }: { children: React.ReactNode }) {
  return children;
}
