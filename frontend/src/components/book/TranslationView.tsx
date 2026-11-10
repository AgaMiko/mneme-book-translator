import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Download,
  Loader2,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { useStepModel } from "@/hooks/useStepModel";
import {
  ApiError,
  type BookDetail,
  type ChapterTranslation,
  type DeclaredEdit,
  type GlossaryTerm,
  type QaIssue,
  type StyleMetrics,
  type TranslationEstimate,
  type TranslationFragment,
  type TermSpan,
  type TranslationStage,
  type TranslatorNote,
  translationExportUrl,
} from "@/lib/api/client";
import {
  useContinueTranslation,
  useStartTranslation,
  useStopTranslation,
  usePassages,
  useTranslation,
  useTranslationEstimate,
  useTranslationTerms,
} from "@/lib/api/hooks";
import { cn, formatNumber } from "@/lib/utils";

import { CostGuardNotice } from "./CostGuardNotice";
import { BOOK_PANEL_CONTAINER, BOOK_PANEL_SURFACE } from "./layout";
import { ModelPicker } from "./ModelPicker";
import { StepRunBar, type RunStatus } from "./StepRunBar";
import { type BookTab, translationBlockers } from "./tabs";
import { HighlightedText, MissingTerms, TermProvider } from "./TermHighlight";
import { englishTerms, useTerms } from "./terms";

interface Props {
  book: BookDetail;
  /** Open a glossary term in the Glossary tab. */
  onOpenTerm: (termId: string) => void;
  /** Switch to another tab (the step that still has to be done). */
  onSelectTab: (tab: BookTab) => void;
}

const STAGES: { id: TranslationStage; label: string; hint: string }[] = [
  { id: "faithful", label: "Draft", hint: "Faithful draft: complete and accurate, not yet edited" },
  // Only three-stage runs have a separate line edit.
  { id: "line_edit", label: "Line edit", hint: "Edited into natural English prose" },
  // "Polish" would be ambiguous next to the Polish source, so the last stage
  // is called "Final" everywhere in the UI (its API id stays `polish`).
  { id: "polish", label: "Final", hint: "The finished English" },
];

// Style targets from the final-edit brief (mirrors backend translation_qa).
const TARGETS = { shePct: 15, ellipses: 3, dashes: 6 };

const NOTE_LABELS: Record<string, string> = {
  source_typo: "Source typo",
  continuity: "Continuity",
  ambiguity: "Ambiguity",
  wordplay: "Wordplay",
  placeholder: "Placeholder",
  added_clarification: "Added words",
  term_choice: "Term choice",
};

const EDIT_LABELS: Record<string, string> = {
  meaning_risk: "May change meaning",
  voice_device: "Voice device changed",
  continuity: "Continuity fix",
};

/**
 * The Translate step: the run in one line, a table of chapters with their
 * state, and one chapter at a time to read next to the source.
 *
 * By default each fragment is translated in one step straight into the
 * final English; two- and three-step modes add a faithful draft and a
 * separate line edit. The model, the pipeline and the estimate are under
 * the run bar's Settings. You pick chapters in the table to translate just
 * those; the run bar's own button translates the rest of the book.
 */
