import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Blog — CuteDSL Engineering',
  description:
    'Deep dives into CuteDSL acceleration techniques: custom Triton kernels, CUDA optimizations, torch.compile, latent teleportation, vector quantization, and more.',
  alternates: { canonical: 'https://cutedsl.app.nz/blog' },
  openGraph: {
    title: 'CuteDSL Blog — Engineering Deep Dives',
    description:
      'Technical deep dives into AI model acceleration with custom Triton kernels, CUDA optimizations, and more.',
    url: 'https://cutedsl.app.nz/blog',
    images: [
      {
        url: 'https://appstatic.app.nz/cutedsl/images/og-blog.webp',
        width: 1360,
        height: 768,
        alt: 'CuteDSL Blog — Engineering Deep Dives',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'CuteDSL Blog — Engineering Deep Dives',
    description:
      'Technical deep dives into AI model acceleration with custom Triton kernels, CUDA optimizations, and more.',
    images: ['https://appstatic.app.nz/cutedsl/images/og-blog.webp'],
  },
};

export default function BlogLayout({ children }: { children: React.ReactNode }) {
  return children;
}
