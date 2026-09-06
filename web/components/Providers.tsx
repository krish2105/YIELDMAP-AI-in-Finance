"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, createContext, useContext, useEffect, useMemo, useState } from "react";

import { type Locale, direction, isLocale, translator } from "@/lib/i18n";
import type { Role } from "@/lib/api";

type Theme = "light" | "dark" | "system";

interface Shell {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string) => string;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  role: Role;
  setRole: (role: Role) => void;
}

const ShellContext = createContext<Shell | null>(null);

export function useShell(): Shell {
  const value = useContext(ShellContext);
  if (!value) throw new Error("useShell must be used inside <Providers>");
  return value;
}

function stored(key: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  try {
    return window.localStorage.getItem(key) ?? fallback;
  } catch {
    // A browser with site data blocked throws on access rather than returning null.
    return fallback;
  }
}

function remember(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* a preference that cannot be saved is not worth breaking the page over */
  }
}

export default function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  const [locale, setLocaleState] = useState<Locale>("en");
  const [theme, setThemeState] = useState<Theme>("system");
  const [role, setRoleState] = useState<Role>("viewer");

  // Read preferences after mount: reading localStorage during render would make the server and
  // the client disagree about the first paint.
  useEffect(() => {
    const saved = stored("yieldmap.locale", "en");
    if (isLocale(saved)) setLocaleState(saved);
    const savedTheme = stored("yieldmap.theme", "system");
    if (savedTheme === "light" || savedTheme === "dark" || savedTheme === "system") {
      setThemeState(savedTheme);
    }
    const savedRole = stored("yieldmap.role", "viewer");
    if (savedRole === "viewer" || savedRole === "analyst" || savedRole === "admin") {
      setRoleState(savedRole);
    }
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    root.lang = locale;
    root.dir = direction(locale);
  }, [locale]);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
  }, [theme]);

  const value = useMemo<Shell>(
    () => ({
      locale,
      setLocale: (next) => {
        setLocaleState(next);
        remember("yieldmap.locale", next);
      },
      t: translator(locale),
      theme,
      setTheme: (next) => {
        setThemeState(next);
        remember("yieldmap.theme", next);
      },
      role,
      setRole: (next) => {
        setRoleState(next);
        remember("yieldmap.role", next);
      },
    }),
    [locale, theme, role],
  );

  return (
    <QueryClientProvider client={client}>
      <ShellContext.Provider value={value}>{children}</ShellContext.Provider>
    </QueryClientProvider>
  );
}
