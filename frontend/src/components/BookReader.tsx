import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, ChevronRight } from "lucide-react";

import {
  GlossaryExtractionActionBar,
  GlossaryExtractionWorkspace,
} from "@/components/GlossaryExtractionWorkspace";
import { GlossaryReviewPanel } from "@/components/GlossaryReviewPanel";
import {
  bookKeys,
  useBook,
  useGlossaryExtractionEstimate,
  useContinueGlossaryExtraction,
  useStartGlossaryExtraction,
  useStopGlossaryExtraction,
} from "@/lib/api/hooks";
import type { GlossaryExtractionStatus, MetadataStatus } from "@/lib/api/client";
import { cn, formatNumber } from "@/lib/utils";

interface Props {
  bookId: string;
}

type ReaderPhase = "manuscript" | "glossary";

type GlossarySubView = "extraction" | "terms";

export function BookReader({ bookId }: Props) {
  const queryClient = useQueryClient();
  const { data: book, isLoading, isError } = useBook(bookId);
  const [phase, setPhase] = useState<ReaderPhase>("manuscript");
  const [glossarySubView, setGlossarySubView] = useState<GlossarySubView>("extraction");
  const [activeChapter, setActiveChapter] = useState<string | null>(null);
  const chapterRefs = useRef<Record<string, HTMLElement | null>>({});
  const prevGlossaryStatus = useRef<string | null>(null);
  const estimate = useGlossaryExtractionEstimate(bookId, phase === "glossary");
  const startGlossary = useStartGlossaryExtraction(bookId);
  const continueGlossary = useContinueGlossaryExtraction(bookId);
  const stopGlossary = useStopGlossaryExtraction(bookId);

  useEffect(() => {
    if (!book) return;
    const prev = prevGlossaryStatus.current;
    prevGlossaryStatus.current = book.glossary_extraction_status;
    if (prev === "running" && book.glossary_extraction_status !== "running") {
      void queryClient.invalidateQueries({
        queryKey: bookKeys.workingGlossary(bookId),
      });
    }
  }, [book, bookId, queryClient]);

  useEffect(() => {
    if (!book) return;
    const base = "Book Translator";
    if (phase === "glossary" && glossarySubView === "terms") {
      document.title = `${book.title} · Glossary`;
    } else {
      document.title = `${book.title} · ${base}`;
    }
    return () => {
      document.title = base;
    };
  }, [book, phase, glossarySubView]);

  const showChapterNav =
    phase === "manuscript" || (phase === "glossary" && glossarySubView === "extraction");
  const showManuscriptBody =
    phase === "manuscript" || (phase === "glossary" && glossarySubView === "extraction");

  // Track which chapter is currently in view to highlight the nav.
  useEffect(() => {
    if (!book) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible) setActiveChapter(visible.target.id);
      },
      { rootMargin: "-20% 0px -60% 0px", threshold: [0.1, 0.5, 1.0] },
    );
    Object.values(chapterRefs.current).forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, [book]);

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

  const language = (book.manuscript_language ?? book.source_language).toUpperCase();
  const extractionActionBarEnabled =
    phase === "glossary" &&
    glossarySubView === "extraction" &&
    Boolean(estimate.data && estimate.data.window_count > 0);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex min-h-0 flex-1">
      {/* Chapter nav */}
      <nav
        className={cn(
          "w-56 shrink-0 border-r border-ink-800 px-4 py-8 overflow-y-auto",
          showChapterNav ? "hidden lg:block" : "hidden",
        )}
        aria-label="Chapters"
      >
        <p className="mb-3 text-xs uppercase tracking-wider text-ink-400">
          Chapters
        </p>
        <ol className="space-y-1">
          {book.chapters.map((c, idx) => {
            const id = `chapter-${c.id}`;
            const label = c.title ?? `Chapter ${idx + 1}`;
            return (
              <li key={c.id}>
                <a
                  href={`#${id}`}
                  className={cn(
                    "block rounded px-2 py-1.5 text-xs transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    activeChapter === id
                      ? "bg-ink-800 text-ink-50"
                      : "text-ink-400 hover:bg-ink-800/60 hover:text-ink-100",
                  )}
                >
                  <span className="text-ink-500 mr-2 tabular-nums">
                    {String(idx + 1).padStart(2, "0")}
                  </span>
                  <span className="truncate">{label}</span>
                </a>
              </li>
            );
          })}
        </ol>
      </nav>

      {/* Reader surface + optional slim extraction actions */}
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="reader-surface flex-1 overflow-y-auto">
        <article
          className={cn(
            "mx-auto px-6 py-12 lg:py-16",
            phase === "glossary" && glossarySubView === "terms"
              ? "max-w-3xl"
              : "max-w-prose",
          )}
        >
          <header className="mb-12 border-b border-ink-800 pb-8">
            <div className="flex flex-wrap items-center gap-3">
              <p className="font-mono text-xs uppercase tracking-widest text-ink-400">
                {language} · {formatNumber(book.word_count)} words
              </p>
              <MetadataPill status={book.metadata_status} />
              <GlossaryExtractionPill
                status={book.glossary_extraction_status}
                windowsCompleted={book.glossary_extraction_windows_completed ?? null}
                windowsTotal={book.glossary_extraction_windows_total ?? null}
              />
            </div>
            <h1 className="mt-3 font-serif text-4xl font-semibold text-ink-50">
              {book.title}
            </h1>
            {book.author && (
              <p className="mt-1 font-serif italic text-ink-300">
                by {book.author}
              </p>
            )}
            <p className="mt-2 font-mono text-xs text-ink-500">
              {book.original_filename}
            </p>
            {book.language_style_note && (
              <p className="mt-5 max-w-prose border-l-2 border-ink-700 pl-4 text-sm italic leading-relaxed text-ink-300">
                {book.language_style_note}
              </p>
            )}

            {phase === "manuscript" && (
              <div className="mt-8 flex flex-col gap-4 border-t border-ink-800/80 pt-6 sm:flex-row sm:items-center sm:justify-between">
                <p className="max-w-md text-sm leading-relaxed text-ink-400">
                  Build a term list for translation: cost estimate, then a background run
                  over the full text.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setPhase("glossary");
                    setGlossarySubView("extraction");
                  }}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-2 self-start rounded-md border border-accent/40",
                    "bg-accent/10 px-4 py-2.5 font-mono text-xs uppercase tracking-wider text-accent",
                    "transition-colors duration-200 ease-out hover:bg-accent/20",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  )}
                >
                  Glossary workspace
                  <ChevronRight className="h-4 w-4" aria-hidden />
                </button>
              </div>
            )}
          </header>

          {phase === "glossary" && (
            <div className="mb-10 flex flex-col gap-4 border-b border-ink-800 pb-5 sm:flex-row sm:items-center sm:justify-between">
              <button
                type="button"
                onClick={() => setPhase("manuscript")}
                className={cn(
                  "inline-flex w-fit items-center gap-1.5 self-start rounded-md px-2 py-1.5",
                  "font-mono text-xs uppercase tracking-wider text-ink-400",
                  "hover:bg-ink-800 hover:text-ink-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                )}
              >
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
                Manuscript
              </button>
              <div
                className="flex flex-wrap gap-2 sm:ml-auto"
                role="tablist"
                aria-label="Glossary views"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={glossarySubView === "extraction"}
                  onClick={() => setGlossarySubView("extraction")}
                  className={cn(
                    "rounded-md px-3 py-2 font-mono text-xs uppercase tracking-wider transition-colors duration-200 ease-out",
                    glossarySubView === "extraction"
                      ? "bg-ink-800 text-ink-50 ring-1 ring-ink-600"
                      : "text-ink-400 hover:bg-ink-800/60 hover:text-ink-100",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  )}
                >
                  Run & estimate
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={glossarySubView === "terms"}
                  onClick={() => setGlossarySubView("terms")}
                  className={cn(
                    "rounded-md px-3 py-2 font-mono text-xs uppercase tracking-wider transition-colors duration-200 ease-out",
                    glossarySubView === "terms"
                      ? "bg-ink-800 text-ink-50 ring-1 ring-ink-600"
                      : "text-ink-400 hover:bg-ink-800/60 hover:text-ink-100",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  )}
                >
                  Glossary terms
                </button>
              </div>
            </div>
          )}

          {phase === "glossary" && glossarySubView === "extraction" && (
            <GlossaryExtractionWorkspace
              book={book}
              estimate={estimate}
              startGlossary={startGlossary}
              continueGlossary={continueGlossary}
              stopGlossary={stopGlossary}
              onOpenTerms={() => setGlossarySubView("terms")}
            />
          )}

          {phase === "glossary" && glossarySubView === "terms" && (
            <GlossaryReviewPanel
              bookId={bookId}
              pollWhileRunning={book.glossary_extraction_status === "running"}
            />
          )}

          {showManuscriptBody &&
            book.chapters.map((chapter, idx) => {
            const id = `chapter-${chapter.id}`;
            const label = chapter.title ?? `Chapter ${idx + 1}`;
            return (
              <section
                key={chapter.id}
                id={id}
                ref={(el) => (chapterRefs.current[id] = el)}
                className="mb-16 scroll-mt-8"
              >
                <h2 className="mb-6 font-serif text-2xl text-accent-pink">
                  {label}
                </h2>
                <div className="chapter-body space-y-5 font-serif text-lg leading-relaxed text-ink-100">
                  {chapter.paragraphs.length === 0 ? (
                    <p className="italic text-ink-500">[empty chapter]</p>
                  ) : (
                    chapter.paragraphs.map((p) => (
                      <p key={p.id}>{p.text}</p>
                    ))
                  )}
                </div>
              </section>
            );
          })}
        </article>
        </div>
        <GlossaryExtractionActionBar
          book={book}
          startGlossary={startGlossary}
          continueGlossary={continueGlossary}
          stopGlossary={stopGlossary}
          enabled={extractionActionBarEnabled}
        />
      </div>
      </div>
    </div>
  );
}

