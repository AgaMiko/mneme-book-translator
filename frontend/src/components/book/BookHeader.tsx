import { AlertCircle } from "lucide-react";

import type {
  BookDetail,
  GlossaryExtractionStatus,
  MetadataStatus,
} from "@/lib/api/client";
import { cn, formatNumber } from "@/lib/utils";

import type { BookTab } from "./tabs";
import { BOOK_TABS } from "./tabs";

interface Props {
  book: BookDetail;
  activeTab: BookTab;
  onSelectTab: (tab: BookTab) => void;
}

/**
 * Persistent header for an open book. Stays put across tab changes —
 * only the content area below it swaps. That stability is what makes
 * tab switching feel like navigating sections of one book, instead of
 * the page eating itself.
 */
export function BookHeader({ book, activeTab, onSelectTab }: Props) {
  const language = (book.manuscript_language ?? book.source_language).toUpperCase();

  return (
    <header className="border-b border-ink-800 bg-ink-900/95 backdrop-blur-sm">
      <div className="mx-auto max-w-5xl px-6 pt-6">
        {/* Title + metadata block */}
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
        <h1 className="mt-2 font-serif text-3xl font-semibold text-ink-50">
          {book.title}
        </h1>
        {book.author && (
          <p className="mt-0.5 font-serif italic text-ink-300">by {book.author}</p>
        )}
        <p className="mt-1 font-mono text-xs text-ink-500">
          {book.original_filename}
        </p>

        {/* Tab strip */}
        <nav
          className="-mb-px mt-6 flex gap-1"
          role="tablist"
          aria-label="Book sections"
        >
          {BOOK_TABS.map((t) => {
            const active = t.id === activeTab;
            return (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={active}
                aria-disabled={t.disabled || undefined}
                disabled={t.disabled}
                onClick={() => !t.disabled && onSelectTab(t.id)}
                className={cn(
                  "relative -mb-px border-b-2 px-4 py-3 font-mono text-xs uppercase tracking-wider",
                  "transition-colors duration-150 ease-out",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  active
                    ? "border-accent text-ink-50"
                    : "border-transparent text-ink-400 hover:text-ink-100",
                  t.disabled && "cursor-not-allowed text-ink-600 hover:text-ink-600",
                )}
              >
                <span>{t.label}</span>
                {t.disabled && (
                  <span className="ml-2 rounded bg-ink-800 px-1.5 py-0.5 text-[9px] text-ink-500">
                    soon
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>
    </header>
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

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-red-900/60 bg-red-950/30 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-red-300">
      <AlertCircle className="h-3 w-3" aria-hidden />
      metadata extraction failed
    </span>
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
