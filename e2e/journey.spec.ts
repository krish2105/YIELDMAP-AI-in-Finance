import { expect, test } from "@playwright/test";

/**
 * The journey the plan asks for, end to end:
 * city → area → compare → simulate → ask (cited) → run the crew → memo renders → export.
 *
 * Plus the properties that matter more than any single page: that a thin cell refuses to show a
 * number, that every figure carries its query, and that the advice notice is never absent.
 */

test.describe("the journey", () => {
  test("city page shows headline figures and the map", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /city/i, level: 1 })).toBeVisible();

    const tiles = page.getByTestId("kpi-tile");
    await expect(tiles.first()).toBeVisible();
    expect(await tiles.count()).toBeGreaterThan(2);

    // Either the 3D canvas or its ranked-list fallback — both are correct outcomes.
    await expect(
      page.getByTestId("city-3d").or(page.getByTestId("city-fallback")),
    ).toBeVisible();

    await expect(page.getByTestId("advice-notice").first()).toBeVisible();
  });

  test("every figure carries the query behind it", async ({ page }) => {
    await page.goto("/");
    const tile = page.getByTestId("kpi-tile").first();
    await tile.getByTestId("kpi-trace").click();

    const drawer = tile.getByTestId("kpi-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer.locator("pre code")).toContainText(/select/i);
    await expect(drawer).toContainText(/method/i);
  });

  test("a thin cell says so instead of showing a number", async ({ page }) => {
    await page.goto("/screener");
    await expect(page.getByRole("heading", { name: /screener/i, level: 1 })).toBeVisible();

    // Raising the floor to something no cell can meet must empty the table rather than
    // fabricate rows.
    await page.getByLabel("Minimum sales").fill("100000");
    await expect(page.getByText(/0 cells match/)).toBeVisible({ timeout: 20_000 });
  });

  test("an area page loads its series, risk and forecast", async ({ page }) => {
    await page.goto("/areas");
    const firstArea = page.locator("tbody tr a").first();
    const name = await firstArea.textContent();
    await firstArea.click();

    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByTestId("kpi-tile").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: /median price per square metre/i })).toBeVisible();
    expect(name?.trim().length ?? 0).toBeGreaterThan(0);
  });

  test("compare puts two communities side by side", async ({ page }) => {
    await page.goto("/compare");
    const chips = page.locator("button[aria-pressed]");
    await chips.nth(0).click();
    await chips.nth(1).click();
    await expect(page.getByRole("heading", { name: /side by side/i })).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.locator("table")).toBeVisible();
  });

  test("simulate projects cash flows and names the binding constraint", async ({ page }) => {
    await page.goto("/simulate");
    await page.getByRole("button", { name: /project the cash flows/i }).click();
    await expect(page.getByText(/levered irr/i).first()).toBeVisible({ timeout: 20_000 });

    await page.getByRole("button", { name: /what could i borrow/i }).click();
    await expect(page.getByText(/what limits it/i)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("advice-notice").first()).toBeVisible();
  });

  test("ask answers with citations", async ({ page }) => {
    await page.goto("/ask");
    await page.getByRole("button", { name: /what is a service charge/i }).click();
    await expect(page.getByRole("heading", { name: /^answer$/i })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("heading", { name: /^sources$/i })).toBeVisible();
    await expect(page.getByText(/citations on \d+% of factual sentences/)).toBeVisible();
  });

  test("the crew runs, a memo renders, and it exports", async ({ page }) => {
    await page.goto("/memos");

    // Writing a memo needs the analyst role, and the interface says so rather than failing.
    await expect(page.getByText(/needs the analyst role/i)).toBeVisible();

    await page.getByLabel("Role").selectOption("analyst");
    await page.getByLabel("Community").selectOption({ index: 1 });
    await page.getByRole("button", { name: /run the crew/i }).click();

    await expect(page.getByText(/citations/).first()).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("link", { name: /export \.md/i })).toBeVisible();

    const download = page.waitForEvent("download");
    await page.getByRole("link", { name: /export \.md/i }).click();
    expect((await download).suggestedFilename()).toMatch(/\.md$/);
  });

  test("the transparency pages load", async ({ page }) => {
    for (const path of ["/methodology", "/models", "/evals", "/data", "/security", "/report"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    }
  });
});

test.describe("things that must always hold", () => {
  test("the advice notice appears wherever a projection does", async ({ page }) => {
    for (const path of ["/", "/simulate", "/portfolio", "/rent", "/forecast"]) {
      await page.goto(path);
      await expect(
        page.getByTestId("advice-notice").first(),
        `${path} must carry the advice notice`,
      ).toBeVisible();
    }
  });

  test("generated figures are banner-flagged", async ({ page }) => {
    await page.goto("/data");
    const provenance = page.getByTestId("provenance-notice");
    const count = await provenance.count();
    if (count > 0) {
      await expect(provenance.first()).toContainText(/generated|not from the registry/i);
    }
  });

  test("arabic flips the document direction", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Language").selectOption("ar");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.locator("html")).toHaveAttribute("lang", "ar");
  });

  test("the theme toggle switches and sticks", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /switch theme/i }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", /light|dark/);
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", /light|dark/);
  });

  test("keyboard users can reach the content", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: /skip to content/i })).toBeFocused();
  });

  test("nothing scrolls sideways on a narrow viewport", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 780 });
    for (const path of ["/", "/screener", "/simulate", "/memos"]) {
      await page.goto(path);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${path} overflows horizontally by ${overflow}px`).toBeLessThanOrEqual(2);
    }
  });
});
