import type {NextConfig} from 'next';

const isExport = process.env.NEXT_OUTPUT === 'export';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: false,
  },
  images: {
    ...(isExport ? { unoptimized: true } : {}),
    formats: ['image/avif', 'image/webp'],
    minimumCacheTTL: 31536000,
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'appstatic.app.nz',
        port: '',
        pathname: '/cutedsl/**',
      },
    ],
  },
  output: isExport ? 'export' : 'standalone',
  compress: true,
  experimental: {
    optimizePackageImports: ['lucide-react', 'motion'],
  },
  ...(isExport ? {} : {
    async rewrites() {
      return [
        {
          source: '/api/:path*',
          destination: 'http://localhost:8090/api/:path*',
        },
      ];
    },
    async headers() {
      return [
        {
          source: '/:all*(svg|jpg|jpeg|png|webp|avif|ico|woff2)',
          headers: [
            {
              key: 'Cache-Control',
              value: 'public, max-age=31536000, immutable',
            },
          ],
        },
        {
          source: '/_next/static/:path*',
          headers: [
            {
              key: 'Cache-Control',
              value: 'public, max-age=31536000, immutable',
            },
          ],
        },
      ];
    },
  }),
  transpilePackages: ['motion'],
  webpack: (config, {dev}) => {
    if (dev && process.env.DISABLE_HMR === 'true') {
      config.watchOptions = {
        ignored: /.*/,
      };
    }
    return config;
  },
};

export default nextConfig;
