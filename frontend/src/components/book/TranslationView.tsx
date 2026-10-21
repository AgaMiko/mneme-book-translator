import {
  AlertCircle,
  CheckCircle2,
  Circle,
  Download,
  Loader2,
  PauseCircle,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
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
  type TranslationRun,
  type TermSpan,
  type TranslationStage,
  type TranslatorNote,
  translationExportUrl,
} from "@/lib/api/client";
import {
  useContinueTranslation,
  useStartTranslation,
  useStopTranslation,
  useTranslation,
  useTranslationEstimate,
  useTranslationTerms,
} from "@/lib/api/hooks";
import { cn, formatNumber } from "@/lib/utils";

import { BOOK_PANEL_CONTAINER, BOOK_PANEL_SURFACE } from "./layout";
import { HighlightedText, MissingTerms, TermProvider } from "./TermHighlight";
import { englishTerms, useTerms } from "./terms";

interface Props {
  book: BookDetail;
  /** Open a glossary term in the Glossary tab. */
  onOpenTerm: (termId: string) => void;
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
 * Step 5: translate fragments and read the result next to the source. By
 * default each fragment is translated in one step straight into the final
 * English; two- and three-step modes add a faithful draft and a separate
 * line edit. The run card shows the pipeline the next run will use and
 * starts, stops and continues runs; the stage switch shows whichever of the
 * draft, line-edited and final texts exist.
 */
export function TranslationView({ book, onOpenTerm }: Props) {
  const translation = useTranslation(book.id);
  const terms = useTranslationTerms(book.id);
  const [stage, setStage] = useState<TranslationStage>("polish");
  const [selected, setSelected] = useState<string[]>([]);

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

  const translatedChapters = book.chapters.filter((c) => {
    const ch = byChapter.get(c.id);
    return ch?.fragments.some((f) => Object.keys(f.stages).length > 0 || f.run_status);
  });

  return (
    <TermProvider
      terms={terms.data?.terms ?? NO_TERMS}
      sourceSpans={terms.data?.paragraphs ?? NO_SPANS}
      onOpenTerm={onOpenTerm}
    >
      <div className={BOOK_PANEL_SURFACE}>
        <div className={cn(BOOK_PANEL_CONTAINER, "py-8")}>
          <RunCard
            book={book}
            run={translation.data?.run ?? null}
            selected={selected}
            onSelectedChange={setSelected}
            byChapter={byChapter}
          />

          {translation.isError && (
            <p className="mt-6 text-sm text-danger">Could not load the translation.</p>
          )}

          {translatedChapters.length > 0 && (
            <div className="mt-8 flex flex-wrap items-center gap-3">
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
                      stage === s.id ? "bg-ink-700 text-ink-50" : "text-ink-400 hover:text-ink-100",
                    )}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
              <div className="ml-auto flex items-center gap-1">
                <p
                  className="mr-1 font-mono text-[10px] uppercase tracking-wider text-ink-500"
                  title="Downloads the translated chapters at the stage shown. Missing fragments fall back to an earlier stage, or are marked as not translated."
                >
                  Export English · {STAGES.find((s) => s.id === stage)?.label.toLowerCase()}
                </p>
                {(["pdf", "epub", "docx"] as const).map((fmt) => (
                  <a
                    key={fmt}
                    href={translationExportUrl(book.id, fmt, stage)}
                    download
                    className={cn(
                      "inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[12.5px] font-medium",
                      "text-ink-100 hover:bg-ink-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    )}
                  >
                    <Download className="h-3.5 w-3.5" aria-hidden />
                    {fmt.toUpperCase()}
                  </a>
                ))}
              </div>
            </div>
          )}

          {translatedChapters.map((chapter) => (
            <ChapterBlock
              key={chapter.id}
              label={`Chapter ${book.chapters.indexOf(chapter) + 1}`}
              sourceTitle={chapter.title}
              paragraphs={chapter.paragraphs}
              translation={byChapter.get(chapter.id)!}
              stage={stage}
            />
          ))}

          {translation.data && translatedChapters.length === 0 && (
            <p className="mt-10 text-center text-sm text-ink-400">
              Nothing translated yet. Pick a chapter above to try the pipeline on a small piece
              first.
            </p>
          )}
        </div>
      </div>
    </TermProvider>
  );
}

const NO_TERMS: GlossaryTerm[] = [];
const NO_SPANS: Record<string, TermSpan[]> = {};

// ─── Run card ───────────────────────────────────────────

function RunCard({
  book,
  run,
  selected,
  onSelectedChange,
  byChapter,
}: {
  book: BookDetail;
  run: TranslationRun | null;
  selected: string[];
  onSelectedChange: (ids: string[]) => void;
  byChapter: Map<string, ChapterTranslation>;
}) {
  const [retranslate, setRetranslate] = useState(false);

  // Per chapter: fragments, and how many have a final English version.
  const status = useMemo(() => {
    const m = new Map<string, { total: number; finished: number }>();
    for (const c of book.chapters) {
      const frags = byChapter.get(c.id)?.fragments ?? [];
      m.set(c.id, {
        total: frags.length,
        finished: frags.filter((f) => f.stages.polish).length,
      });
    }
    return m;
  }, [book.chapters, byChapter]);
  const isDone = (id: string) => {
    const st = status.get(id);
    return !!st && st.total > 0 && st.finished === st.total;
  };
  const doneCount = book.chapters.filter((c) => isDone(c.id)).length;
  const allDone = doneCount === book.chapters.length && doneCount > 0;

  // Without "Translate again", a whole-book run skips finished chapters,
  // so the estimate covers only the rest.
  const estimateIds = selected.length
    ? selected
    : retranslate || doneCount === 0
      ? null
      : book.chapters.filter((c) => !isDone(c.id)).map((c) => c.id);
  const estimate = useTranslationEstimate(book.id, estimateIds);
  const start = useStartTranslation(book.id);
  const resume = useContinueTranslation(book.id);
  const stop = useStopTranslation(book.id);

  const running = run?.status === "running";
  const canContinue = run?.status === "failed" || run?.status === "cancelled";
  const glossaryReady = book.glossary_extraction_status === "completed";

  const error =
    errorText(start.error, start.isError, "Could not start the translation.") ??
    errorText(resume.error, resume.isError, "Could not continue the run.") ??
    errorText(stop.error, stop.isError, "Could not stop the run.");

  const done = run ? run.fragments_completed : 0;
  const total = run ? run.fragments_total : 0;
  const pct = total > 0 ? Math.round((100 * done) / total) : 0;

  const toggle = (id: string) =>
    onSelectedChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  return (
    <section className="rounded-lg border border-ink-800 bg-ink-800" aria-label="Translation run">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <RunIcon status={run?.status ?? null} />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] leading-snug text-ink-100">{summary(run)}</p>
          {run && (
            <p className="mt-0.5 font-mono text-[10px] text-ink-500">
              {STAGES.filter((st) => run.models[st.id])
                .map((st) => `${st.label.toLowerCase()}: ${run.models[st.id]}`)
                .join(" · ")}
            </p>
          )}
        </div>
      </div>

      {run && total > 0 && (
        <div className="px-4 pb-3">
          <div className="h-1.5 overflow-hidden rounded-full bg-ink-900">
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="mt-1 font-mono text-[10px] tabular-nums text-ink-500">
            {done}/{total} fragments
            {run.fragments_failed > 0 && (
              <span className="text-danger"> · {run.fragments_failed} failed</span>
            )}
          </p>
        </div>
      )}

      <div className="border-t border-ink-700 px-4 py-4">
        {!glossaryReady && (
          <p className="mb-3 text-sm text-warning">
            The glossary hasn&apos;t been extracted yet. Translation will run without accepted
            terms.
          </p>
        )}

        <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
          Chapters to translate
        </p>
        <div className="mt-2 max-h-48 overflow-y-auto rounded-lg border border-ink-700 bg-ink-900 p-2">
          <label className="flex items-center gap-2 rounded px-2 py-1 text-[12.5px] text-ink-200">
            <input
              type="checkbox"
              checked={selected.length === 0}
              onChange={() => onSelectedChange([])}
              className="accent-[var(--color-accent)]"
            />
            {doneCount > 0 && !retranslate ? "Whole book (untranslated parts)" : "Whole book"}
          </label>
          {book.chapters.map((c, idx) => {
            const st = status.get(c.id) ?? { total: 0, finished: 0 };
            const done = isDone(c.id);
            const locked = done && !retranslate;
            return (
              <label
                key={c.id}
                title={
                  locked
                    ? "Already translated. Tick “Translate again” to include it in a run."
                    : undefined
                }
                className={cn(
                  "flex items-center gap-2 rounded px-2 py-1 text-[12.5px] text-ink-300",
                  locked ? "cursor-not-allowed opacity-50" : "hover:bg-ink-800",
                )}
              >
                <input
                  type="checkbox"
                  checked={selected.includes(c.id)}
                  disabled={locked}
                  onChange={() => toggle(c.id)}
                  className="accent-[var(--color-accent)]"
                />
                <span className="font-mono text-[11px] tabular-nums text-ink-500">
                  {String(idx + 1).padStart(2, "0")}
                </span>
                <span className="min-w-0 flex-1 truncate">{c.title ?? `Chapter ${idx + 1}`}</span>
                {done ? (
                  <span className="inline-flex items-center gap-1 font-mono text-[10px] text-success">
                    <CheckCircle2 className="h-3 w-3" aria-hidden />
                    translated
                  </span>
                ) : st.finished > 0 ? (
                  <span
                    className="font-mono text-[10px] tabular-nums text-ink-400"
                    title="Fragments with a final English version"
                  >
                    {st.finished}/{st.total}
                  </span>
                ) : null}
              </label>
            );
          })}
        </div>

        {estimate.data && <Pipeline estimate={estimate.data} />}

        {estimate.data && (
          <p className="mt-2 text-xs leading-relaxed text-ink-400">
            About {formatNumber(estimate.data.fragment_count)} fragment
            {estimate.data.fragment_count === 1 ? "" : "s"} ·{" "}
            {formatNumber(estimate.data.word_count)} words · {estimate.data.stages.length} call
            {estimate.data.stages.length === 1 ? "" : "s"} per fragment · ~
            {formatNumber(estimate.data.total_tokens)} tokens ·{" "}
            <span className="text-accent">≈ ${estimate.data.cost_usd.toFixed(2)}</span>. A rough
            estimate; thinking tokens vary by model.
          </p>
        )}

        <label className="mt-3 flex items-center gap-2 text-[12.5px] text-ink-300">
          <input
            type="checkbox"
            checked={retranslate}
            onChange={(e) => {
              setRetranslate(e.target.checked);
              // Finished chapters can only stay selected while translating again.
              if (!e.target.checked) onSelectedChange(selected.filter((id) => !isDone(id)));
            }}
            className="accent-[var(--color-accent)]"
          />
          Translate again, including fragments that already have a final English version
        </label>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button
            variant="accent"
            size="sm"
            disabled={running || start.isPending || (allDone && !retranslate && !selected.length)}
            onClick={() =>
              start.mutate({ chapter_ids: selected.length ? selected : null, retranslate })
            }
          >
            {start.isPending
              ? "Starting…"
              : selected.length
                ? `Translate ${selected.length} chapter${selected.length === 1 ? "" : "s"}`
                : allDone && !retranslate
                  ? "Everything is translated"
                  : doneCount > 0 && !retranslate
                    ? "Translate the rest of the book"
                    : "Translate whole book"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={!canContinue || resume.isPending}
            title={
              canContinue ? "Retry failed and unfinished fragments" : "Only after a stop or failure"
            }
            onClick={() => resume.mutate()}
          >
            {resume.isPending ? "Continuing…" : "Continue"}
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={!running || stop.isPending || run?.cancel_requested}
            title="Fragments finish their current stage, then stop"
            onClick={() => stop.mutate()}
          >
            {run?.cancel_requested ? "Stopping…" : "Stop"}
          </Button>
        </div>

        {error && (
          <p className="mt-3 text-sm text-danger" role="alert">
            {error}
          </p>
        )}
        {run?.error_message && !running && (
          <p className="mt-3 text-sm text-danger">{run.error_message}</p>
        )}
      </div>
    </section>
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

function summary(run: TranslationRun | null): string {
  if (!run) return "No translation yet. The next run's steps and models are shown below.";
  const progress = `${run.fragments_completed}/${run.fragments_total} fragments`;
  switch (run.status) {
    case "running":
      return run.cancel_requested
        ? `Stopping after the current stages · ${progress}.`
        : `Translating · ${progress} done.`;
    case "completed":
      return `Translation finished · ${progress}.`;
    case "cancelled":
      return `Stopped · ${progress}. Continue to translate the rest.`;
    case "failed":
      return `Run ended with errors · ${progress}.`;
  }
}

function RunIcon({ status }: { status: TranslationRun["status"] | null }) {
  const cls = "h-4 w-4 shrink-0";
  if (status === "running")
    return <Loader2 className={cn(cls, "animate-spin text-accent")} aria-hidden />;
  if (status === "completed")
    return <CheckCircle2 className={cn(cls, "text-success")} aria-hidden />;
  if (status === "failed") return <AlertCircle className={cn(cls, "text-danger")} aria-hidden />;
  if (status === "cancelled")
    return <PauseCircle className={cn(cls, "text-warning")} aria-hidden />;
  return <Circle className={cn(cls, "text-ink-500")} aria-hidden />;
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
            {translatedTitle ?? ""}
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
