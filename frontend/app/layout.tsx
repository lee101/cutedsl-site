import type {Metadata} from 'next';
import { Fredoka, Nunito } from 'next/font/google';
import 'highlight.js/styles/github-dark.css';
import './globals.css';
import { FrontendErrorReporter } from './frontend-error-reporter';

const fredoka = Fredoka({
  subsets: ['latin'],
  variable: '--font-fredoka',
  weight: ['400', '600', '700'],
  display: 'swap',
});

const nunito = Nunito({
  subsets: ['latin'],
  variable: '--font-nunito',
  weight: ['400', '700'],
  display: 'swap',
});

const siteUrl = 'https://cutedsl.cc';
const imgBase = 'https://appstatic.app.nz/cutedsl/images';

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: 'CuteDSL — AI Model Acceleration on Solana',
    template: '%s | CuteDSL',
  },
  description:
    'Accelerate AI models with custom Triton kernels and fused pipelines. SOTA image generation, time series forecasting, TTS, and more. Powered by $CUTEDSL on Solana.',
  keywords: [
    'AI inference',
    'model acceleration',
    'Triton kernels',
    'CUDA',
    'Solana',
    'CUTEDSL',
    'image generation',
    'time series forecasting',
    'text to speech',
    'torch.compile',
    'NVFP4',
    'Z-Image',
    'Chronos-2',
  ],
  authors: [{ name: 'Applied AI NZ', url: 'https://app.nz' }],
  creator: 'Applied AI NZ',
  icons: {
    icon: [
      { url: `${imgBase}/favicon.ico`, sizes: '32x32', type: 'image/x-icon' },
      { url: `${imgBase}/logo.png`, sizes: '512x512', type: 'image/png' },
    ],
    apple: `${imgBase}/apple-touch-icon.png`,
  },
  openGraph: {
    type: 'website',
    locale: 'en_US',
    url: siteUrl,
    siteName: 'CuteDSL',
    title: 'CuteDSL — AI Model Acceleration on Solana',
    description:
      'Accelerate AI models with custom Triton kernels and fused pipelines. SOTA image generation, time series forecasting, and more. Powered by $CUTEDSL.',
    images: [
      {
        url: `${imgBase}/og-image.webp`,
        width: 1360,
        height: 768,
        alt: 'CuteDSL — AI Model Acceleration',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'CuteDSL — AI Model Acceleration on Solana',
    description:
      'Accelerate AI models with custom Triton kernels and fused pipelines. Powered by $CUTEDSL on Solana.',
    images: [`${imgBase}/og-image.webp`],
  },
  alternates: {
    canonical: siteUrl,
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-video-preview': -1,
      'max-image-preview': 'large',
      'max-snippet': -1,
    },
  },
};

const jsonLd = {
  '@context': 'https://schema.org',
  '@type': 'SoftwareApplication',
  name: 'CuteDSL',
  applicationCategory: 'DeveloperApplication',
  description:
    'AI model acceleration and inference platform using custom Triton kernels and fused pipelines. Powered by $CUTEDSL on Solana.',
  url: siteUrl,
  codeRepository: 'https://github.com/lee101/cutedsl',
  creator: {
    '@type': 'Organization',
    name: 'Applied AI NZ',
    url: 'https://app.nz',
  },
  offers: {
    '@type': 'Offer',
    priceCurrency: 'USD',
    description: 'Pay-per-use AI inference with $CUTEDSL tokens',
  },
  sameAs: ['https://github.com/lee101/cutedsl'],
};

export default function RootLayout({children}: {children: React.ReactNode}) {
  return (
    <html lang="en" className={`${fredoka.variable} ${nunito.variable}`}>
      <head>
        <link rel="dns-prefetch" href="https://appstatic.app.nz" />
        <link rel="preconnect" href="https://appstatic.app.nz" crossOrigin="anonymous" />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </head>
      <body className="font-nunito antialiased bg-pink-50 text-slate-800 selection:bg-pink-300 selection:text-pink-900" suppressHydrationWarning>
        <FrontendErrorReporter />
        {children}
      </body>
    </html>
  );
}
