import type { Metadata } from 'next';

const socialImage = 'https://appstatic.app.nz/cutedsl/images/og-image.webp';

export const metadata: Metadata = {
  title: 'Search — CuteDSL AI Art Gallery',
  description:
    'Browse and search 100,000+ AI-generated images created with CuteDSL Z-Image Turbo. Find prompts, explore styles, and generate your own.',
  alternates: { canonical: 'https://cutedsl.cc/search' },
  openGraph: {
    title: 'CuteDSL AI Art Gallery — Search & Explore',
    description:
      'Browse 100,000+ AI-generated images with prompt search. Powered by CuteDSL Z-Image Turbo.',
    url: 'https://cutedsl.cc/search',
    images: [{ url: socialImage, width: 1360, height: 768, alt: 'Search the CuteDSL AI art gallery' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Search the CuteDSL AI Art Gallery',
    description: 'Search 100,000+ AI-generated images by prompt, subject, and visual style.',
    images: [socialImage],
  },
};

export default function SearchLayout({ children }: { children: React.ReactNode }) {
  return children;
}