export function TranslationView({ book, onOpenTerm, onSelectTab }: Props) {
  const translation = useTranslation(book.id);
  const passages = usePassages(book.id);
  // Unknown until the passages query answers; exports wait for it.
  const blockingPassages = passages.data?.blocking_flags ?? 0;
  const exportReady = passages.isSuccess || passages.isError;
  const terms = useTranslationTerms(book.id);
  const [stage, setStage] = useState<TranslationStage>("polish");
  const [selected, setSelected] = useState<string[]>([]);
  const [retranslate, setRetranslate] = useState(false);
  const [readingId, setReadingId] = useState<string | null>(null);
  const readingRef = useRef<HTMLDivElement>(null);
  const run = translation.data?.run ?? null;

  const byChapter = useMemo(() => {
    const map = new Map<string, ChapterTranslation>();
    for (const ch of translation.data?.chapters ?? []) map.set(ch.chapter_id, ch);
    return map;
  }, [translation.data?.chapters]);

  // Two-step runs have no separate line edit: show only stages that have text.
  const visibleStages = useMemo(() => {
    const present = new Set<TranslationStage>();
    for (const ch of translation.data?.chapters ?? []) {
      for (const f of ch.fragments) {
        for (const s of Object.keys(f.stages) as TranslationStage[]) present.add(s);
      }
    }
    return STAGES.filter((s) => present.has(s.id));
  }, [translation.data?.chapters]);

  const status = useMemo(() => {
    const m = new Map<string, ChapterStatus>();
    for (const c of book.chapters) m.set(c.id, chapterStatus(byChapter.get(c.id)));
    return m;
  }, [book.chapters, byChapter]);
  const isDone = (id: string) => {
    const st = status.get(id);
    return !!st && st.total > 0 && st.finished === st.total;
  };
  const doneCount = book.chapters.filter((c) => isDone(c.id)).length;
  const allDone = doneCount === book.chapters.length && doneCount > 0;
  let bookFragments = 0;
  let bookFinished = 0;
  for (const st of status.values()) {
    bookFragments += st.total;
    bookFinished += st.finished;
  }

  // Chapters with any English to read.
  const readable = book.chapters.filter((c) => (status.get(c.id)?.withText ?? 0) > 0);
  const reading = readable.find((c) => c.id === readingId) ?? readable[0];

  // The rest of the book unless chapters are picked. Without "translate
  // again", a whole-book run skips finished chapters, so the estimate
  // covers only the rest.
  const restIds =
    retranslate || doneCount === 0
      ? null
      : book.chapters.filter((c) => !isDone(c.id)).map((c) => c.id);
  const translationModel = useStepModel("translation");
  const restEstimate = useTranslationEstimate(book.id, restIds, translationModel.model);
  const selectionEstimate = useTranslationEstimate(
    book.id,
    selected.length ? selected : restIds,
    translationModel.model,
  );
  const start = useStartTranslation(book.id);
  const resume = useContinueTranslation(book.id);
  const stop = useStopTranslation(book.id);

  const running = run?.status === "running";
  const canContinue = run?.status === "failed" || run?.status === "cancelled";
  const missing = translationBlockers(book);
  const guard = book.cost_guard.translation;
  const paused = run?.status === "cancelled" && !!guard?.paused_reason;

  const error =
    errorText(start.error, start.isError, "Could not start the translation.") ??
    errorText(resume.error, resume.isError, "Could not continue the run.") ??
    errorText(stop.error, stop.isError, "Could not stop the run.");

  const startRun = (chapterIds: string[] | null) =>
    start.mutate(
      { chapter_ids: chapterIds, retranslate, model: translationModel.model },
      { onSuccess: () => setSelected([]) },
    );

  const toggle = (id: string) =>
    setSelected(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  const openChapter = (id: string) => {
    setReadingId(id);
    window.setTimeout(() => readingRef.current?.scrollIntoView({ block: "start" }), 0);
  };

  // ── Run bar ──
  const barStatus: RunStatus = running
    ? "running"
    : run?.status === "cancelled" || run?.status === "failed"
      ? run.status
      : allDone
        ? "completed"
        : "idle";

  const bookLine =
    bookFragments > 0
      ? `${formatNumber(bookFinished)} of ${formatNumber(bookFragments)} fragments translated`
      : "Nothing translated yet";
  let summaryText: string;
  if (missing.length > 0) {
    summaryText =
      missing.length === 2
        ? "Build the glossary and the voices first. The translation uses both."
        : missing[0] === "glossary"
          ? "Finish the glossary first. The translation uses its terms."
          : "Build the voices first. The translation uses the voice profiles.";
  } else if (running && run) {
    summaryText = run.cancel_requested
      ? "Stopping after the fragments in progress…"
      : `Translating · this run ${run.fragments_completed}/${run.fragments_total} · ${bookLine.toLowerCase()}`;
  } else if (allDone) {
    summaryText = `Whole book translated · ${formatNumber(bookFragments)} fragments`;
  } else if (run?.status === "cancelled") {
    summaryText = `${bookLine} · the last run stopped`;
  } else if (run?.status === "failed") {
    summaryText = `${bookLine} · the last run had errors`;
  } else if (bookFinished === 0) {
    summaryText =
      "Nothing translated yet. Pick a chapter below to try it first, or translate the whole book.";
  } else {
    summaryText = bookLine;
  }

  const meta = run
    ? STAGES.filter((st) => run.models[st.id])
        .map((st) => `${st.label.toLowerCase()}: ${run.models[st.id]}`)
        .join(" · ")
    : null;

  const restCost = restEstimate.data ? ` · ~$${restEstimate.data.cost_usd.toFixed(2)}` : "";
  const action =
    missing.length > 0 ? (
      <Button variant="ghost" size="sm" onClick={() => onSelectTab(missing[0])}>
        {missing[0] === "glossary" ? "Go to Glossary" : "Go to Voices"}
      </Button>
    ) : running ? (
      <Button
        variant="danger"
        size="sm"
        disabled={stop.isPending || run?.cancel_requested}
        title="Fragments finish their current stage, then stop"
        onClick={() => stop.mutate()}
      >
        {run?.cancel_requested ? "Stopping…" : "Stop"}
      </Button>
    ) : canContinue && !paused ? (
      <Button
        variant="accent"
        size="sm"
        disabled={resume.isPending}
        title="Retry the failed and unfinished fragments of the last run"
        onClick={() => resume.mutate()}
      >
        {resume.isPending ? "Continuing…" : "Continue"}
      </Button>
    ) : !allDone && !paused ? (
      <Button variant="accent" size="sm" disabled={start.isPending} onClick={() => startRun(null)}>
        {start.isPending
          ? "Starting…"
          : doneCount > 0 || bookFinished > 0
            ? `Translate the rest${restCost}`
            : `Translate the book${restCost}`}
      </Button>
    ) : null;

  const pausedNotice = paused ? (
    <CostGuardNotice
      state={guard}
      paused
      showSpent={false}
      busy={resume.isPending}
      onContinue={() => resume.mutate()}
      onContinueWithoutLimit={() => resume.mutate({ costLimit: false })}
    />
  ) : null;
  const runError = run?.error_message && !running ? run.error_message : null;
  const notice =
    pausedNotice || error || runError ? (
      <div className="space-y-2">
        {pausedNotice}
        {error && (
          <p className="text-sm text-danger" role="alert">
            {error}
          </p>
        )}
        {runError && <p className="text-sm text-danger">{runError}</p>}
      </div>
    ) : null;

  const settings = (
    <>
      <ModelPicker choice={translationModel} disabled={running} />
      {restEstimate.data && <Pipeline estimate={restEstimate.data} />}
      {restEstimate.data && (
        <p className="mt-2 text-xs leading-relaxed text-ink-400">
          {retranslate || doneCount === 0 ? "The whole book" : "The rest of the book"}: about{" "}
          {formatNumber(restEstimate.data.fragment_count)} fragment
          {restEstimate.data.fragment_count === 1 ? "" : "s"} ·{" "}
          {formatNumber(restEstimate.data.word_count)} words · {restEstimate.data.stages.length}{" "}
          call{restEstimate.data.stages.length === 1 ? "" : "s"} per fragment · ~
          {formatNumber(restEstimate.data.total_tokens)} tokens ·{" "}
          <span className="text-accent">≈ ${restEstimate.data.cost_usd.toFixed(2)}</span>. A rough
          estimate; thinking tokens vary by model.
        </p>
      )}
      <label className="mt-4 flex items-center gap-2 text-[12.5px] text-ink-300">
        <input
          type="checkbox"
          checked={retranslate}
          onChange={(e) => {
            setRetranslate(e.target.checked);
            // Finished chapters can only stay picked while translating again.
            if (!e.target.checked) setSelected(selected.filter((id) => !isDone(id)));
          }}
          className="accent-[var(--color-accent)]"
        />
        Translate again, including fragments that already have a final English version
      </label>
      {retranslate && (
        <div className="mt-3">
          <Button
            variant="ghost"
            size="sm"
            className="border border-ink-700"
            disabled={running || start.isPending || missing.length > 0}
            onClick={() => startRun(null)}
          >
            Translate the whole book again
          </Button>
        </div>
      )}
    </>
  );

  return (
    <TermProvider
      terms={terms.data?.terms ?? NO_TERMS}
      sourceSpans={terms.data?.paragraphs ?? NO_SPANS}
      onOpenTerm={onOpenTerm}
    >
      <div className={BOOK_PANEL_SURFACE}>
        <div className={cn(BOOK_PANEL_CONTAINER, "py-8")}>
          <StepRunBar
            label="Translation run"
            status={barStatus}
            summary={summaryText}
            meta={meta}
            cost={guard}
            action={action}
            notice={notice}
            settings={settings}
          />

          {translation.isError && (
            <p className="mt-6 text-sm text-danger">Could not load the translation.</p>
          )}

          <ChapterTable
            book={book}
            status={status}
            selected={selected}
            retranslate={retranslate}
            readingId={reading?.id ?? null}
            isDone={isDone}
            onToggle={toggle}
            onRead={openChapter}
          />

          {selected.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-accent bg-accent-soft px-4 py-2.5">
              <p className="min-w-0 flex-1 text-[13px] text-ink-100">
                {selected.length} chapter{selected.length === 1 ? "" : "s"} picked
                {selectionEstimate.data && (
                  <span className="text-ink-400">
                    {" "}
                    · {formatNumber(selectionEstimate.data.fragment_count)} fragment
                    {selectionEstimate.data.fragment_count === 1 ? "" : "s"} · ~$
                    {selectionEstimate.data.cost_usd.toFixed(2)}
                  </span>
                )}
              </p>
              <Button variant="ghost" size="sm" onClick={() => setSelected([])}>
                Clear
              </Button>
              <Button
                variant="accent"
                size="sm"
                disabled={running || start.isPending || missing.length > 0}
                title={running ? "Wait for the current run to finish" : undefined}
                onClick={() => startRun(selected)}
              >
                {start.isPending
                  ? "Starting…"
                  : `Translate ${selected.length} chapter${selected.length === 1 ? "" : "s"}`}
              </Button>
            </div>
          )}

          <div ref={readingRef} className="scroll-mt-4">
            {reading && (
              <div className="mt-10 flex flex-wrap items-center gap-3">
                <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">Show</p>
                <div className="inline-flex rounded-lg border border-ink-700 bg-ink-900 p-0.5">
                  {visibleStages.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      title={s.hint}
                      onClick={() => setStage(s.id)}
                      aria-pressed={stage === s.id}
                      className={cn(
                        "rounded-md px-3 py-1 text-[12.5px] transition-colors",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                        stage === s.id
                          ? "bg-ink-700 text-ink-50"
                          : "text-ink-400 hover:text-ink-100",
                      )}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
                <ExportLinks
                  bookId={book.id}
                  stage={stage}
                  blockingPassages={blockingPassages}
                  ready={exportReady}
                  onReview={() => onSelectTab("review")}
                />
              </div>
            )}

            {reading && (
              <>
                <ChapterBlock
                  key={reading.id}
                  label={`Chapter ${book.chapters.indexOf(reading) + 1}`}
                  sourceTitle={reading.title}
                  paragraphs={reading.paragraphs}
                  translation={byChapter.get(reading.id)!}
                  stage={stage}
                />
                <ChapterPager
                  chapters={readable}
                  current={reading.id}
                  number={(id) => book.chapters.findIndex((c) => c.id === id) + 1}
                  onOpen={openChapter}
                />
              </>
            )}
          </div>

          {translation.data && readable.length === 0 && missing.length === 0 && (
            <p className="mt-10 text-center text-sm text-ink-400">
              Nothing translated yet. Pick a chapter in the table to try the translation on a small
              piece first.
            </p>
          )}
        </div>
      </div>
    </TermProvider>
  );
}

const NO_TERMS: GlossaryTerm[] = [];
const NO_SPANS: Record<string, TermSpan[]> = {};

// ─── Chapter table ──────────────────────────────────────

interface ChapterStatus {
  /** Fragments in the chapter; 0 before the first run splits the book. */
  total: number;
  /** Fragments with a final English version. */
  finished: number;
  /** Fragments with English at any stage. */
  withText: number;
  running: boolean;
  failed: number;
  /** Translator notes on the final English. */
  notes: number;
}

function chapterStatus(ch: ChapterTranslation | undefined): ChapterStatus {
  const frags = ch?.fragments ?? [];
  return {
    total: frags.length,
    finished: frags.filter((f) => f.stages.polish).length,
    withText: frags.filter((f) => Object.keys(f.stages).length > 0).length,
    running: frags.some(
      (f) => f.run_status?.status === "running" || f.run_status?.status === "pending",
    ),
    failed: frags.filter((f) => f.run_status?.status === "failed").length,
    notes: frags.reduce((n, f) => n + (f.stages.polish?.notes.length ?? 0), 0),
  };
}

function ChapterTable({
  book,
  status,
  selected,
  retranslate,
  readingId,
  isDone,
  onToggle,
  onRead,
}: {
  book: BookDetail;
  status: Map<string, ChapterStatus>;
  selected: string[];
  retranslate: boolean;
  readingId: string | null;
  isDone: (id: string) => boolean;
  onToggle: (id: string) => void;
  onRead: (id: string) => void;
}) {
  return (
    <section className="mt-8" aria-labelledby="chapters-heading">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 id="chapters-heading" className="font-serif text-2xl font-semibold text-ink-50">
          Chapters
        </h2>
        <p className="text-xs text-ink-500">Tick chapters to translate just those.</p>
      </div>
      <div className="max-h-[26rem] overflow-y-auto rounded-lg border border-ink-800 bg-ink-900">
        <ul className="divide-y divide-ink-800">
          {book.chapters.map((c, idx) => {
            const st = status.get(c.id) ?? chapterStatus(undefined);
            const done = isDone(c.id);
            const locked = done && !retranslate;
            const isReading = c.id === readingId;
            return (
              <li
                key={c.id}
                className={cn(
                  "flex items-center gap-3 px-3 py-2 text-[13px]",
                  isReading && "bg-ink-800",
                )}
              >
                <input
                  type="checkbox"
                  checked={selected.includes(c.id)}
                  disabled={locked}
                  onChange={() => onToggle(c.id)}
                  aria-label={`Pick chapter ${idx + 1}`}
                  title={
                    locked
                      ? "Already translated. Tick “Translate again” under Settings to include it."
                      : undefined
                  }
                  className="accent-[var(--color-accent)] disabled:opacity-40"
                />
                <span className="w-6 shrink-0 font-mono text-[11px] tabular-nums text-ink-500">
                  {String(idx + 1).padStart(2, "0")}
                </span>
                <span className="min-w-0 flex-1 truncate text-ink-200" title={c.title ?? undefined}>
                  {c.title ?? `Chapter ${idx + 1}`}
                </span>
                <ChapterState st={st} done={done} />
                <span className="w-14 shrink-0 text-right">
                  {st.withText > 0 && (
                    <button
                      type="button"
                      onClick={() => onRead(c.id)}
                      aria-current={isReading || undefined}
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[12px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                        isReading ? "text-ink-50" : "text-accent hover:underline",
                      )}
                    >
                      {isReading ? "Reading" : "Read"}
                    </button>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

function ChapterState({ st, done }: { st: ChapterStatus; done: boolean }) {
  const cls = "w-44 shrink-0 whitespace-nowrap font-mono text-[10.5px] tabular-nums";
  const notes = st.notes > 0 ? ` · ${st.notes} note${st.notes === 1 ? "" : "s"}` : "";
  if (st.running) {
    return (
      <span className={cn(cls, "inline-flex items-center gap-1 text-accent")}>
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
        translating
      </span>
    );
  }
  if (done) {
    return (
      <span className={cn(cls, "inline-flex items-center gap-1 text-success")}>
        <CheckCircle2 className="h-3 w-3" aria-hidden />
        translated{notes}
      </span>
    );
  }
  if (st.failed > 0) {
    return (
      <span className={cn(cls, "text-danger")}>
        {st.finished}/{st.total} · {st.failed} failed
      </span>
    );
  }
  if (st.finished > 0) {
    return (
      <span className={cn(cls, "text-warning")} title="Fragments with a final English version">
        {st.finished}/{st.total}
        {notes}
      </span>
    );
  }
  return <span className={cn(cls, "text-ink-500")}>not started</span>;
}

/** Previous and next chapter that have English, under the one you read. */
function ChapterPager({
  chapters,
  current,
  number,
  onOpen,
}: {
  chapters: BookDetail["chapters"];
  current: string;
  number: (id: string) => number;
  onOpen: (id: string) => void;
}) {
  const i = chapters.findIndex((c) => c.id === current);
  const prev = i > 0 ? chapters[i - 1] : null;
  const next = i >= 0 && i < chapters.length - 1 ? chapters[i + 1] : null;
  if (!prev && !next) return null;
  return (
    <nav
      aria-label="Other translated chapters"
      className="mt-10 flex items-center justify-between border-t border-ink-800 pt-4"
    >
      {prev ? (
        <Button variant="ghost" size="sm" onClick={() => onOpen(prev.id)}>
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
          Chapter {number(prev.id)}
        </Button>
      ) : (
        <span />
      )}
      {next && (
        <Button variant="ghost" size="sm" onClick={() => onOpen(next.id)}>
          Chapter {number(next.id)}
          <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </Button>
      )}
    </nav>
  );
}

function ExportLinks({
  bookId,
  stage,
  blockingPassages,
  ready,
  onReview,
}: {
  bookId: string;
  stage: TranslationStage;
  blockingPassages: number;
  ready: boolean;
  onReview: () => void;
}) {
  return (
    <div className="ml-auto flex items-center gap-1">
      <p
        className="mr-1 font-mono text-[10px] uppercase tracking-wider text-ink-500"
        title="Downloads the translated chapters at the stage shown. Missing fragments fall back to an earlier stage, or are marked as not translated."
      >
        Export English · {STAGES.find((s) => s.id === stage)?.label.toLowerCase()}
      </p>
      {blockingPassages > 0 && (
        <button
          type="button"
          onClick={onReview}
          className="mr-1 rounded text-[12px] text-warning underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          title="These passages break their rule and have no checked translation. Until you decide on them in Review, an export is a draft and its file name says DRAFT."
        >
          {blockingPassages} passage{blockingPassages === 1 ? "" : "s"} need a decision
        </button>
      )}
      {(["pdf", "epub", "docx"] as const).map((fmt) =>
        ready ? (
          <a
            key={fmt}
            href={translationExportUrl(bookId, fmt, stage, blockingPassages > 0)}
            download
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[12.5px] font-medium",
              "text-ink-100 hover:bg-ink-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
            )}
          >
            <Download className="h-3.5 w-3.5" aria-hidden />
            {blockingPassages > 0 ? `Draft ${fmt.toUpperCase()}` : fmt.toUpperCase()}
          </a>
        ) : (
          <span
            key={fmt}
            aria-disabled="true"
            className="inline-flex h-8 items-center gap-1.5 px-3 text-[12.5px] font-medium text-ink-500"
          >
            <Download className="h-3.5 w-3.5" aria-hidden />
            {fmt.toUpperCase()}
          </span>
        ),
      )}
    </div>
  );
}

/** The steps the next run will take, e.g. "Draft gpt-6-luna → Final gpt-6.1-sol". */
function Pipeline({ estimate }: { estimate: TranslationEstimate }) {
  const label = (id: TranslationStage) => STAGES.find((s) => s.id === id)?.label ?? id;
  return (
    <p className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[12px] text-ink-300">
      <span className="font-mono text-[10px] uppercase tracking-wider text-ink-500">Next run</span>
      {estimate.stages.map((s, i) => (
        <span key={s.stage} className="inline-flex items-center gap-1.5">
          {i > 0 && <span className="text-ink-600">→</span>}
          <span>
            {label(s.stored_as)}{" "}
            <span className="font-mono text-[11px] text-ink-100">{s.model}</span>
            {s.thinking && <span className="text-ink-500"> ({s.thinking} thinking)</span>}
          </span>
        </span>
      ))}
      {estimate.service_tier && (
        <span className="text-ink-500">· {estimate.service_tier} tier</span>
      )}
    </p>
  );
}

function errorText(error: Error | null, isError: boolean, fallback: string): string | null {
  if (!isError) return null;
  return error instanceof ApiError ? error.detail : fallback;
}

// ─── Chapter ────────────────────────────────────────────

function ChapterBlock({
  label,
  sourceTitle,
  paragraphs,
  translation,
  stage,
}: {
  label: string;
  sourceTitle: string | null;
  paragraphs: BookDetail["chapters"][number]["paragraphs"];
  translation: ChapterTranslation;
  stage: TranslationStage;
}) {
  const sourceById = useMemo(() => new Map(paragraphs.map((p) => [p.id, p.text])), [paragraphs]);
  const metrics = translation.metrics[stage];
  // The chapter heading (POV, title, epigraph) is translated with the first
  // fragment under the pseudo paragraph id `title:<chapter id>`.
  const titleId = `title:${translation.chapter_id}`;
  const translatedTitle = translation.fragments
    .flatMap((f) => f.stages[stage]?.paragraphs ?? [])
    .find((p) => p.paragraph_id === titleId)?.text;

  // Agreed glossary terms the English of this stage does not use.
  const termCtx = useTerms();
  const termWarnings = useMemo(() => {
    if (!termCtx) return 0;
    let n = 0;
    for (const f of translation.fragments) {
      for (const p of f.stages[stage]?.paragraphs ?? []) {
        const spans = termCtx.sourceSpans[p.paragraph_id] ?? [];
        if (spans.length) n += englishTerms(p.text, spans, termCtx.termsById).missing.length;
      }
    }
    return n;
  }, [termCtx, translation.fragments, stage]);

  return (
    <section className="mt-10">
      <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-ink-800 pb-2">
        <h2 className="font-serif text-2xl text-accent">{label}</h2>
        {metrics && <MetricsRow metrics={metrics} termWarnings={termWarnings} />}
      </div>
      {sourceTitle && (
        <div className="mt-4 grid gap-x-8 gap-y-1 md:grid-cols-2">
          <p className="whitespace-pre-line font-serif text-[14px] italic leading-relaxed text-ink-400">
            {sourceTitle}
          </p>
          <p className="whitespace-pre-line font-serif text-[14px] italic leading-relaxed text-ink-100">
            <HighlightedText text={translatedTitle ?? ""} spans={NO_SPAN_LIST} />
          </p>
        </div>
      )}
      {translation.fragments.map((f) => (
        <FragmentBlock key={f.fragment_id} fragment={f} stage={stage} sourceById={sourceById} />
      ))}
    </section>
  );
}

function MetricsRow({ metrics, termWarnings }: { metrics: StyleMetrics; termWarnings: number }) {
  const items: { label: string; value: string; over: boolean }[] = [
    {
      label: "She/He openers",
      value: `${metrics.she_he_pct}%`,
      over: metrics.she_he_pct > TARGETS.shePct,
    },
    {
      label: "Ellipses /1k",
      value: String(metrics.ellipses_per_1k),
      over: metrics.ellipses_per_1k > TARGETS.ellipses,
    },
    {
      label: "Dashes /1k",
      value: String(metrics.dashes_per_1k),
      over: metrics.dashes_per_1k > TARGETS.dashes,
    },
    { label: "Stock phrases", value: String(metrics.stock_total), over: metrics.stock_total > 0 },
    {
      label: "Repeated words /1k",
      value: String(metrics.repetitions_per_1k ?? "—"),
      over: false,
    },
    {
      label: "Even-length runs",
      value: String(metrics.even_runs ?? "—"),
      over: (metrics.even_runs ?? 0) > 0,
    },
    { label: "Term warnings", value: String(termWarnings), over: termWarnings > 0 },
  ];
  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10.5px]">
      {items.map((i) => (
        <div key={i.label} className="flex gap-1.5" title="Target: see the final-edit brief">
          <dt className="text-ink-500">{i.label}</dt>
          <dd className={cn("tabular-nums", i.over ? "text-warning" : "text-ink-200")}>
            {i.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Polish and English side by side, with glossary terms marked on both. */
function ParagraphPair({
  source,
  english,
  paragraphId,
}: {
  source: string;
  english: string;
  paragraphId: string;
}) {
  const ctx = useTerms();
  const sourceSpans = ctx?.sourceSpans[paragraphId] ?? NO_SPAN_LIST;
  const { spans, missing } = useMemo(
    () =>
      ctx && sourceSpans.length
        ? englishTerms(english, sourceSpans, ctx.termsById)
        : { spans: NO_SPAN_LIST, missing: [] },
    [ctx, english, sourceSpans],
  );
  const warnIds = useMemo(() => new Set(missing.map((t) => t.id)), [missing]);
  return (
    <>
      <p className="font-serif text-[15px] leading-relaxed text-ink-400">
        <HighlightedText text={source} spans={sourceSpans} warnIds={warnIds} />
      </p>
      <div>
        <p className="whitespace-pre-line font-serif text-[15px] leading-relaxed text-ink-100">
          <HighlightedText text={english} spans={spans} />
        </p>
        <MissingTerms missing={missing} />
      </div>
    </>
  );
}

const NO_SPAN_LIST: TermSpan[] = [];

function FragmentBlock({
  fragment,
  stage,
  sourceById,
}: {
  fragment: TranslationFragment;
  stage: TranslationStage;
  sourceById: Map<string, string>;
}) {
  const output = fragment.stages[stage];
  const rs = fragment.run_status;

  if (!output) {
    const label =
      rs?.status === "running"
        ? `Translating${rs.last_stage ? ` · ${STAGES.find((s) => s.id === rs.last_stage)?.label.toLowerCase()} done` : ""}…`
        : rs?.status === "failed"
          ? "Failed"
          : rs?.status === "pending"
            ? "Waiting"
            : "Not translated at this stage yet";
    return (
      <div className="mt-4 rounded-lg border border-dashed border-ink-700 px-4 py-3 text-[12.5px] text-ink-400">
        <span className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
          Fragment {fragment.position + 1} · {formatNumber(fragment.word_count)} words
        </span>
        <p className={cn("mt-1", rs?.status === "failed" && "text-danger")}>
          {rs?.status === "running" && <Loader2 className="mr-1.5 inline h-3 w-3 animate-spin" />}
          {label}
          {rs?.error_message && `: ${rs.error_message}`}
        </p>
      </div>
    );
  }

  const textById = new Map(output.paragraphs.map((p) => [p.paragraph_id, p.text]));
  const group = <T extends { paragraph_id: string | null }>(items: T[]) => {
    const m = new Map<string, T[]>();
    for (const it of items) {
      const key = it.paragraph_id ?? "";
      m.set(key, [...(m.get(key) ?? []), it]);
    }
    return m;
  };
  const notes = group<TranslatorNote>(output.notes);
  const edits = group<DeclaredEdit>(output.declared_edits);
  const qa = group<QaIssue>(output.qa);

  return (
    <div className="mt-6">
      <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-ink-500">
        Fragment {fragment.position + 1}
        {output.model && <span className="normal-case tracking-normal"> · {output.model}</span>}
      </p>
      <div className="space-y-4">
        {fragment.paragraph_ids.map((pid) => (
          <div key={pid} className="grid gap-x-8 gap-y-1 md:grid-cols-2">
            <ParagraphPair
              source={sourceById.get(pid) ?? ""}
              english={textById.get(pid) ?? ""}
              paragraphId={pid}
            />
            <div className="md:col-start-2">
              <Annotations notes={notes.get(pid)} edits={edits.get(pid)} qa={qa.get(pid)} />
            </div>
          </div>
        ))}
      </div>
      {(notes.get("") ?? []).length > 0 && (
        <Annotations notes={notes.get("")} edits={undefined} qa={undefined} />
      )}
    </div>
  );
}

function Annotations({
  notes,
  edits,
  qa,
}: {
  notes: TranslatorNote[] | undefined;
  edits: DeclaredEdit[] | undefined;
  qa: QaIssue[] | undefined;
}) {
  if (!notes?.length && !edits?.length && !qa?.length) return null;
  return (
    <ul className="mt-2 space-y-1.5">
      {notes?.map((n, i) => (
        <li
          key={`n${i}`}
          className="rounded-md border-l-2 border-accent bg-ink-900 px-3 py-1.5 text-[12px] leading-snug text-ink-300"
        >
          <span className="font-mono text-[10px] uppercase tracking-wider text-accent">
            {NOTE_LABELS[n.kind] ?? n.kind}
          </span>{" "}
          {n.note}
        </li>
      ))}
      {edits?.map((e, i) => (
        <li
          key={`e${i}`}
          className="rounded-md border-l-2 border-warning bg-ink-900 px-3 py-1.5 text-[12px] leading-snug text-ink-300"
        >
          <span className="font-mono text-[10px] uppercase tracking-wider text-warning">
            {EDIT_LABELS[e.kind] ?? e.kind}
          </span>{" "}
          <span className="text-ink-500 line-through">{e.before}</span> → {e.after}
          <span className="text-ink-500"> · {e.why}</span>
        </li>
      ))}
      {qa?.map((q, i) => (
        <li
          key={`q${i}`}
          className="flex items-start gap-1.5 rounded-md bg-danger-surface px-3 py-1.5 text-[12px] leading-snug text-danger"
        >
          <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
          {q.detail}
        </li>
      ))}
    </ul>
  );
}
