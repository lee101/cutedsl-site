import type { Metadata } from 'next';
import { staticAssetPath } from '@/lib/static-assets';

export const metadata: Metadata = {
  title: 'Blog — CuteDSL Engineering',
  description:
    'Deep dives into CuteDSL acceleration techniques: custom Triton kernels, CUDA optimizations, torch.compile, latent teleportation, vector quantization, and more.',
  alternates: { canonical: 'https://cutedsl.cc/blog' },
  openGraph: {
    title: 'CuteDSL Blog — Engineering Deep Dives',
    description:
      'Technical deep dives into AI model acceleration with custom Triton kernels, CUDA optimizations, and more.',
    url: 'https://cutedsl.cc/blog',
    images: [
      {
        url: staticAssetPath('/images/og-blog.webp'),
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
    images: [staticAssetPath('/images/og-blog.webp')],
  },
};

export default function BlogLayout({ children }: { children: React.ReactNode }) {
  return children;
}
