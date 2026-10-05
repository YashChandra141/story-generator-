import type { NextConfig } from "next";

// Proxy: the browser calls same-origin /api/*, Next forwards to the FastAPI
// backend at request time. BACKEND_URL may be a bare hostname (Render's
// service host) or a full URL; a scheme is added if missing. To call the
// backend directly from the browser instead (needs CORS_ORIGINS on the API),
// set NEXT_PUBLIC_API_URL in ui/lib/api.ts's env.
const raw = (process.env.BACKEND_URL || "http://127.0.0.1:8000").trim();
const backend = /^https?:\/\//i.test(raw) ? raw.replace(/\/+$/, "") : `https://${raw.replace(/\/+$/, "")}`;

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;