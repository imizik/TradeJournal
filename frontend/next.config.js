/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // The only browser-facing service in production is the private frontend.
  // This fixed upstream is never chosen from a request URL or header.
  async rewrites() {
    const upstream = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8080";
    const url = new URL(upstream);
    if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)) {
      throw new Error("API_PROXY_TARGET must be a loopback HTTP origin");
    }
    return [{ source: "/api/backend/:path*", destination: `${url.origin}/:path*` }];
  },
};

module.exports = nextConfig;
