import type {Metadata} from 'next';
import { Fredoka, Nunito } from 'next/font/google';
import 'highlight.js/styles/github-dark.css';
import './globals.css';
import { FrontendErrorReporter } from './frontend-error-reporter';
import { STATIC_BASE_URL, staticAssetPath } from '@/lib/static-assets';

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
const thConfig = "window.__thConfig={siteId:'thw_7fwTDwXBYrLeDq4mob3NytcXhB4BqyxU'};window.th=window.th||function(){(window.th.q=window.th.q||[]).push(arguments)};";
const staticOrigin = STATIC_BASE_URL.startsWith('http') ? new URL(STATIC_BASE_URL).origin : null;

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: 'AI Image Generator API — ra2, Z-Image Turbo, Video, TTS | CuteDSL',
    template: '%s | CuteDSL',
  },
  description:
    'Create AI images with ra2 art generator and Z-Image Turbo, turn stills into video, and ship them through one fast developer API. Pay as you go by card.',
  keywords: [
    'AI image generator',
    'text to image API',
    'ra2 art generator',
    'AI art generator',
    'AI inference',
    'model acceleration',
    'Triton kernels',
    'CUDA',
    'Solana',
    'CUTEDSL',
    'image generation',
    'image to video',
    'AI video generation',
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
      { url: staticAssetPath('/images/favicon.ico'), sizes: '32x32', type: 'image/x-icon' },
      { url: staticAssetPath('/images/logo.png'), sizes: '512x512', type: 'image/png' },
    ],
    apple: staticAssetPath('/images/apple-touch-icon.png'),
  },
  openGraph: {
    type: 'website',
    locale: 'en_US',
    url: siteUrl,
    siteName: 'CuteDSL',
    title: 'AI Image Generator API — ra2, Z-Image Turbo, Video, TTS',
    description:
      'Create AI images with ra2 art generator and Z-Image Turbo, animate any still into video, and ship both through one fast developer API.',
    images: [
      {
        url: staticAssetPath('/images/og-image.webp'),
        width: 1360,
        height: 768,
        alt: 'CuteDSL AI image generator — ra2 and Z-Image Turbo',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'AI Image Generator API — ra2, Z-Image Turbo, Video',
    description:
      'Create AI images with ra2 art generator and Z-Image Turbo, turn stills into video, and pay as you go securely by card.',
    images: [staticAssetPath('/images/og-image.webp')],
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
    'AI image and video creation studio with an API: ra2 art generator (default) and Z-Image Turbo text-to-image, accelerated inference, and pay-as-you-go card billing.',
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
    description: 'Pay-as-you-go AI creation with secure Stripe card payments',
  },
  sameAs: ['https://github.com/lee101/cutedsl'],
};

export default function RootLayout({children}: {children: React.ReactNode}) {
  return (
    <html lang="en" className={`${fredoka.variable} ${nunito.variable}`}>
      <head>
        {staticOrigin && <link rel="dns-prefetch" href={staticOrigin} />}
        {staticOrigin && <link rel="preconnect" href={staticOrigin} crossOrigin="anonymous" />}
        <script dangerouslySetInnerHTML={{ __html: thConfig }} />
        <script async src="https://twohelixes.com/static/th.js" />
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
