// The web app holds no business logic (plan, Phase 10): every number it shows comes
// from the Core API. The browser reaches it at the same origin through this rewrite,
// which keeps the API free of CORS and lets the service worker queue submissions to
// a path it controls. CORE_API_URL is read when the app is built.
const CORE_API_URL = process.env.CORE_API_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/core/:path*", destination: `${CORE_API_URL}/:path*` }];
  },
  async headers() {
    return [
      {
        // The service worker must be fetched fresh, or a fixed bug lives on in phones.
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(self)" },
        ],
      },
    ];
  },
};

export default nextConfig;
