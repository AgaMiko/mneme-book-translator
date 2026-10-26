import { TriangleAlert } from "lucide-react";
import { Fragment, useMemo, useState, type ReactNode } from "react";

import type { GlossaryTerm, TermSpan } from "@/lib/api/client";
import { cn } from "@/lib/utils";

import { parseInline } from "./inline";
import { TermContext, useTerms } from "./terms";

/**
 * Glossary terms in the Translation tab and the manuscript.
 *
 * The server finds terms in each Polish paragraph, case forms included
 * (`GET /books/{id}/translation/terms`). Here the English side is matched by
 * the term's agreed target, and a term whose target is missing from the
 * English paragraph is shown as a warning. Character names are not warned
 * about: English often replaces a name with "she" or "he".
 *
 * Hovering a term shows a short card; clicking opens the term in the
 * glossary. The manuscript also shows terms not reviewed yet, with a
 * fainter underline.
 */

const TYPE_LABELS: Record<string, string> = {
  character_name: "Character",
  place_name: "Place",
  organization: "Organization",
  lore_term: "Lore",
  cultural_term: "Cultural",
  specialized_usage: "Specialized",
  epithet: "Epithet",
  other: "Other",
};

export function TermProvider({
  terms,
  sourceSpans,
  onOpenTerm,
  children,
}: {
  terms: GlossaryTerm[];
  sourceSpans: Record<string, TermSpan[]>;
  onOpenTerm: (termId: string) => void;
  children: ReactNode;
}) {
  const value = useMemo(
    () => ({ termsById: new Map(terms.map((t) => [t.id, t])), sourceSpans, onOpenTerm }),
    [terms, sourceSpans, onOpenTerm],
  );
  return <TermContext.Provider value={value}>{children}</TermContext.Provider>;
}

/**
 * Text with Markdown italics/bold rendered and its term spans turned into
 * hoverable, clickable marks. Spans are raw-text offsets; a span that crosses
 * an italic boundary is drawn as two marks.
 */
export function HighlightedText({
  text,
  spans,
  warnIds,
}: {
  text: string;
  spans: TermSpan[];
  warnIds?: Set<string>;
}) {
  const ctx = useTerms();
  const runs = useMemo(() => parseInline(text), [text]);
  const usable = ctx ? spans.filter((s) => ctx.termsById.has(s.term_id)) : [];
  return (
    <>
      {runs.map((run, r) => {
        const pieces: ReactNode[] = [];
        let pos = run.start;
        for (const [i, s] of usable.entries()) {
          const a = Math.max(s.start, run.start);
          const b = Math.min(s.end, run.end);
          if (b <= a || a < pos) continue;
          if (a > pos) pieces.push(text.slice(pos, a));
          const term = ctx!.termsById.get(s.term_id)!;
          pieces.push(
            <TermMark key={`${r}-${i}`} term={term} warn={warnIds?.has(term.id) ?? false}>
              {text.slice(a, b)}
            </TermMark>,
          );
          pos = b;
        }
        if (pos < run.end) pieces.push(text.slice(pos, run.end));
        let node: ReactNode = pieces;
        if (run.italic) node = <em>{node}</em>;
        if (run.bold) node = <strong className="font-semibold">{node}</strong>;
        return <Fragment key={r}>{node}</Fragment>;
      })}
    </>
  );
}

function TermMark({
  term,
  warn,
  children,
}: {
  term: GlossaryTerm;
  warn: boolean;
  children: ReactNode;
}) {
  const ctx = useTerms();
  const [open, setOpen] = useState(false);
  const pending = term.status === "proposed";
  return (
    <span
      className="relative"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onClick={() => ctx?.onOpenTerm(term.id)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className={cn(
          "cursor-pointer rounded-sm underline decoration-dotted underline-offset-4",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          warn
            ? "bg-warning-surface text-warning decoration-warning"
            : pending
              ? "decoration-ink-700 hover:bg-ink-800 hover:decoration-ink-500"
              : "decoration-ink-500 hover:bg-ink-800 hover:decoration-accent",
        )}
      >
        {children}
      </button>
      {open && (
        <span
          role="tooltip"
          className={cn(
            "absolute bottom-full left-0 z-20 mb-1.5 block w-72 rounded-lg border border-ink-700",
            "bg-ink-900 px-3 py-2 text-left font-sans text-[12px] leading-snug text-ink-200 shadow-lg",
          )}
        >
          <span className="block">
            <span className="font-medium text-ink-50">{term.source}</span>
            <span className="text-ink-500"> → </span>
            <span className="font-medium text-accent">{term.target}</span>
          </span>
          <span className="mt-0.5 block font-mono text-[10px] uppercase tracking-wider text-ink-500">
            {TYPE_LABELS[term.term_type] ?? term.term_type}
            {pending && " · not reviewed yet"}
          </span>
          {term.note && <span className="mt-1 block text-ink-400">{term.note}</span>}
          {warn && (
            <span className="mt-1 block text-warning">
              The English paragraph does not use “{term.target}”.
            </span>
          )}
          <span className="mt-1 block text-[11px] text-ink-500">Click to open in the glossary</span>
        </span>
      )}
    </span>
  );
}

/** One line under an English paragraph listing agreed terms it does not use. */
export function MissingTerms({ missing }: { missing: GlossaryTerm[] }) {
  const ctx = useTerms();
  if (missing.length === 0) return null;
  return (
    <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-warning">
      <TriangleAlert className="h-3 w-3 shrink-0" aria-hidden />
      <span>Agreed term not used:</span>
      {missing.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => ctx?.onOpenTerm(t.id)}
          className="rounded-sm underline decoration-dotted underline-offset-4 hover:text-ink-50"
        >
          {t.source} → {t.target}
        </button>
      ))}
    </p>
  );
}
