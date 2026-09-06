import type { Metadata, Viewport } from "next";
import { Archivo, IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

import { SpeedInsights } from "@vercel/speed-insights/next";

import Providers from "@/components/Providers";
import Shell from "@/components/Shell";
import "./globals.css";

const archivo = Archivo({ subsets: ["latin"], variable: "--font-archivo", display: "swap" });
const plex = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex",
  display: "swap",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "YIELDMAP", template: "%s · YIELDMAP" },
  description:
    "Dubai property investment intelligence from published Land Department data. Information, not advice.",
  robots: { index: false },
};

/**
 * Rendered per request, deliberately.
 *
 * The Content-Security-Policy in `middleware.ts` carries a per-request nonce, and Next stamps that
 * nonce onto its own inline bootstrap script by reading the CSP header off the incoming request.
 * A statically prerendered page has no incoming request at the moment its HTML is written, so the
 * script goes out unnonced and the browser refuses it: the app ships as inert static markup with
 * no hydration, no interactivity and no error the user can see.
 *
 * Every route here reads live data from the API on the client, so prerendering was only ever
 * producing an empty shell. Giving that shell up buys a policy that actually holds.
 */
export const dynamic = "force-dynamic";

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f1ea" },
    { media: "(prefers-color-scheme: dark)", color: "#131316" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr" className={`${archivo.variable} ${plex.variable} ${plexMono.variable}`}>
      <body>
        <Providers>
          <Shell>{children}</Shell>
        </Providers>
        {/*
          Core Web Vitals from real devices on real networks. The frame rate and bundle figures in
          docs/results/ are measured in headless Chromium on a CI runner, which is a floor and not
          an experience — this is the only way to learn what the site is actually like to use on a
          phone in Dubai.

          Speed Insights only. Vercel Analytics was installed and removed: it counts visitors, and
          this project's posture is that it holds no personal data. A pageview total is not worth
          giving that up.
        */}
        <SpeedInsights />
      </body>
    </html>
  );
}
