/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Suppress Object.assign() deprecation from Node http proxy internals
  serverExternalPackages: [],
  experimental: {
    // Increase proxy timeout for backend API calls (ms) to avoid ECONNRESET
    proxyTimeout: 120000,
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
