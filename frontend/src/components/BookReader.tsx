import { useCallback, useMemo, useState } from "react";

import { BookHeader } from "@/components/book/BookHeader";
import { ChapterRail } from "@/components/book/ChapterRail";
import { GlossaryView } from "@/components/book/GlossaryView";
import { ManuscriptView } from "@/components/book/ManuscriptView";
import { PassagesView } from "@/components/book/PassagesView";
import {
  DEFAULT_BOOK_TAB,
  glossaryUsable,
  startTabFor,
  type TabCounts,
} from "@/components/book/tabs";
import { TranslationView } from "@/components/book/TranslationView";
import { VoiceView } from "@/components/book/VoiceView";
import { useBookTab } from "@/hooks/useBookTab";
import {
  useBook,
  usePassages,
  useTranslation,
  useWorkingGlossary,
  useWorkingVoices,
} from "@/lib/api/hooks";

interface Props {
  bookId: string;
  onBack: () => void;
}

/**
 * Thin shell. Orchestrates loading, tab state, the persistent chapter
 * rail, and which section to render. All real content lives in
 * `components/book/`.
 */
export function BookReader({ bookId, onBack }: Props) {
  const { data: book, isLoading, isError } = useBook(bookId);
  const translation = useTranslation(bookId);
  const translationRun = translation.data?.run ?? null;

  // Open on the stage the book has reached, once both queries have answered.
  const translationKnown = translation.isSuccess || translation.isError;
  const startTab =
    book && translationKnown
      ? startTabFor(book, {
          translationStatus: translationRun?.status ?? null,
          translationDone: translationRun?.fragments_completed ?? 0,
        })
      : null;
  const [activeTab, setActiveTab] = useBookTab(bookId, startTab, DEFAULT_BOOK_TAB);

  /**
   * Which chapter is in view. Owned here rather than in `ManuscriptView`
   * so the rail can read it from any tab, and so it survives the
   * manuscript unmounting while you work in the glossary.
   */
  const [activeChapter, setActiveChapter] = useState<string | null>(null);
  const [chapterScrollTarget, setChapterScrollTarget] = useState<string | null>(null);

  /**
   * Counts for the tab captions. Both queries are already mounted by the
   * panels themselves — react-query dedupes on the same key, so reading
   * them here costs nothing extra.
   */
  const glossary = useWorkingGlossary(bookId, {
    enabled: true,
    refetchIntervalMs: book?.glossary_extraction_status === "running" ? 2000 : false,
  });
  const voices = useWorkingVoices(bookId, {
    enabled: book ? glossaryUsable(book) : false,
    refetchIntervalMs: book?.voice_extraction_status === "running" ? 1500 : false,
  });

  const passages = usePassages(bookId, translationRun?.status === "running");

  const counts: TabCounts = useMemo(() => {
    const glossaryEntries = glossary.data?.entries ?? [];
    const voiceEntries = voices.data?.entries ?? [];
    const pendingOf = (entries: readonly { status: string }[]) =>
      entries.filter((e) => e.status === "proposed" || e.status === "adjusted").length;
    return {
      glossaryTotal: glossaryEntries.length,
      glossaryPending: pendingOf(glossaryEntries),
      voicesTotal: voiceEntries.length,
      voicesPending: pendingOf(voiceEntries),
      translationStatus: translationRun?.status ?? null,
      translationDone: translationRun?.fragments_completed ?? 0,
      translationTotal: translationRun?.fragments_total ?? 0,
      passagesStatus: passages.data?.state.status ?? "idle",
      passagesTotal: (passages.data?.passages ?? []).filter((p) => p.status !== "dismissed").length,
      passagesOpen: passages.data?.open_flags ?? 0,
      passagesBlocking: passages.data?.blocking_flags ?? 0,
    };
  }, [glossary.data?.entries, voices.data?.entries, translationRun, passages.data]);

  /**
   * Picking a chapter from a working tab means "take me back to the text
   * there" — switch to the manuscript, then scroll once it mounts.
   */
  const handleSelectChapter = useCallback(
    (chapterDomId: string) => {
      setActiveChapter(chapterDomId);
      setChapterScrollTarget(chapterDomId);
      setActiveTab("manuscript");
    },
    [setActiveTab],
  );

  const handleScrollHandled = useCallback(() => setChapterScrollTarget(null), []);

  /** A glossary term clicked in the manuscript or translation: open it in the glossary. */
  const [glossaryFocus, setGlossaryFocus] = useState<string | null>(null);
  const handleOpenTerm = useCallback(
    (termId: string) => {
      setGlossaryFocus(termId);
      setActiveTab("glossary");
    },
    [setActiveTab],
  );
  const handleGlossaryFocusHandled = useCallback(() => setGlossaryFocus(null), []);

  if (isLoading) {
    return (
      <div className="mx-auto max-w-prose space-y-4 px-6 py-12" aria-busy="true">
        <div className="h-10 w-2/3 animate-pulse rounded bg-ink-800" />
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-4 animate-pulse rounded bg-ink-800" />
          ))}
        </div>
      </div>
    );
  }

  if (isError || !book) {
    return (
      <div className="mx-auto max-w-prose px-6 py-12 text-sm text-danger">
        Couldn't load this manuscript.
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <BookHeader
        book={book}
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        onBack={onBack}
        counts={counts}
      />

      <div className="flex min-h-0 flex-1">
        <ChapterRail book={book} activeChapterId={activeChapter} onSelect={handleSelectChapter} />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {activeTab === "manuscript" && (
            <ManuscriptView
              book={book}
              onActiveChapterChange={setActiveChapter}
              scrollTarget={chapterScrollTarget}
              onScrollHandled={handleScrollHandled}
              onOpenTerm={handleOpenTerm}
            />
          )}
          {activeTab === "glossary" && (
            <GlossaryView
              book={book}
              focusEntryId={glossaryFocus}
              onFocusHandled={handleGlossaryFocusHandled}
            />
          )}
          {activeTab === "voices" && <VoiceView book={book} />}
          {activeTab === "review" && <PassagesView book={book} />}
          {activeTab === "translation" && (
            <TranslationView book={book} onOpenTerm={handleOpenTerm} onSelectTab={setActiveTab} />
          )}
        </div>
      </div>
    </div>
  );
}
