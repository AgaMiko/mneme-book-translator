/**
 * The three sections of an open book — single source of truth.
 *
 * `Translation` is visible-but-disabled rather than hidden, on purpose:
 * it tells the user where they are in the workflow without overpromising.
 */
export const BOOK_TABS = [
  { id: "manuscript", label: "Manuscript", disabled: false },
  { id: "glossary", label: "Glossary", disabled: false },
  { id: "translation", label: "Translation", disabled: true },
] as const satisfies readonly {
  id: string;
  label: string;
  disabled: boolean;
}[];

export type BookTab = (typeof BOOK_TABS)[number]["id"];

export const BOOK_TAB_IDS: readonly BookTab[] = BOOK_TABS.map((t) => t.id);

export const DEFAULT_BOOK_TAB: BookTab = "manuscript";
