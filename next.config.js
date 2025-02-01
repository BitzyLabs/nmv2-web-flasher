/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'export',
  ...(process.env.NODE_ENV === 'production'
    ? {
        basePath: '/bitmaker-web-flasher',
        assetPrefix: '/bitmaker-web-flasher',
      }
    : {}),
  images: {
    unoptimized: true,
  },
};

module.exports = nextConfig;
