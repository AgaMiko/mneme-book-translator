import { BookHeader } from "@/components/book/BookHeader";
import { GlossaryView } from "@/components/book/GlossaryView";
import { ManuscriptView } from "@/components/book/ManuscriptView";
import { BOOK_TAB_IDS, DEFAULT_BOOK_TAB } from "@/components/book/tabs";
import { TranslationView } from "@/components/book/TranslationView";
import { WorkflowHint } from "@/components/book/WorkflowHint";
import { useBookTab } from "@/hooks/useBookTab";
import { useBook } from "@/lib/api/hooks";

interface Props {
  bookId: string;
}

/**
 * Thin shell. Orchestrates loading, tab state, and which section to
 * render. All real content lives in `components/book/`.
 *
 * Layout is three stacked rows: persistent header (title + tabs),
 * optional workflow hint (one quiet line pointing at the next sensible
 * action), and the active section's content. The header and hint stay
 * put across tab switches — only the third row swaps. That stability
 * is what makes tab switching feel like navigating sections of one
 * book, instead of the page eating itself.
 */
export function BookReader({ bookId }: Props) {
  const { data: book, isLoading, isError } = useBook(bookId);
  const [activeTab, setActiveTab] = useBookTab(bookId, BOOK_TAB_IDS, DEFAULT_BOOK_TAB);

  if (isLoading) {
    return (
      <div className="mx-auto max-w-prose space-y-4 px-6 py-12" aria-busy="true">
        <div className="h-10 w-2/3 animate-pulse rounded bg-ink-800/60" />
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-4 animate-pulse rounded bg-ink-800/40" />
          ))}
        </div>
      </div>
    );
  }

  if (isError || !book) {
    return (
      <div className="mx-auto max-w-prose px-6 py-12 text-sm text-red-300">
        Couldn't load this manuscript.
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <BookHeader book={book} activeTab={activeTab} onSelectTab={setActiveTab} />
      <WorkflowHint book={book} activeTab={activeTab} onSelectTab={setActiveTab} />

      <div className="min-h-0 flex-1">
        {activeTab === "manuscript" && <ManuscriptView book={book} />}
        {activeTab === "glossary" && <GlossaryView book={book} />}
        {activeTab === "translation" && <TranslationView />}
      </div>
    </div>
  );
}
