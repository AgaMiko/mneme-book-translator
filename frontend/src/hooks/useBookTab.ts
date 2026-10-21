import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Active tab of an open book.
 *
 * A book opens on the stage it has reached (`startTab`), computed by the
 * caller from the book's pipeline state: a fresh upload opens on the
 * manuscript, a book with voices extracted opens on voices, and so on.
 * `startTab` is `null` while that state is still loading; the tab is set
 * once it arrives, and only once per book, so a status change while you
 * work never moves you to another tab.
 *
 * The tab used to be read from `?tab=` in the URL. The URL does not say
 * which book is open, so the last book's tab leaked into the next one
 * (a new upload opened on Translation). It is no longer read or written.
 */
export function useBookTab<T extends string>(
  bookId: string,
  startTab: T | null,
  fallbackTab: T,
): [T, (tab: T) => void] {
  const [tab, setTab] = useState<T>(startTab ?? fallbackTab);
  const initialisedFor = useRef<string | null>(null);

  useEffect(() => {
    if (initialisedFor.current === bookId || startTab === null) return;
    initialisedFor.current = bookId;
    setTab(startTab);
  }, [bookId, startTab]);

  const select = useCallback((next: T) => setTab(next), []);
  return [tab, select];
}
