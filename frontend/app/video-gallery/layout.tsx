import type { Metadata } from 'next';

const socialImage = 'https://appstatic.app.nz/cutedsl/images/og-image.webp';

export const metadata: Metadata = {
  title: 'AI Video Gallery — AV1 Generations',
  description: 'Watch and share selected AI-generated videos created through CuteDSL and ManifoldGen, with efficient AV1 source assets.',
  alternates: { canonical: 'https://cutedsl.cc/video-gallery' },
  openGraph: { title: 'CuteDSL AI Video Gallery', description: 'Selected AI videos generated with ManifoldGen.', url: 'https://cutedsl.cc/video-gallery', images: [socialImage] },
  twitter: { card: 'summary_large_image', title: 'CuteDSL AI Video Gallery', description: 'Selected AI-generated AV1 videos.', images: [socialImage] },
};

export default function VideoGalleryLayout({ children }: { children: React.ReactNode }) {
  return children;
}
