import { useCallback, useEffect, useState } from "react";

/**
 * Tiny URL-synced state for the active book tab.
 *
 * - Reads `?tab=...` on mount so a reload preserves the working view.
 * - Writes back via `history.replaceState` (no extra entry per click).
 * - Resets to the default whenever `bookId` changes — opening a fresh
 *   book always starts on Manuscript, regardless of the tab the previous
 *   book was on. This is deliberate: a book is "what's in it" first;
 *   "what we're doing with it" is a deliberate next step, not a sticky
 *   preference that follows the user across books.
 *
 * Avoids a router dependency. Plays nicely with the back/forward buttons
 * because we use replaceState (not pushState) — back goes to the previous
 * book or page, not to the previous tab. That's the right default for
 * a workflow surface where each tab isn't a "place" worth revisiting.
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

  // Reset on book switch
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
