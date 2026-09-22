import type { Metadata } from 'next';
import { staticAssetPath } from '@/lib/static-assets';

export const metadata: Metadata = {
  title: 'Text-to-Image and Video API Docs — ra2, Z-Image, Flux, ManifoldGen',
  description:
    'CuteDSL API for ra2 art generator text-to-image, Z-Image Turbo, Flux Schnell, ManifoldGen AV1 video, Kokoro TTS, speech-to-text, Chronos-2 forecasting, LoRA training, and LTX video.',
  alternates: { canonical: 'https://cutedsl.cc/docs' },
  openGraph: {
    title: 'CuteDSL API — Text-to-Image, Video, TTS, Forecasting',
    description:
      'Z-Image Turbo, Flux Schnell, ManifoldGen AV1 video, Kokoro TTS, Chronos-2, and LTX endpoints with playgrounds.',
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
      'Z-Image Turbo, Flux Schnell, ManifoldGen AV1 video, Kokoro TTS, Chronos-2, and LTX endpoints.',
    images: [staticAssetPath('/images/og-image.webp')],
  },
};

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
