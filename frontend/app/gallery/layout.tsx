import type { Metadata } from 'next';

const siteUrl = 'https://cutedsl.cc';
const imgBase = 'https://appstatic.app.nz/cutedsl/images';

export const metadata: Metadata = {
  title: 'AI Art Gallery — 100,000+ Fairy, Fantasy & Anime Images',
  description:
    'Browse 100,000+ AI-generated images — fairies, fantasy characters, cute animals, anime, landscapes and more. Made with CuteDSL Z-Image Turbo on Solana. Free to view, prompt-searchable, Pinterest-style masonry.',
  keywords: [
    'AI art gallery',
    'AI generated images',
    'fairy art',
    'fantasy AI art',
    'anime AI',
    'Z-Image Turbo',
    'Stable Diffusion gallery',
    'Pinterest AI',
    'CuteDSL',
    'Solana AI',
    'prompt gallery',
    'AI inspiration',
  ],
  alternates: { canonical: `${siteUrl}/gallery` },
  openGraph: {
    type: 'website',
    url: `${siteUrl}/gallery`,
    siteName: 'CuteDSL',
    title: 'CuteDSL AI Art Gallery — 100,000+ Fairy & Fantasy Images',
    description:
      'A Pinterest-style masonry of 100,000+ AI-generated images powered by CuteDSL Z-Image Turbo. Click any image for prompt, seed, and related art.',
    images: [
      {
        url: `${imgBase}/og-image.webp`,
        width: 1360,
        height: 768,
        alt: 'CuteDSL AI Art Gallery — fairies, fantasy, anime and more',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'CuteDSL AI Art Gallery',
    description:
      '100,000+ AI-generated fairy, fantasy, and anime images — all prompt-searchable.',
    images: [`${imgBase}/og-image.webp`],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-image-preview': 'large',
      'max-snippet': -1,
    },
  },
};

const jsonLd = {
  '@context': 'https://schema.org',
  '@type': 'CollectionPage',
  name: 'CuteDSL AI Art Gallery',
  description:
    '100,000+ AI-generated images (fairy, fantasy, anime, landscapes) created with CuteDSL Z-Image Turbo. Browse prompts, seeds, and related art.',
  url: `${siteUrl}/gallery`,
  inLanguage: 'en',
  isPartOf: {
    '@type': 'WebSite',
    name: 'CuteDSL',
    url: siteUrl,
  },
  breadcrumb: {
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: siteUrl },
      { '@type': 'ListItem', position: 2, name: 'Gallery', item: `${siteUrl}/gallery` },
    ],
  },
  about: {
    '@type': 'Thing',
    name: 'AI-generated art',
  },
  creator: {
    '@type': 'Organization',
    name: 'Applied AI NZ',
    url: 'https://app.nz',
  },
};

export default function GalleryLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      {children}
    </>
  );
}
