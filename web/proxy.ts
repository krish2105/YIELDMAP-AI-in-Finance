import { type NextRequest, NextResponse } from "next/server";

/**
 * Content-Security-Policy with a per-request nonce.
 *
 * This is Next 16's `proxy` convention, which replaces `middleware`. The old name still works
 * and prints a deprecation warning on every build.
 *
 * Next.js emits a small inline script to hand hydration data to the client. A policy of
 * `script-src 'self'` blocks it, and the whole application silently degrades to static HTML — the
 * navigation renders, nothing is interactive, and no error reaches the user. The lazy fix is
 * `'unsafe-inline'`, which switches off the protection that makes the header worth having.
 *
 * A nonce is the right answer: Next reads it from this header and stamps it onto its own scripts,
 * so exactly those execute and an injected one does not. The cost is that pages become
 * dynamically rendered, which is a fair price for a policy that actually holds.
 */
export default function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");

  const csp = [
    "default-src 'self'",
    // 'self' for the framework's own chunk files, the nonce for its inline bootstrap. Deliberately
    // no 'strict-dynamic': it makes a browser ignore 'self' entirely, which blocks every chunk
    // Next emits as a plain script tag. What is left still refuses any inline script without the
    // nonce and any script from another origin, which is the protection worth having.
    `script-src 'self' 'nonce-${nonce}' 'unsafe-eval'`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "worker-src 'self' blob:",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ");

  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  // Next reads the nonce off the *request's* CSP header to stamp its own inline bootstrap.
  // Setting it only on the response leaves those scripts unnonced, and they are then refused by
  // the very policy this function just wrote.
  headers.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    // Everything except static assets and the API proxy, which the FastAPI service secures itself.
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
