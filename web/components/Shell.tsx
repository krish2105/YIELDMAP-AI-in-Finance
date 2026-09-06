"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

import { LOCALES, LOCALE_NAMES } from "@/lib/i18n";
import type { Role } from "@/lib/api";
import { useShell } from "./Providers";

/** The twenty tabs, grouped so the rail stays readable. */
export const SECTIONS: { group: string; items: { href: string; key: string }[] }[] = [
  {
    group: "Market",
    items: [
      { href: "/", key: "nav.city" },
      { href: "/areas", key: "nav.areas" },
      { href: "/compare", key: "nav.compare" },
      { href: "/screener", key: "nav.screener" },
    ],
  },
  {
    group: "Money",
    items: [
      { href: "/simulate", key: "nav.simulate" },
      { href: "/portfolio", key: "nav.portfolio" },
      { href: "/rent", key: "nav.rent" },
      { href: "/forecast", key: "nav.forecast" },
    ],
  },
  {
    group: "Signals",
    items: [
      { href: "/signals", key: "nav.signals" },
      { href: "/developers", key: "nav.developers" },
    ],
  },
  {
    group: "Intelligence",
    items: [
      { href: "/ask", key: "nav.ask" },
      { href: "/memos", key: "nav.memos" },
      { href: "/crew", key: "nav.crew" },
    ],
  },
  {
    group: "How it works",
    items: [
      { href: "/models", key: "nav.models" },
      { href: "/evals", key: "nav.evals" },
      { href: "/methodology", key: "nav.methodology" },
      { href: "/data", key: "nav.data" },
      { href: "/security", key: "nav.security" },
      { href: "/report", key: "nav.report" },
    ],
  },
];

const ALL_ITEMS = SECTIONS.flatMap((section) =>
  section.items.map((item) => ({ ...item, group: section.group })),
);

function CommandPalette({ onClose }: { onClose: () => void }) {
  const { t } = useShell();
  const [query, setQuery] = useState("");
  const matches = ALL_ITEMS.filter((item) =>
    t(item.key).toLowerCase().includes(query.trim().toLowerCase()),
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh] backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <motion.div
        initial={{ opacity: 0, y: -8, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
        className="w-full max-w-lg overflow-hidden rounded-xl border border-line bg-raised shadow-card"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t("common.search")}
      >
        <input
          autoFocus
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("common.search")}
          className="w-full border-b border-line bg-transparent px-4 py-3 text-base text-ink outline-none placeholder:text-ink-muted"
        />
        <ul className="max-h-80 overflow-auto py-1">
          {matches.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                onClick={onClose}
                className="flex items-center justify-between px-4 py-2 text-sm text-ink-secondary hover:bg-sunken hover:text-ink"
              >
                <span>{t(item.key)}</span>
                <span className="text-xs text-ink-muted">{item.group}</span>
              </Link>
            </li>
          ))}
          {matches.length === 0 ? (
            <li className="px-4 py-6 text-center text-sm text-ink-muted">{t("common.none")}</li>
          ) : null}
        </ul>
      </motion.div>
    </div>
  );
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const { t, locale, setLocale, theme, setTheme, role, setRole } = useShell();
  const pathname = usePathname();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const reduce = useReducedMotion();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
      if (event.key === "Escape") setPaletteOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => setNavOpen(false), [pathname]);

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15rem_1fr]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-raised focus:px-3 focus:py-2"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-raised/90 px-4 py-3 backdrop-blur lg:hidden">
        <button
          type="button"
          onClick={() => setNavOpen((open) => !open)}
          aria-expanded={navOpen}
          aria-label="Menu"
          className="rounded border border-line px-2 py-1 text-sm"
        >
          ☰
        </button>
        <Link href="/" className="font-display text-lg tracking-tight">
          {t("app.name")}
        </Link>
      </header>

      <nav
        className={`${navOpen ? "block" : "hidden"} border-b border-line bg-raised px-4 py-4 lg:sticky lg:top-0 lg:block lg:h-dvh lg:overflow-y-auto lg:border-b-0 lg:border-e lg:py-6`}
        aria-label="Sections"
      >
        <Link href="/" className="hidden lg:block">
          <span className="font-display text-xl tracking-tight text-ink">{t("app.name")}</span>
          <span className="mt-0.5 block text-xs text-ink-muted">{t("app.tagline")}</span>
        </Link>

        <div className="mt-0 space-y-5 lg:mt-7">
          {SECTIONS.map((section) => (
            <div key={section.group}>
              <p className="mb-1.5 px-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                {section.group}
              </p>
              <ul className="space-y-0.5">
                {section.items.map((item) => {
                  const active =
                    item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        // On a phone the nav is a disclosure, and following a link inside it left
                        // it open: the page you asked for rendered below a full screen of menu.
                        onClick={() => setNavOpen(false)}
                        aria-current={active ? "page" : undefined}
                        className={`block rounded-lg px-2 py-1.5 text-sm transition-colors ${
                          active
                            ? "bg-sunken font-medium text-ink"
                            : "text-ink-secondary hover:bg-sunken hover:text-ink"
                        }`}
                      >
                        {t(item.key)}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-7 space-y-3 border-t border-line pt-4 text-xs">
          <label className="block">
            <span className="mb-1 block text-ink-muted">{t("role.label")}</span>
            <select
              value={role}
              onChange={(event) => setRole(event.target.value as Role)}
              className="w-full rounded border border-line bg-bg px-2 py-1 text-ink"
            >
              <option value="viewer">Viewer</option>
              <option value="analyst">Analyst</option>
              <option value="admin">Admin</option>
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-ink-muted">Language</span>
            <select
              value={locale}
              onChange={(event) => setLocale(event.target.value as (typeof LOCALES)[number])}
              className="w-full rounded border border-line bg-bg px-2 py-1 text-ink"
            >
              {LOCALES.map((code) => (
                <option key={code} value={code}>
                  {LOCALE_NAMES[code]}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="w-full rounded border border-line px-2 py-1 text-ink-secondary hover:border-teal hover:text-teal-ink"
          >
            {t("theme.toggle")}
          </button>

          <p className="pt-1 text-[11px] text-ink-muted">
            Press <kbd className="rounded border border-line px-1">⌘K</kbd> to search
          </p>
        </div>
      </nav>

      <main id="main" className="min-w-0 px-4 py-6 lg:px-8 lg:py-10">
        {reduce ? (
          children
        ) : (
          <motion.div
            key={pathname}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          >
            {children}
          </motion.div>
        )}
      </main>

      <AnimatePresence>
        {paletteOpen ? <CommandPalette onClose={() => setPaletteOpen(false)} /> : null}
      </AnimatePresence>
    </div>
  );
}
