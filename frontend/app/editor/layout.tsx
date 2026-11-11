import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Media Colour Editor | CuteDSL',
  description: 'Grade and export CuteDSL images and videos in your browser.',
  robots: { index: false, follow: false },
};

export default function EditorLayout({ children }: { children: React.ReactNode }) {
  return children;
}
