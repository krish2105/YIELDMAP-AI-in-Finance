import { expect, test } from "@playwright/test";

/**
 * What a person sees when the API is not there.
 *
 * This is not a hypothetical. The API runs on Render's free tier, which sleeps after fifteen
 * minutes idle and takes about fifty seconds to wake, so the first visitor after a quiet period
 * meets a service that is not answering. Sixteen of the nineteen routes had an error state
 * written for exactly that, and nothing exercised any of them — which is how the crew page came
 * to render an empty card on failure instead of saying anything at all.
 *
 * Every route here is loaded with the API refusing, and each must say something. The bar is
 * deliberately low and absolute: never a blank region, never an unhandled crash, never a spinner
 * that spins forever. A page that cannot get data should say so and offer to try again.
 */

/**
 * Routes that fetch as soon as they load. With the API down each must say so.
 */
const LOADS_DATA = [
  "/",
  "/areas",
  "/screener",
  "/forecast",
  "/signals",
  "/developers",
  "/models",
  "/evals",
  "/data",
  "/crew",
];

/**
 * Routes whose first screen is a form. These request nothing until someone submits, so with the
 * API down they correctly show no error at all — there has been no failure yet. Holding them to
 * the same bar as the pages above would be demanding they invent one.
 */
const FORM_FIRST = ["/compare", "/simulate", "/portfolio", "/rent", "/ask", "/memos"];

/** Fail every API call the page makes, the way an unreachable origin does. */
async function apiIsDown(page: import("@playwright/test").Page) {
  await page.route("**/api/**", (route) => route.abort("connectionrefused"));
}

test.describe("when the API is unreachable", () => {
  test.beforeEach(async ({ page }) => {
    await apiIsDown(page);
  });

  for (const path of LOADS_DATA) {
    test(`${path} says so rather than showing nothing`, async ({ page }) => {
      const crashes: string[] = [];
      page.on("pageerror", (error) => crashes.push(error.message));

      await page.goto(path);

      // The shell is server-rendered and survives regardless: the heading stays, so someone
      // looking at the error can tell which page produced it. Five routes used to return only an
      // error box, leaving the document with no h1 at all.
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });

      // Specifically the error state, not "any alert". The provenance banner also carries
      // role="alert" and is present on a healthy page, so asserting on the role matched every
      // route whether or not it had handled the failure — the first version of this test passed
      // everywhere and was measuring nothing.
      await expect(page.getByTestId("error-state").first()).toBeVisible({ timeout: 30_000 });

      expect(crashes, `${path} threw: ${crashes.join("; ")}`).toEqual([]);
    });
  }

  for (const path of FORM_FIRST) {
    test(`${path} still renders its form`, async ({ page }) => {
      const crashes: string[] = [];
      page.on("pageerror", (error) => crashes.push(error.message));

      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });

      // Nothing has been asked for, so nothing has failed. What matters is that the page is
      // usable rather than blank, and that it has not invented an error.
      await expect(page.getByTestId("error-state")).toHaveCount(0);
      expect(crashes, `${path} threw: ${crashes.join("; ")}`).toEqual([]);
    });
  }

  test("asking a question with no API surfaces the failure rather than hanging", async ({
    page,
  }) => {
    // The form-first pages owe an error once someone actually submits. A spinner that never
    // resolves is the worst of the three outcomes: it looks like progress.
    await page.goto("/ask");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });

    await page.getByRole("textbox").first().fill("What is the transfer fee?");
    await page.getByRole("button", { name: /ask/i }).first().click();

    await expect(page.getByTestId("error-state").first()).toBeVisible({ timeout: 30_000 });
  });

  test("the advice notice still appears, because it is not data", async ({ page }) => {
    // The "information, not advice" boundary must not depend on a network call succeeding.
    await page.goto("/simulate");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/not advice/i).first()).toBeVisible();
  });

  test("retrying recovers once the API answers again", async ({ page }) => {
    // The button is the whole point of the error state, and one that does not refetch is worse
    // than no button: it tells someone the problem is theirs to retry when it is not.
    await page.goto("/");
    await expect(page.getByTestId("error-state").first()).toBeVisible({ timeout: 30_000 });

    await page.unroute("**/api/**");

    // The landing page runs two independent queries and each error state retries only its own,
    // which is the right design — one failing panel should not refetch the whole page — but it
    // means recovery takes a click per panel.
    const retries = page.getByRole("button", { name: /try again/i });
    for (let i = await retries.count(); i > 0; i = await retries.count()) {
      await retries.first().click();
      await expect(retries).toHaveCount(i - 1, { timeout: 30_000 });
    }

    await expect(page.getByTestId("kpi-tile").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("error-state")).toHaveCount(0);
  });
});

test.describe("when the API is slow rather than absent", () => {
  test("a cold start shows a loading state, not an error", async ({ page }) => {
    // Render's free tier takes about fifty seconds to wake. Treating slow as failed would show
    // an error to everyone who arrives first after a quiet period.
    await page.route("**/api/market**", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.continue();
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });
    // The tiles arrive late but they arrive. A slow response must not be reported as a failure.
    await expect(page.getByTestId("kpi-tile").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("error-state")).toHaveCount(0);
  });
});
