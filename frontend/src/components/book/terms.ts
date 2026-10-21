import { createContext, useContext } from "react";

import type { GlossaryTerm, TermSpan } from "@/lib/api/client";

/**
 * Shared data and matching for glossary-term highlighting in the
 * Translation tab (components in `TermHighlight.tsx`).
 */

/** Character names are not warned about: English often uses "she" or "he" instead. */
const NO_WARNING_TYPES = new Set(["character_name"]);

export interface TermContextValue {
  termsById: Map<string, GlossaryTerm>;
  sourceSpans: Record<string, TermSpan[]>;
  onOpenTerm: (termId: string) => void;
}

export const TermContext = createContext<TermContextValue | null>(null);

export function useTerms(): TermContextValue | null {
  return useContext(TermContext);
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Singular and plural forms of an English target: Shapers/Shaper, Academy/Academies. */
function targetForms(target: string): string[] {
  const t = target.replace(/^the\s+/i, "").trim();
  if (!t) return [];
  const forms = new Set([t]);
  if (/ies$/i.test(t)) forms.add(t.slice(0, -3) + "y");
  else if (/[sx]es$/i.test(t)) forms.add(t.slice(0, -2));
  else if (/s$/i.test(t) && !/ss$/i.test(t)) forms.add(t.slice(0, -1));
  if (/[^aeiou]y$/i.test(t)) forms.add(t.slice(0, -1) + "ies");
  return [...forms].sort((a, b) => b.length - a.length);
}

/** Spans of a term's English target: case-insensitive, whole words, singular or plural, 's. */
function targetSpans(text: string, term: GlossaryTerm): TermSpan[] {
  const forms = targetForms(term.target);
  if (!forms.length) return [];
  const re = new RegExp(
    `(?<![\\p{L}\\p{N}])(?:${forms.map(escapeRegExp).join("|")})(?:es|s|'s|\u2019s)?(?![\\p{L}\\p{N}])`,
    "giu",
  );
  const out: TermSpan[] = [];
  for (const m of text.matchAll(re)) {
    out.push({ term_id: term.id, start: m.index ?? 0, end: (m.index ?? 0) + m[0].length });
  }
  return out;
}

/** Where the English uses the agreed targets, and which expected terms are missing. */
export function englishTerms(
  text: string,
  sourceSpans: TermSpan[],
  termsById: Map<string, GlossaryTerm>,
): { spans: TermSpan[]; missing: GlossaryTerm[] } {
  const ids = [...new Set(sourceSpans.map((s) => s.term_id))];
  const all: TermSpan[] = [];
  const missing: GlossaryTerm[] = [];
  for (const id of ids) {
    const term = termsById.get(id);
    if (!term) continue;
    const found = targetSpans(text, term);
    if (found.length) all.push(...found);
    else if (!NO_WARNING_TYPES.has(term.term_type)) missing.push(term);
  }
  // Longest first at the same start, then drop overlaps.
  all.sort((a, b) => a.start - b.start || b.end - a.end);
  const spans: TermSpan[] = [];
  let lastEnd = -1;
  for (const s of all) {
    if (s.start >= lastEnd) {
      spans.push(s);
      lastEnd = s.end;
    }
  }
  return { spans, missing };
}
