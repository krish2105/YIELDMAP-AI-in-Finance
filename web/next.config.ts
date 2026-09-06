import type { NextConfig } from "next";

/**
 * The browser always calls this app's own origin at /api. The proxy to the FastAPI service lives
 * in app/api/[...path]/route.ts rather than in a `rewrites()` entry here, because rewrite
 * destinations are resolved during `next build` and frozen into routes-manifest.json — a build
 * would carry whichever API URL its build machine happened to have. The handler reads the
 * environment per request instead, so one build runs anywhere.
 */
const config: NextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // Content-Security-Policy is set in middleware.ts, where a per-request nonce can be
          // minted. A static header here cannot carry one, and without a nonce the policy either
          // blocks Next's own bootstrap or has to allow all inline script.
        ],
      },
    ];
  },
};

export default config;
