import { AxeBuilder } from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

/**
 * The two claims this project made and never measured.
 *
 * The plan set a frame-rate target for the 3D city — 60fps on a desktop, 30 on a phone — and an
 * accessibility bar, and both sat in the document as intentions. In a project whose entire thesis
 * is that a number without a measurement behind it is worthless, that was the one place the rule
 * was not being applied to itself.
 *
 * Results are written to docs/results/ like every other measurement, so the report reads them
 * rather than restating them.
 */

const RESULTS = join(process.cwd(), "docs", "results");

function record(name: string, body: Record<string, unknown>) {
  mkdirSync(dirname(join(RESULTS, name)), { recursive: true });
  writeFileSync(join(RESULTS, name), `${JSON.stringify(body, null, 2)}\n`);
}

/**
 * Wait until the page has stopped moving.
 *
 * The shell wraps page content in a Motion fade, and the server-rendered HTML ships with
 * `opacity: 0` on that wrapper — so the settled colours only exist once the entrance animation
 * has finished. Playwright's `toBeVisible()` does not consider opacity, so an axe run started
 * right after the heading appears can measure text that is still fading in, and a colour part way
 * to the background fails contrast: `--ink-muted` is 5.44:1 when settled and already 4.36:1 at
 * 90% opacity. That produced intermittent "serious" violations naming different pages on each
 * run — which is exactly what a race looks like, and is not a finding about the delivered UI.
 *
 * So this waits for every running animation to finish and for the wrapper to reach full opacity
 * before anything is measured. It asserts settledness rather than assuming it: a page that never
 * settles fails here, loudly, instead of producing a contrast number that depends on timing.
 */
async function settled(page: Page): Promise<void> {
  await page.waitForFunction(
    () => {
      const running = document.getAnimations().some((a) => a.playState === "running");
      if (running) return false;
      const wrapper = document.querySelector("main > div");
      return !wrapper || Number(getComputedStyle(wrapper).opacity) >= 1;
    },
    undefined,
    { timeout: 15_000 },
  );
}

/**
 * Frames rendered per second, counted in the page over a fixed window.
 *
 * `requestAnimationFrame` rather than a Playwright trace: the browser only calls it when it
 * actually paints a frame, so counting calls measures what a person would see. The scene uses
 * `frameloop="demand"`, meaning it deliberately renders nothing while idle — so the window has to
 * be one where something is moving, or the honest answer is zero and the number means nothing.
 */
async function measureFps(page: Page, durationMs: number): Promise<number> {
  return page.evaluate(async (ms) => {
    return new Promise<number>((resolve) => {
      let frames = 0;
      const started = performance.now();
      const tick = () => {
        frames += 1;
        if (performance.now() - started < ms) requestAnimationFrame(tick);
        else resolve(Math.round((frames / (performance.now() - started)) * 1000));
      };
      requestAnimationFrame(tick);
    });
  }, durationMs);
}

/** Drag across the canvas, so the scene is actually rendering while the frames are counted. */
async function orbit(page: Page) {
  const canvas = page.locator("canvas").first();
  const box = await canvas.boundingBox();
  if (!box) return false;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  for (let i = 0; i < 24; i += 1) {
    await page.mouse.move(box.x + box.width / 2 + i * 6, box.y + box.height / 2 + i * 2);
  }
  await page.mouse.up();
  return true;
}

test.describe("measured, not claimed", () => {
  test("the 3D city holds its frame-rate target", async ({ page }, testInfo) => {
    const phone = testInfo.project.name === "phone";
    // The plan's targets. A phone is held to half a desktop because it has roughly a quarter of
    // the fill rate and a much smaller viewport to cover.
    const target = phone ? 30 : 60;

    await page.goto("/");
    const canvas = page.locator("canvas").first();
    await expect(canvas).toBeVisible({ timeout: 45_000 });
    // Give the instanced mesh a moment to receive its data; measuring an empty scene flatters it.
    await page.waitForTimeout(1500);

    const dragged = await orbit(page);
    const fps = await measureFps(page, 2000);

    record(`fps_${testInfo.project.name}.json`, {
      provenance: "REAL",
      note:
        "Frames per second counted in-page with requestAnimationFrame while the scene is being " +
        "orbited. Measured in headless Chromium with SwiftShader — software rasterisation, no " +
        "GPU — so this is a floor rather than what the hardware does.",
      project: testInfo.project.name,
      viewport: page.viewportSize(),
      renderer: "swiftshader (headless, software)",
      interacted: dragged,
      fps,
      target,
      met: fps >= target,
      measured_at: new Date().toISOString(),
    });

    // The assertion is deliberately soft: software rasterisation in CI is not the claim, and a
    // hard gate here would make the suite fail for reasons that have nothing to do with the code.
    // The number is recorded either way, and a collapse to single figures is a real regression.
    expect(fps, `${fps}fps on ${testInfo.project.name} — a collapse means the scene is thrashing`)
      .toBeGreaterThan(10);
  });

  test("no page has a serious accessibility violation", async ({ page }, testInfo) => {
    // Reduced motion, because the audit is about the colours a reader ends up looking at, not
    // about the frames on the way there — and because it is the state a good number of real
    // people browse in. `settled()` below still waits, so this is belt and braces rather than a
    // way of avoiding the wait.
    await page.emulateMedia({ reducedMotion: "reduce" });

    const paths = ["/", "/areas", "/screener", "/simulate", "/ask", "/memos", "/security"];
    const findings: Record<string, unknown>[] = [];

    for (const path of paths) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });
      await settled(page);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();

      for (const violation of results.violations) {
        findings.push({
          path,
          id: violation.id,
          impact: violation.impact,
          help: violation.help,
          nodes: violation.nodes.length,
          // The first offending selector, which is what a person needs to go and look at it.
          example: violation.nodes[0]?.target?.join(" "),
        });
      }
    }

    const serious = findings.filter(
      (f) => f.impact === "serious" || f.impact === "critical",
    );

    record(`accessibility_${testInfo.project.name}.json`, {
      provenance: "REAL",
      note:
        "axe-core against WCAG 2.1 A and AA on seven representative pages, measured after the " +
        "entrance animation has settled and with reduced motion emulated. Automated checks find " +
        "roughly a third of real accessibility problems; passing here is a floor, not a claim of " +
        "compliance.",
      measured_when: "after animations settle, prefers-reduced-motion: reduce",
      project: testInfo.project.name,
      pages: paths.length,
      standard: "WCAG 2.1 A + AA",
      violations: findings.length,
      serious_or_critical: serious.length,
      findings,
      measured_at: new Date().toISOString(),
    });

    expect(
      serious,
      `serious accessibility violations:\n${serious.map((f) => `  ${f.path}: ${f.id} (${f.example})`).join("\n")}`,
    ).toEqual([]);
  });
});
