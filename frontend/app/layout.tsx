import type {Metadata} from 'next';
import { Fredoka, Nunito } from 'next/font/google';
import 'highlight.js/styles/github-dark.css';
import './globals.css';
import { FrontendErrorReporter } from './frontend-error-reporter';
import { SiteCreateBar } from '@/lib/site-create-bar';
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
const staticOrigin = STATIC_BASE_URL.startsWith('http') ? new URL(STATIC_BASE_URL).origin : null;

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: 'AI Image Generator API — ra2, Z-Image Turbo, Video, TTS | CuteDSL',
    template: '%s | CuteDSL',
  },
  description:
    'Text-to-image API (ra2 art generator, Z-Image Turbo, Flux Schnell), ManifoldGen text-to-video, Kokoro TTS, speech-to-text, Chronos-2 time series forecasting, and a 100k+ AI art gallery. $CUTEDSL on Solana.',
  keywords: [
    'AI image generator',
    'text to image API',
    'ra2 art generator',
    'Z-Image Turbo',
    'Flux Schnell',
    'AI art generator',
    'Stable Diffusion API',
    'AI video generator',
    'text to video',
    'ManifoldGen',
    'text to speech',
    'Kokoro TTS',
    'speech to text',
    'time series forecasting',
    'Chronos-2',
    'AI art gallery',
    'LoRA training',
    'Solana AI',
    'CUTEDSL',
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
      'Text-to-image (ra2 art generator, Z-Image Turbo, Flux Schnell), ManifoldGen text-to-video, Kokoro TTS, Chronos-2 forecasting. 100k+ AI art gallery. $CUTEDSL on Solana.',
    images: [
      {
        url: staticAssetPath('/images/og-image.webp'),
        width: 1360,
        height: 768,
        alt: 'CuteDSL AI image generator — Z-Image Turbo',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'AI Image Generator API — Z-Image Turbo, Video, TTS',
    description:
      'Text-to-image, ManifoldGen AV1 video, Kokoro TTS, Chronos-2 forecasting. $CUTEDSL on Solana.',
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
    'AI image generator and inference API: ra2 art generator, Z-Image Turbo, Flux Schnell, Kokoro TTS, Chronos-2 forecasting. $CUTEDSL on Solana.',
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
    description: 'Text-to-image, TTS, and forecasting API paid with $CUTEDSL',
  },
  sameAs: ['https://github.com/lee101/cutedsl'],
};

export default function RootLayout({children}: {children: React.ReactNode}) {
  return (
    <html lang="en" className={`${fredoka.variable} ${nunito.variable}`}>
      <head>
        {staticOrigin && <link rel="dns-prefetch" href={staticOrigin} />}
        {staticOrigin && <link rel="preconnect" href={staticOrigin} crossOrigin="anonymous" />}
        <script
          async
          src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8598649123553748"
          crossOrigin="anonymous"
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </head>
      <body className="font-nunito antialiased bg-pink-50 text-slate-800 selection:bg-pink-300 selection:text-pink-900" suppressHydrationWarning>
        <FrontendErrorReporter />
        {children}
        <SiteCreateBar />
      </body>
    </html>
  );
}
