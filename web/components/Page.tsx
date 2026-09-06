"use client";

import type { ReactNode } from "react";

export function PageHeader({
  title,
  lede,
  actions,
}: {
  title: string;
  lede?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-3xl text-ink">{title}</h1>
        {lede ? <p className="mt-1.5 max-w-2xl text-sm text-ink-secondary">{lede}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </header>
  );
}

export function Section({
  title,
  hint,
  children,
  id,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
  id?: string;
}) {
  return (
    <section id={id} className="mb-8 scroll-mt-20">
      <div className="mb-3">
        <h2 className="text-lg text-ink">{title}</h2>
        {hint ? <p className="mt-0.5 text-xs text-ink-muted">{hint}</p> : null}
      </div>
      {children}
    </section>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-line bg-raised p-4 shadow-card ${className}`}>
      {children}
    </div>
  );
}

export function Empty({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-dashed border-line px-4 py-10 text-center text-sm text-ink-muted">
      {message}
    </div>
  );
}

export function Loading({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 px-1 py-8 text-sm text-ink-muted" aria-live="polite">
      <span className="h-2 w-2 animate-pulse rounded-full bg-teal" />
      {label}…
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-line bg-sunken px-4 py-6 text-sm text-ink-secondary"
    >
      <p className="mb-2 font-medium text-ink">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="rounded border border-line px-2 py-1 text-xs hover:border-teal hover:text-teal-ink"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}
