import { useCallback, useEffect, useState } from "react";

/**
 * Tiny URL-synced state for the active book tab.
 *
 * - Reads `?tab=...` on mount so a reload preserves the working view.
 * - Writes back via `history.replaceState` (no extra entry per click).
 * - Resets to the default whenever `bookId` changes — opening a fresh
 *   book always starts on Manuscript.
 */
export function useBookTab<T extends string>(
  bookId: string,
  validTabs: readonly T[],
  defaultTab: T,
): [T, (tab: T) => void] {
  const readFromUrl = useCallback((): T => {
    if (typeof window === "undefined") return defaultTab;
    const param = new URLSearchParams(window.location.search).get("tab");
    return validTabs.includes(param as T) ? (param as T) : defaultTab;
  }, [defaultTab, validTabs]);

  const [tab, setTabState] = useState<T>(readFromUrl);

  useEffect(() => {
    setTabState(readFromUrl());
  }, [bookId, readFromUrl]);

  const setTab = useCallback((next: T) => {
    setTabState(next);
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.replaceState({}, "", url.toString());
  }, []);

  return [tab, setTab];
}
