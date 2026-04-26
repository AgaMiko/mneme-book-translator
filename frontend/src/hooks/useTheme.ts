import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "mneme:theme";

function readStoredTheme(): Theme | null {
  if (typeof window === "undefined") return null;
  const value = window.localStorage.getItem(STORAGE_KEY);
  return value === "light" || value === "dark" ? value : null;
}

function readSystemTheme(): Theme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
}

/**
 * Theme controller.
 *
 * - System preference is the default until the user makes a choice.
 * - User choice persists in localStorage and overrides system preference
 *   from then on.
 * - The `data-theme` attribute on <html> is set synchronously by the
 *   bootstrap script in index.html (to prevent a flash before React
 *   mounts) and kept in sync here for any subsequent toggles.
 */
export function useTheme() {
  // Initial value: stored choice if any, else current system preference.
  // Reading from the DOM is most accurate because the bootstrap script
  // already set this before React mounted.
  const [theme, setThemeState] = useState<Theme>(() => {
    if (typeof document !== "undefined") {
      const current = document.documentElement.getAttribute("data-theme");
      if (current === "dark" || current === "light") return current;
    }
    return readStoredTheme() ?? readSystemTheme();
  });

  // Keep the DOM in sync. (Almost a no-op since the bootstrap script
  // already did this, but matters when the user toggles.)
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // Follow system preference changes — but only when the user hasn't
  // made an explicit choice. Once they toggle, we respect that until
  // they reset.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (readStoredTheme() !== null) return;

    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => {
      setThemeState(e.matches ? "dark" : "light");
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, next);
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

  return { theme, setTheme, toggleTheme };
}
