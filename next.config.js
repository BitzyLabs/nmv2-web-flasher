/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'export',
  ...(process.env.NODE_ENV === 'production'
    ? {
        basePath: '/bitronics-web-flasher',
        assetPrefix: '/bitronics-web-flasher',
      }
    : {}),
  images: {
    unoptimized: true,
  },
};

module.exports = nextConfig;
