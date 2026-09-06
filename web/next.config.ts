import path from "node:path";

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

  // This is a workspace inside a larger repository that also holds a Python project. Without a
  // tracing root Next guesses, and it guessed the repository root, so the serverless bundle came
  // to 740MB — over Vercel's 500MB ceiling — and the deployment failed outright.
  outputFileTracingRoot: path.join(__dirname, ".."),

  outputFileTracingExcludes: {
    "/**": [
      // WebGL runs in the browser and never in a function. `@react-three/drei` is imported for a
      // single control, but the barrel drags its whole dependency graph — a video player, a
      // stats overlay, the three.js example modules — into the module graph, and the tracer
      // follows all of it.
      "node_modules/three/**",
      "node_modules/three-stdlib/**",
      "node_modules/stats-gl/**",
      "node_modules/hls.js/**",
      "node_modules/@react-three/**",
      // Build-time only.
      "node_modules/typescript/**",
      "node_modules/@typescript-eslint/**",
      "node_modules/eslint*/**",
      "node_modules/@esbuild/**",
      "node_modules/@swc/**",
      // The Python half of the repository, which the tracing root now makes reachable.
      "../.venv/**",
      "../data/**",
      "../docs/**",
      "../tests/**",
    ],
  },

  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // Content-Security-Policy is set in proxy.ts, where a per-request nonce can be
          // minted. A static header here cannot carry one, and without a nonce the policy either
          // blocks Next's own bootstrap or has to allow all inline script.
        ],
      },
    ];
  },
};

export default config;
