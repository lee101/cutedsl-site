import type {Metadata} from 'next';
import { Fredoka, Nunito } from 'next/font/google';
import './globals.css'; // Global styles

const fredoka = Fredoka({
  subsets: ['latin'],
  variable: '--font-fredoka',
  weight: ['400', '500', '600', '700'],
});

const nunito = Nunito({
  subsets: ['latin'],
  variable: '--font-nunito',
  weight: ['400', '600', '700', '800'],
});

export const metadata: Metadata = {
  title: 'Cute DSL | Magical AI Model Conversion',
  description: 'Fairy-themed AI model conversion project powered by $CUTE token on Solana.',
};

export default function RootLayout({children}: {children: React.ReactNode}) {
  return (
    <html lang="en" className={`${fredoka.variable} ${nunito.variable}`}>
      <body className="font-nunito antialiased bg-pink-50 text-slate-800 selection:bg-pink-300 selection:text-pink-900" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