function GlossaryExtractionPill({
  status,
  windowsCompleted,
  windowsTotal,
}: {
  status: GlossaryExtractionStatus;
  windowsCompleted: number | null;
  windowsTotal: number | null;
}) {
  if (status === "idle") return null;

  if (status === "running") {
    const progress =
      windowsTotal != null && windowsTotal > 0
        ? ` ${windowsCompleted ?? 0}/${windowsTotal}`
        : "";
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-ink-800 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink-300">
        <span
          className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent"
          aria-hidden
        />
        glossary extraction…{progress}
      </span>
    );
  }

  if (status === "completed") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-950/40 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-emerald-300">
        glossary saved
      </span>
    );
  }

  if (status === "cancelled") {
    const tail =
      windowsTotal != null && windowsTotal > 0
        ? ` after ${windowsCompleted ?? 0}/${windowsTotal}`
        : "";
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-900/50 bg-amber-950/25 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-amber-200/90">
        glossary stopped{tail}
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-red-900/60 bg-red-950/30 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-red-300">
      <AlertCircle className="h-3 w-3" aria-hidden />
      glossary failed
    </span>
  );
}

function MetadataPill({ status }: { status: MetadataStatus }) {
  if (status === "ready") return null;

  if (status === "pending") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-ink-800 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink-300">
        <span
          className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent"
          aria-hidden
        />
        extracting metadata…
      </span>
    );
  }

  // failed
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-red-900/60 bg-red-950/30 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-red-300">
      <AlertCircle className="h-3 w-3" aria-hidden />
      metadata extraction failed
    </span>
  );
}
