import type { Metadata } from 'next';

const socialImage = 'https://appstatic.app.nz/cutedsl/images/og-image.webp';

export const metadata: Metadata = {
  title: 'Evals — Benchmarks & Acceleration Research',
  description:
    'Benchmarks for CuteDSL-accelerated models, including CuteChronos2, CuteZImage fused kernels, Latent Teleportation, TurboQuant, and NVFP4.',
  alternates: { canonical: 'https://cutedsl.cc/evals' },
  openGraph: {
    title: 'CuteDSL Evals — Benchmarks & Acceleration Research',
    description:
      'Performance benchmarks for CuteChronos2 (27x speedup), CuteZImage fused Triton kernels, and more acceleration techniques.',
    url: 'https://cutedsl.cc/evals',
    images: [{ url: socialImage, width: 1360, height: 768, alt: 'CuteDSL acceleration benchmarks and evaluations' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'CuteDSL Evals — Acceleration Benchmarks',
    description: 'Performance results for CuteChronos2, CuteZImage, Triton kernels, TurboQuant, and NVFP4.',
    images: [socialImage],
  },
};

export default function EvalsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
