import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Search — CuteDSL AI Art Gallery',
  description:
    'Browse and search 100,000+ AI-generated images created with CuteDSL Z-Image Turbo. Find prompts, explore styles, and generate your own.',
  alternates: { canonical: 'https://cutedsl.app.nz/search' },
  openGraph: {
    title: 'CuteDSL AI Art Gallery — Search & Explore',
    description:
      'Browse 100,000+ AI-generated images with prompt search. Powered by CuteDSL Z-Image Turbo.',
    url: 'https://cutedsl.app.nz/search',
  },
};

export default function SearchLayout({ children }: { children: React.ReactNode }) {
  return children;
}
