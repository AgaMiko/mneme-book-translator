import { AlertCircle, ArrowLeft, ArrowRight, BookOpen, Check, Lock } from "lucide-react";
import { Fragment } from "react";

import { Button } from "@/components/ui/Button";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import type { BookDetail } from "@/lib/api/client";
import { cn, formatNumber } from "@/lib/utils";

import { computeNextAction } from "./nextAction";
import type { BookTab, TabCounts, TabState } from "./tabs";
import { BOOK_TABS } from "./tabs";

interface Props {
  book: BookDetail;
  activeTab: BookTab;
  onSelectTab: (tab: BookTab) => void;
  onBack: () => void;
  counts: TabCounts;
}

/**
 * Persistent header for an open book. Stays put across tab changes —
 * only the content area below it swaps. That stability is what makes
 * tab switching feel like navigating sections of one book, instead of
 * the page eating itself.
 *
 * Three things live here that used to be spread across the app: the way
 * back to the library, the pipeline (as tabs that report their own
 * state), and the single primary action for whatever comes next. The
 * Manuscript tab sits before the pipeline, set apart by a rule: it is the
 * reading view that shows every step's results, not a step itself.
 */
export function BookHeader({ book, activeTab, onSelectTab, onBack, counts }: Props) {
  const language = (book.manuscript_language ?? book.source_language).toUpperCase();
  const nextAction = computeNextAction(book, activeTab, onSelectTab);
  const failures = collectFailures(book);

  return (
    <header className="border-b border-ink-800 bg-ink-900 backdrop-blur-sm">
      <div className="mx-auto max-w-5xl px-6 pt-3">
        {/* Top bar: back to library on the left, chrome on the right. */}
        <div className="flex items-center justify-between gap-3">
          <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            Library
          </Button>
          <div className="flex items-center gap-3">
            <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
              {book.source_language} → {book.target_language}
            </p>
            <ThemeToggle />
          </div>
        </div>

        {/* Title block. Author, language, size and filename ride on one
            line under the title — four facts, one row, no stack. */}
        <div className="mt-4 flex flex-wrap items-start justify-between gap-7">
          <div className="min-w-0">
            <h1 className="font-serif text-[27px] font-semibold leading-tight text-ink-50">
              {book.title}
            </h1>
            <p className="mt-1.5 flex flex-wrap items-center gap-2.5 text-[13px] text-ink-400">
              {book.author && (
                <>
                  <span className="font-serif text-sm italic text-ink-200">{book.author}</span>
                  <span className="text-ink-700" aria-hidden>
                    ·
                  </span>
                </>
              )}
              <span className="font-mono text-[11px] tracking-wide">
                {language} · {formatNumber(book.word_count)} words
              </span>
              <span className="text-ink-700" aria-hidden>
                ·
              </span>
              <span className="font-mono text-[11px] text-ink-500">{book.original_filename}</span>
            </p>
          </div>
          {nextAction && (
            <Button
              variant="primary"
              size="md"
              className="shrink-0 font-semibold"
              onClick={nextAction.onClick}
            >
              {nextAction.label}
              <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </Button>
          )}
        </div>

        {/* One alert for every failed step, rather than a pill each. */}
        {failures.length > 0 && (
          <div
            role="alert"
            className={cn(
              "mt-3 flex items-start gap-2 rounded-lg border border-danger-border bg-danger-surface",
              "px-3 py-2 text-xs leading-relaxed text-danger",
            )}
          >
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>{failures.join(" · ")}. Open the step to retry — partial results are kept.</span>
          </div>
        )}

        {/* Tab strip — the reading view, then the pipeline. Two lines per
            tab: state + label, then a caption reporting what is inside. */}
        <nav className="-mb-px mt-4 flex gap-1" role="tablist" aria-label="Book sections">
          {BOOK_TABS.map((t, i) => {
            const active = t.id === activeTab;
            const state = t.state(book, counts);
            const tabDisabled = t.disabled || state === "locked";
            const stepNumber = BOOK_TABS.slice(0, i + 1).filter((x) => x.kind === "step").length;
            const firstStep = t.kind === "step" && BOOK_TABS[i - 1]?.kind === "view";
            return (
              <Fragment key={t.id}>
                {firstStep && (
                  <span aria-hidden className="mx-2 my-2.5 w-px self-stretch bg-ink-700" />
                )}
                <button
                  type="button"
                  role="tab"
                  aria-selected={active}
                  aria-disabled={tabDisabled || undefined}
                  disabled={tabDisabled}
                  onClick={() => !tabDisabled && onSelectTab(t.id)}
                  className={cn(
                    "relative -mb-px min-w-[9.5rem] px-[18px] pb-[11px] pt-3 text-left",
                    "transition-colors duration-150 ease-out",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    // The whole shorthand in both branches — a longhand
                    // override on top of a shorthand base leaves the
                    // bottom colour unset, which resolves to white.
                    active
                      ? "border-b-2 border-b-accent border-solid"
                      : "border-b-2 border-b-transparent border-solid",
                    tabDisabled && "cursor-not-allowed",
                  )}
                >
                  <span className="flex items-center gap-2">
                    {t.kind === "view" ? (
                      <ViewBadge />
                    ) : (
                      <TabBadge state={state} index={stepNumber} />
                    )}
                    <span
                      className={cn(
                        "font-sans text-[13px] font-medium",
                        active ? "text-ink-50" : tabDisabled ? "text-ink-500" : "text-ink-200",
                      )}
                    >
                      {t.label}
                    </span>
                  </span>
                  {/* Indented past the badge so the caption hangs under the
                    label rather than under the step marker. */}
                  <span className="mt-1 block truncate pl-[26px] font-mono text-[10px] tracking-wide text-ink-500">
                    {t.caption(book, counts)}
                  </span>
                </button>
              </Fragment>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

/** The reading view has no state of its own: a book, not a numeral or check. */
function ViewBadge() {
  return (
    <span
      className="flex h-[18px] w-[18px] shrink-0 items-center justify-center text-ink-400"
      aria-hidden
    >
      <BookOpen className="h-3.5 w-3.5" />
    </span>
  );
}

/**
 * Numeral when the step hasn't run, check when it's done, padlock when
 * it's out of reach, pulse while it's in flight. The badge is the only
 * status indicator the header needs.
 */
function TabBadge({ state, index }: { state: TabState; index: number }) {
  const base =
    "flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border font-mono text-[9px] tabular-nums";

  if (state === "done") {
    return (
      <span
        className={cn(base, "border-success-border bg-success-surface text-success")}
        aria-label="completed"
      >
        <Check className="h-2.5 w-2.5" aria-hidden />
      </span>
    );
  }
  if (state === "locked") {
    return (
      <span className={cn(base, "border-ink-700 text-ink-600")} aria-label="locked">
        <Lock className="h-2.5 w-2.5" aria-hidden />
      </span>
    );
  }
  if (state === "active") {
    return (
      <span className={cn(base, "border-accent bg-accent-soft text-accent")} aria-label="running">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden />
      </span>
    );
  }
  return (
    <span className={cn(base, "border-ink-700 text-ink-400")} aria-hidden>
      {index}
    </span>
  );
}

/** Human names for whichever pipeline steps are in a failed state. */
function collectFailures(book: BookDetail): string[] {
  const failures: string[] = [];
  if (book.metadata_status === "failed") failures.push("Metadata extraction failed");
  if (book.glossary_extraction_status === "failed") failures.push("Glossary extraction failed");
  if (book.speakers_extraction_status === "failed") failures.push("Speaker identification failed");
  if (book.voice_extraction_status === "failed") failures.push("Voice extraction failed");
  return failures;
}
