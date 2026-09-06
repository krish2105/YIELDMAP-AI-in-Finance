"use client";

import { type FormEvent, useState } from "react";

import { useShell } from "@/components/Providers";
import { ApiError } from "@/lib/api";

/**
 * Signing in, where the role selector used to be.
 *
 * That selector was the whole access-control system: it wrote a role to localStorage, the client
 * sent it as a header, and the API believed it. Choosing "Analyst" from a dropdown genuinely
 * granted the analyst role — to anyone, including a stranger with curl who never loaded the page.
 *
 * What replaces it cannot be operated from the browser at all: the role is a claim inside a token
 * the API signs, so the interface can only ask, and the answer is the API's.
 */
export default function SignIn() {
  const { role, authenticated, signIn, signOut } = useShell();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
      setOpen(false);
      setPassword("");
    } catch (cause) {
      setError(
        cause instanceof ApiError && cause.status === 401
          ? "That email and password do not match an account."
          : cause instanceof ApiError && cause.status === 429
            ? "Too many attempts. Wait a minute and try again."
            : "Could not reach the service. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (authenticated) {
    return (
      <div className="space-y-1.5">
        <p className="text-ink-muted">
          Signed in as <span className="font-medium text-ink">{role}</span>
        </p>
        <button
          type="button"
          onClick={signOut}
          className="w-full rounded border border-line px-2 py-1 text-ink-secondary hover:border-teal hover:text-teal-ink"
        >
          Sign out
        </button>
      </div>
    );
  }

  if (!open) {
    return (
      <div className="space-y-1.5">
        <p className="text-ink-muted">
          Reading as <span className="font-medium text-ink">viewer</span>. Everything here is
          public.
        </p>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="w-full rounded border border-line px-2 py-1 text-ink-secondary hover:border-teal hover:text-teal-ink"
        >
          Sign in to write memos
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-1.5">
      <label className="block">
        <span className="mb-1 block text-ink-muted">Email</span>
        <input
          type="email"
          autoComplete="username"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="w-full rounded border border-line bg-bg px-2 py-1 text-ink"
          required
        />
      </label>
      <label className="block">
        <span className="mb-1 block text-ink-muted">Password</span>
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="w-full rounded border border-line bg-bg px-2 py-1 text-ink"
          required
        />
      </label>
      {error ? (
        <p role="alert" className="text-[11px] text-sand">
          {error}
        </p>
      ) : null}
      <div className="flex gap-1.5">
        <button
          type="submit"
          disabled={busy}
          className="flex-1 rounded border border-teal bg-sunken px-2 py-1 text-ink disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            setError(null);
          }}
          className="rounded border border-line px-2 py-1 text-ink-secondary"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
