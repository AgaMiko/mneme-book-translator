/**
 * Sections of an open book — single source of truth.
 *
 * `Voices` unlocks after glossary extraction completes (canonical characters exist).
 * `Translation` is visible-but-disabled rather than hidden, on purpose.
 */
export const BOOK_TABS = [
  { id: "manuscript", label: "Manuscript", disabled: false },
  { id: "glossary", label: "Glossary", disabled: false },
  { id: "voices", label: "Voices", disabled: false },
  { id: "translation", label: "Translation", disabled: true },
] as const satisfies readonly {
  id: string;
  label: string;
  disabled: boolean;
}[];

export type BookTab = (typeof BOOK_TABS)[number]["id"];

export const BOOK_TAB_IDS: readonly BookTab[] = BOOK_TABS.map((t) => t.id);

export const DEFAULT_BOOK_TAB: BookTab = "manuscript";
