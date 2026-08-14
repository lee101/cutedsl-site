import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'My Generations — Queued AI Video Creation',
  description: 'Create durable queued AI video jobs with ManifoldGen, monitor progress, recover results, and publish selected AV1 videos.',
  alternates: { canonical: 'https://cutedsl.cc/generations' },
  robots: { index: false, follow: true },
};

export default function GenerationsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
