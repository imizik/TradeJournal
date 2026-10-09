/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Both profiles use authenticated route handlers, never arbitrary rewrites.
  poweredByHeader: false,
};

module.exports = nextConfig;
