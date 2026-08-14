/**
 * One content measure for every tab in an open book.
 *
 * The manuscript, the glossary and the voices panels all sit inside this
 * container, so the text column and the run cards share the same left
 * and right edges. Switching tabs then moves only the content, never the
 * frame — which is the whole point of the persistent header and rail.
 */
export const BOOK_PANEL_CONTAINER = "mx-auto w-full max-w-5xl px-8";

/**
 * The scrolling surface each panel sits on. `scrollbar-gutter: stable`
 * reserves the scrollbar's width even on a short tab, so the content
 * column does not shift sideways by ~7px as you move between tabs.
 */
export const BOOK_PANEL_SURFACE =
  "reader-surface h-full min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]";
