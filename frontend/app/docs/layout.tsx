import type { Metadata } from 'next';
import { staticAssetPath } from '@/lib/static-assets';

export const metadata: Metadata = {
  title: 'Text-to-Image and Video API Docs — ra2, Z-Image, Flux',
  description:
    'Complete API reference for CuteDSL inference services. ra2 art generator (default) and Z-Image Turbo text-to-image, video generation, time series forecasting, TTS, STT, and chat.',
  alternates: { canonical: 'https://cutedsl.cc/docs' },
  openGraph: {
    title: 'CuteDSL API — Text-to-Image, Video, TTS, Forecasting',
    description:
      'ra2 art generator, Z-Image Turbo, Flux Schnell, video, Kokoro TTS, Chronos-2, and LTX endpoints with interactive playgrounds.',
    url: 'https://cutedsl.cc/docs',
    images: [
      {
        url: staticAssetPath('/images/og-image.webp'),
        width: 1360,
        height: 768,
        alt: 'CuteDSL API Documentation',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'CuteDSL API — Text-to-Image, Video, TTS, Forecasting',
    description:
      'ra2 art generator, Z-Image Turbo, Flux Schnell, video, Kokoro TTS, Chronos-2, and LTX endpoints.',
    images: [staticAssetPath('/images/og-image.webp')],
  },
};

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
