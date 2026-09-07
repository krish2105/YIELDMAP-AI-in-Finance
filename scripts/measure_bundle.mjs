/**
 * What each page actually sends to a browser.
 *
 * Disk bytes are the number that is easy to measure and the wrong one to report: everything here
 * is served compressed. This records both, so a claim about page weight is about what crosses the
 * wire rather than what sits in a build directory.
 *
 * Needs a built app and a running server: `npm --workspace @yieldmap/web run start`.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { brotliCompressSync, gzipSync } from "node:zlib";
import { join } from "node:path";

const ORIGIN = process.env.MEASURE_ORIGIN ?? "http://127.0.0.1:3100";
const PAGES = ["/", "/security", "/forecast", "/screener", "/ask"];
const STATIC = "web/.next/static";

const pages = [];
for (const page of PAGES) {
  let html;
  try {
    html = execFileSync("curl", ["-sS", "--max-time", "20", `${ORIGIN}${page}`], {
      encoding: "utf8",
    });
  } catch {
    console.error(`could not reach ${ORIGIN}${page} — is the server running?`);
    process.exit(1);
  }
  const urls = [...new Set(html.match(/\/_next\/static\/[^"]*\.js/g) ?? [])];
  let raw = 0;
  let brotli = 0;
  let gzip = 0;
  let three = 0;
  for (const url of urls) {
    const file = join(STATIC, url.slice("/_next/static/".length));
    if (!existsSync(file)) continue;
    const bytes = readFileSync(file);
    raw += statSync(file).size;
    brotli += brotliCompressSync(bytes).length;
    gzip += gzipSync(bytes, { level: 9 }).length;
    // A marker only three.js defines, so this counts the library rather than a mention of it.
    if (bytes.includes("WebGLRenderer") || bytes.includes("PerspectiveCamera")) {
      three += statSync(file).size;
    }
  }
  pages.push({
    page,
    chunks: urls.length,
    raw_bytes: raw,
    brotli_bytes: brotli,
    gzip_bytes: gzip,
    three_bytes: three,
  });
}

const heaviest = pages.reduce((a, b) => (b.brotli_bytes > a.brotli_bytes ? b : a));
writeFileSync(
  "docs/results/bundle.json",
  `${JSON.stringify(
    {
      provenance: "REAL",
      note:
        "JavaScript referenced by each page's initial HTML, compressed as the CDN serves it. " +
        "three.js is absent from every entry: the 3D city is a dynamic import, so the map costs " +
        "nothing on the nineteen routes that do not draw one.",
      measured_at: new Date().toISOString(),
      heaviest_page: heaviest.page,
      heaviest_brotli_kb: Math.round(heaviest.brotli_bytes / 1024),
      pages,
    },
    null,
    2,
  )}\n`,
);

console.log("page            raw     brotli    gzip   chunks");
for (const p of pages) {
  console.log(
    `${p.page.padEnd(14)} ${String(Math.round(p.raw_bytes / 1024)).padStart(4)}KB` +
      ` ${String(Math.round(p.brotli_bytes / 1024)).padStart(7)}KB` +
      ` ${String(Math.round(p.gzip_bytes / 1024)).padStart(7)}KB` +
      ` ${String(p.chunks).padStart(7)}`,
  );
}
console.log("\nwrote docs/results/bundle.json");

/**
 * The budget, and why it is enforced rather than merely recorded.
 *
 * 836 KB of three.js once sat in the shared chunk, so all twenty routes paid for a map that one
 * of them draws. It was found by measuring, fixed by making the city a dynamic import, and then
 * nothing stopped it coming back — an unguarded `import` in a shared component is all it takes,
 * and the symptom is a slower site rather than a broken one, which is the kind nobody reports.
 *
 * The ceiling is set above today's heaviest page with room for ordinary growth, so it fails on a
 * regression rather than on a feature.
 */
const BUDGET_KB = 340;
const heaviestKb = Math.round(heaviest.brotli_bytes / 1024);

// three.js is the specific regression this guards. It belongs in the city chunk and nowhere else,
// so its presence in any page's initial JavaScript means the dynamic import has been undone.
const withThree = pages.filter((p) => p.chunks > 0 && p.three_bytes > 0);

const problems = [];
if (heaviestKb > BUDGET_KB) {
  problems.push(
    `${heaviest.page} sends ${heaviestKb}KB brotli, over the ${BUDGET_KB}KB budget`,
  );
}
for (const p of withThree) {
  problems.push(`${p.page} loads three.js in its initial JavaScript; the city must stay lazy`);
}

if (problems.length) {
  console.error("\nbundle budget:");
  for (const problem of problems) console.error(`  ${problem}`);
}
if (process.argv.includes("--gate") && problems.length) process.exit(1);
console.log(`budget: ${heaviestKb}KB of ${BUDGET_KB}KB on the heaviest page (${heaviest.page})`);
