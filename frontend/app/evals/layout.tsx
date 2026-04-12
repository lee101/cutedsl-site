import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Evals — Benchmarks & Acceleration Research',
  description:
    'Performance benchmarks for CuteDSL-accelerated models: CuteChronos2 (27x speedup), CuteZImage fused kernels, Latent Teleportation, TurboQuant, NVFP4, and stable-diffusion.cpp.',
  alternates: { canonical: 'https://cutedsl.app.nz/evals' },
  openGraph: {
    title: 'CuteDSL Evals — Benchmarks & Acceleration Research',
    description:
      'Performance benchmarks for CuteChronos2 (27x speedup), CuteZImage fused Triton kernels, and more acceleration techniques.',
    url: 'https://cutedsl.app.nz/evals',
  },
};

export default function EvalsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
