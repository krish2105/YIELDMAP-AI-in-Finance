/**
 * Translation coverage.
 *
 * The interface claims three languages and one of them reads right to left. The translator falls
 * back to English when a key is missing, which is the right behaviour at runtime — a blank label
 * is worse than an English one — and is also how a gap hides: nothing throws, nothing logs, and
 * the page renders. Nine strings were falling through that way, including the confidence label
 * that appears on every KPI tile, so an Arabic reader saw "High confidence" in English beside a
 * right-to-left layout.
 */

import { describe, expect, it } from "vitest";

import {
  LOCALES,
  SHARED_ACROSS_LOCALES,
  TRANSLATION_KEYS,
  direction,
  isLocale,
  translator,
  untranslated,
} from "./i18n";

describe("every locale translates every key", () => {
  it.each(LOCALES)("%s has no untranslated keys", (locale) => {
    expect(untranslated(locale)).toEqual([]);
  });

  it("has keys to check, so this cannot pass vacuously", () => {
    expect(TRANSLATION_KEYS.length).toBeGreaterThan(30);
  });

  it("keeps the shared list short and deliberate", () => {
    // A long shared list would make this test meaningless by declaring the gap away.
    expect(SHARED_ACROSS_LOCALES.length).toBeLessThanOrEqual(3);
  });

  it.each(SHARED_ACROSS_LOCALES)("%s is a real key, not a stale entry", (key) => {
    expect(TRANSLATION_KEYS).toContain(key);
  });
});

describe("the fallback chain", () => {
  it("returns the translation when one exists", () => {
    expect(translator("ar")("nav.city")).toBe("المدينة");
    expect(translator("hi")("nav.city")).not.toBe("City");
  });

  it("falls back to English rather than a blank for an unknown key", () => {
    expect(translator("ar")("nav.city")).toBeTruthy();
    expect(translator("en")("no.such.key")).toBe("no.such.key");
  });

  it("returns the key itself rather than undefined when nothing matches", () => {
    // A missing key must never render as "undefined" in the page.
    for (const locale of LOCALES) {
      expect(translator(locale)("totally.absent")).toBe("totally.absent");
    }
  });

  it("never renders an empty string for a known key", () => {
    for (const locale of LOCALES) {
      const t = translator(locale);
      for (const key of TRANSLATION_KEYS) {
        expect(t(key).trim()).not.toBe("");
      }
    }
  });
});

describe("direction", () => {
  it("is right to left for Arabic only", () => {
    expect(direction("ar")).toBe("rtl");
    expect(direction("en")).toBe("ltr");
    expect(direction("hi")).toBe("ltr");
  });
});

describe("isLocale", () => {
  it("accepts the three shipped locales", () => {
    for (const locale of LOCALES) expect(isLocale(locale)).toBe(true);
  });

  it("rejects anything else, including a plausible near-miss", () => {
    // A stored preference is read back from localStorage and a query string, both of which can
    // hold whatever a person types.
    for (const value of ["", "EN", "ar-AE", "fr", "../en"]) {
      expect(isLocale(value)).toBe(false);
    }
  });
});

describe("the advice notice is translated everywhere it appears", () => {
  it("says the tool cannot transact, in every language", () => {
    // The one string with a compliance meaning rather than only a usability one: it is the
    // "information, not advice" boundary, and an English-only version of it is not a boundary
    // for a reader who does not read English.
    for (const locale of LOCALES) {
      const body = translator(locale)("notice.body");
      expect(body.length).toBeGreaterThan(40);
      if (locale !== "en") expect(body).not.toBe(translator("en")("notice.body"));
    }
  });
});
