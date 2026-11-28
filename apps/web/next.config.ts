import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const api = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const config: NextConfig = {
  output: "standalone",
  // Monorepo: trace dependencies from the repo root so @a11y/ui is included in the standalone bundle.
  outputFileTracingRoot: fileURLToPath(new URL("../../", import.meta.url)),
  transpilePackages: ["@a11y/ui"],
  poweredByHeader: false,
  // The browser only ever talks to this origin; /api/* is proxied to FastAPI. That keeps the
  // httpOnly refresh cookie first-party (SameSite=Lax) and avoids CORS in production.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};
export default config;
