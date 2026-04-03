import type {NextConfig} from 'next';

const isExport = process.env.NEXT_OUTPUT === 'export';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: false,
  },
  images: {
    ...(isExport ? { unoptimized: true } : {}),
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'picsum.photos',
        port: '',
        pathname: '/**',
      },
    ],
  },
  output: isExport ? 'export' : 'standalone',
  ...(isExport ? {} : {
    async rewrites() {
      return [
        {
          source: '/api/:path*',
          destination: 'http://localhost:8090/api/:path*',
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
