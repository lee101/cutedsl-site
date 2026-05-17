import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'API Documentation — CuteDSL',
  description:
    'Complete API reference for CuteDSL inference services. Text-to-image, time series forecasting, TTS, STT, chat, video generation, and more.',
  alternates: { canonical: 'https://cutedsl.cc/docs' },
  openGraph: {
    title: 'CuteDSL API Documentation',
    description:
      'Complete API reference for CuteDSL inference services with interactive playgrounds.',
    url: 'https://cutedsl.cc/docs',
    images: [
      {
        url: 'https://appstatic.app.nz/cutedsl/images/og-docs.webp',
        width: 1360,
        height: 768,
        alt: 'CuteDSL API Documentation',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'CuteDSL API Documentation',
    description:
      'Complete API reference for CuteDSL inference services with interactive playgrounds.',
    images: ['https://appstatic.app.nz/cutedsl/images/og-docs.webp'],
  },
};

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
