import { type NextRequest, NextResponse } from "next/server";

/**
 * The proxy between the browser and the FastAPI service.
 *
 * The browser only ever calls this app's own origin, which removes cross-origin requests
 * entirely: no CORS to configure, and `connect-src 'self'` in the policy rather than a list of
 * hosts.
 *
 * It is a route handler and not a `rewrites()` entry in next.config.ts, which is the obvious way
 * to write this and does not work. Rewrite destinations are resolved during `next build` and
 * written into routes-manifest.json, so a build carries whichever API URL was in the environment
 * of the machine that built it — the same build-time freezing that makes NEXT_PUBLIC_ variables
 * the wrong tool here. `process.env` inside a handler is read per request, so one image runs
 * against a local API, a preview and production.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Where the analytics API lives, read per request.
 *
 * The fallback is the local development port on purpose. Defaulting to the deployed API would
 * mean a developer who forgets the variable silently queries production and never notices; a
 * connection refused on localhost says exactly what is wrong. In deployment the value comes from
 * vercel.json, which is the right place for it: the API's URL is configuration, not a secret.
 */
function origin(): string {
  return (process.env.API_ORIGIN ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}

// Hop-by-hop headers, and the ones that describe the browser's connection to Next rather than
// Next's connection to the API. Forwarding host or the content length of a re-encoded body makes
// the upstream request inconsistent with itself.
const STRIP = new Set([
  "host",
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "content-length",
  "accept-encoding",
]);

function forwardHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!STRIP.has(key.toLowerCase())) headers.set(key, value);
  });
  return headers;
}

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  const search = request.nextUrl.search;
  const url = `${origin()}/${path.join("/")}${search}`;

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: request.method,
      headers: forwardHeaders(request),
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      // Required by undici whenever a request carries a streamed body.
      duplex: "half",
      redirect: "manual",
      cache: "no-store",
    } as RequestInit & { duplex: "half" });
  } catch (error) {
    // A reachable front end reporting an unreachable API is more useful than a blank 500: it says
    // which of the two services is down, which is the first thing anyone needs to know.
    return NextResponse.json(
      {
        detail: "the analytics API is not reachable from the web service",
        upstream: origin(),
        error: error instanceof Error ? error.message : String(error),
      },
      { status: 502 },
    );
  }

  // The body is passed through as a stream so that Server-Sent Events from /runs/stream arrive as
  // they are produced rather than when the run finishes.
  const headers = new Headers(upstream.headers);
  headers.delete("content-encoding");
  headers.delete("content-length");
  return new Response(upstream.body, { status: upstream.status, headers });
}

type Ctx = { params: Promise<{ path: string[] }> };

async function handle(request: NextRequest, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  return proxy(request, path);
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
export const HEAD = handle;
