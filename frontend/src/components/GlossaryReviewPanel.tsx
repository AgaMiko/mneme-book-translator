import { useMemo, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Braces,
  Building2,
  ChevronDown,
  Library,
  MapPin,
  Search,
  Shapes,
  Sparkles,
  UserRound,
} from "lucide-react";

import type {
  GlossaryRunMeta,
  GlossarySelectOption,
  GlossaryWorkingEntry,
} from "@/lib/api/client";
import {
  GLOSSARY_EXTRACTION_OVERLAP_WORDS,
  GLOSSARY_EXTRACTION_WINDOW_WORDS,
} from "@/constants/glossaryExtraction";
import { useWorkingGlossary } from "@/lib/api/hooks";
import { cn, formatNumber } from "@/lib/utils";

/** Presentation only — ids and labels come from ``term_type_options`` on the API. */
type TermTypeStyle = {
  Icon: LucideIcon;
  chipOn: string;
  chipOff: string;
  badge: string;
  iconClass: string;
};

const DEFAULT_TERM_STYLE: TermTypeStyle = {
  Icon: Shapes,
  chipOn:
    "border-zinc-500/40 bg-zinc-900/90 text-zinc-200 shadow-sm shadow-black/30 ring-1 ring-zinc-500/20",
  chipOff: "border-ink-700/90 bg-ink-950/60 text-ink-500 opacity-55",
  badge: "border-zinc-600/40 bg-zinc-900/70 text-zinc-200",
  iconClass: "text-zinc-400",
};

const TERM_TYPE_STYLE: Record<string, TermTypeStyle> = {
  character_name: {
    Icon: UserRound,
    chipOn:
      "border-sky-500/45 bg-sky-950/55 text-sky-100 shadow-sm shadow-sky-950/40 ring-1 ring-sky-400/25",
    chipOff: "border-ink-700/90 bg-ink-950/60 text-ink-500 opacity-55",
    badge: "border-sky-500/35 bg-sky-950/45 text-sky-100",
    iconClass: "text-sky-400",
  },
  place_name: {
    Icon: MapPin,
    chipOn:
      "border-emerald-500/45 bg-emerald-950/55 text-emerald-100 shadow-sm shadow-emerald-950/40 ring-1 ring-emerald-400/25",
    chipOff: "border-ink-700/90 bg-ink-950/60 text-ink-500 opacity-55",
    badge: "border-emerald-500/35 bg-emerald-950/45 text-emerald-100",
    iconClass: "text-emerald-400",
  },
  organization: {
    Icon: Building2,
    chipOn:
      "border-blue-500/45 bg-blue-950/55 text-blue-100 shadow-sm shadow-blue-950/40 ring-1 ring-blue-400/25",
    chipOff: "border-ink-700/90 bg-ink-950/60 text-ink-500 opacity-55",
    badge: "border-blue-500/35 bg-blue-950/45 text-blue-100",
    iconClass: "text-blue-400",
  },
  lore_term: {
    Icon: Sparkles,
    chipOn:
      "border-violet-500/45 bg-violet-950/55 text-violet-100 shadow-sm shadow-violet-950/40 ring-1 ring-violet-400/25",
    chipOff: "border-ink-700/90 bg-ink-950/60 text-ink-500 opacity-55",
    badge: "border-violet-500/35 bg-violet-950/45 text-violet-100",
    iconClass: "text-violet-400",
  },
  cultural_term: {
    Icon: Library,
    chipOn:
      "border-amber-500/45 bg-amber-950/55 text-amber-100 shadow-sm shadow-amber-950/40 ring-1 ring-amber-400/20",
    chipOff: "border-ink-700/90 bg-ink-950/60 text-ink-500 opacity-55",
    badge: "border-amber-500/35 bg-amber-950/45 text-amber-100",
    iconClass: "text-amber-400",
  },
  specialized_usage: {
    Icon: Braces,
    chipOn:
      "border-rose-500/40 bg-rose-950/50 text-rose-100 shadow-sm shadow-rose-950/35 ring-1 ring-rose-400/25",
    chipOff: "border-ink-700/90 bg-ink-950/60 text-ink-500 opacity-55",
    badge: "border-rose-500/35 bg-rose-950/45 text-rose-100",
    iconClass: "text-rose-300",
  },
};

function termTypeStyleFor(id: string): TermTypeStyle {
  return TERM_TYPE_STYLE[id] ?? DEFAULT_TERM_STYLE;
}

function canonicalTermTypeId(raw: string, optionIds: readonly string[]): string {
  const mapped = raw === "magic_term" ? "lore_term" : raw;
  return optionIds.includes(mapped) ? mapped : "other";
}

function labelSuggestion(raw: string, options: GlossarySelectOption[]): string {
  const o = options.find((x) => x.id === raw);
  return o?.label ?? raw.replace(/_/g, " ");
}

function readTranslation(rec: Record<string, unknown>) {
  const suggestion =
    typeof rec.suggestion === "string" ? rec.suggestion : "translate";
  const proposed_target =
    typeof rec.proposed_target === "string" || rec.proposed_target === null
      ? (rec.proposed_target as string | null)
      : null;
  const rationale = typeof rec.rationale === "string" ? rec.rationale : "";
  const rawAlts = rec.alternative_targets;
  const fromApi: string[] = Array.isArray(rawAlts)
    ? rawAlts.filter((x): x is string => typeof x === "string" && x.trim() !== "").map((x) => x.trim())
    : [];
  const seen = new Set<string>();
  const ptKey = (proposed_target ?? "").trim().toLowerCase();
  if (ptKey) seen.add(ptKey);
  const alternative_targets: string[] = [];
  for (const a of fromApi) {
    const k = a.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    alternative_targets.push(a);
    if (alternative_targets.length >= 5) break;
  }
  return { suggestion, proposed_target, rationale, alternative_targets };
}

function formatWhen(iso: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function runStatusTone(status: string): string {
  if (status === "completed") return "text-emerald-300/90";
  if (status === "running") return "text-accent";
  if (status === "cancelled") return "text-amber-200/90";
  if (status === "failed") return "text-red-300";
  return "text-ink-400";
}

interface Props {
  bookId: string;
  pollWhileRunning: boolean;
}

export function GlossaryReviewPanel({ bookId, pollWhileRunning }: Props) {
  const { data, isLoading, isError, error } = useWorkingGlossary(bookId, {
    enabled: true,
    refetchIntervalMs: pollWhileRunning ? 2000 : false,
  });
  const [query, setQuery] = useState("");
  const [hiddenTermTypes, setHiddenTermTypes] = useState<Set<string>>(() => new Set());
  const [openId, setOpenId] = useState<string | null>(null);

  const termTypeOptionIds = useMemo(
    () => (data?.term_type_options ?? []).map((o) => o.id),
    [data?.term_type_options],
  );

  const termTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const id of termTypeOptionIds) counts[id] = 0;
    for (const e of data?.entries ?? []) {
      const id = canonicalTermTypeId(e.term_type, termTypeOptionIds);
      counts[id] = (counts[id] ?? 0) + 1;
    }
    return counts;
  }, [data?.entries, termTypeOptionIds]);

  const filtered = useMemo(() => {
    if (!data?.entries.length) return [];
    const q = query.trim().toLowerCase();
    return data.entries.filter((e) => {
      const tid = canonicalTermTypeId(e.term_type, termTypeOptionIds);
      if (hiddenTermTypes.has(tid)) return false;
      if (!q) return true;
      const tr = readTranslation(e.translation_recommendation);
      const blob = [
        e.canonical_form,
        e.meaning,
        e.term_type,
        ...e.variants,
        tr.proposed_target ?? "",
        tr.rationale,
        ...tr.alternative_targets,
      ]
        .join(" ")
        .toLowerCase();
      return blob.includes(q);
    });
  }, [data?.entries, query, hiddenTermTypes, termTypeOptionIds]);

  const toggleTermTypeVisibility = (id: string) => {
    setHiddenTermTypes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const clearTermTypeFilter = () => setHiddenTermTypes(new Set());

  return (
    <section
      id="glossary-review"
      aria-labelledby="glossary-review-heading"
      className="mb-14 scroll-mt-6"
    >
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2
            id="glossary-review-heading"
            className="font-serif text-2xl font-semibold tracking-tight text-ink-50"
          >
            Working glossary
          </h2>
          <p className="mt-1 max-w-prose text-xs leading-relaxed text-ink-500">
            Occurrences and the first-window index are counted across the full manuscript
            (not the model), using the same ~{formatNumber(GLOSSARY_EXTRACTION_WINDOW_WORDS)}
            -word windows (~{formatNumber(GLOSSARY_EXTRACTION_OVERLAP_WORDS)} overlap) as
            extraction. Translation targets default to the source form when the model left
            them blank.
          </p>
          <RunSubtitle run={data?.run ?? null} isLoading={isLoading} />
        </div>
        <div className="relative max-w-md flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-500"
            aria-hidden
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by term, variant, or gloss…"
            className={cn(
              "w-full rounded-md border border-ink-700 bg-ink-900 py-2 pl-10 pr-3 font-sans text-sm text-ink-100",
              "placeholder:text-ink-500",
              "focus:border-accent/50 focus:outline-none focus:ring-2 focus:ring-accent/30",
            )}
            aria-label="Filter glossary entries"
          />
        </div>
      </div>

      {!isLoading && !isError && data && data.entries.length > 0 && (
        <div
          className="mb-6 rounded-lg border border-ink-800/80 bg-ink-900/40 px-3 py-3 sm:px-4"
          role="group"
          aria-label="Filter by term type"
        >
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
              Term types
            </p>
            {hiddenTermTypes.size > 0 && (
              <button
                type="button"
                onClick={clearTermTypeFilter}
                className={cn(
                  "rounded px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-accent-pink",
                  "hover:bg-accent-pink/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-pink/40",
                )}
              >
                Show all types
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {(data.term_type_options ?? []).map((opt) => {
              const id = opt.id;
              const meta = termTypeStyleFor(id);
              const { Icon } = meta;
              const visible = !hiddenTermTypes.has(id);
              const count = termTypeCounts[id] ?? 0;
              return (
                <button
                  key={id}
                  type="button"
                  aria-pressed={visible}
                  title={visible ? `Hide ${opt.label} terms` : `Show ${opt.label} terms`}
                  onClick={() => toggleTermTypeVisibility(id)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 font-mono text-[11px] font-medium transition-all duration-150",
                    visible ? meta.chipOn : meta.chipOff,
                  )}
                >
                  <Icon
                    className={cn(
                      "h-3.5 w-3.5 shrink-0",
                      visible ? meta.iconClass : "text-ink-500",
                    )}
                    aria-hidden
                  />
                  <span>{opt.label}</span>
                  <span
                    className={cn(
                      "min-w-[1.25rem] tabular-nums",
                      visible ? "opacity-80" : "opacity-60",
                    )}
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {isLoading && (
        <p className="text-sm text-ink-400" aria-busy="true">
          Loading glossary…
        </p>
      )}

      {isError && (
        <p className="text-sm text-red-300" role="alert">
          {error instanceof Error ? error.message : String(error)}
        </p>
      )}

      {!isLoading && !isError && data && !data.run && (
        <p className="max-w-prose text-sm leading-relaxed text-ink-400">
          No extraction run exists for this book yet. When you start a run, terms
          will appear here as each pass finishes.
        </p>
      )}

      {!isLoading && !isError && data?.run && data.entries.length === 0 && (
        <p className="max-w-prose text-sm leading-relaxed text-ink-400">
          This run has no stored terms yet. If extraction is still running, check
          back in a moment.
        </p>
      )}

      {!isLoading && !isError && filtered.length > 0 && (
        <p className="mb-3 font-mono text-xs text-ink-500">
          Showing {filtered.length}
          {(query.trim() || hiddenTermTypes.size > 0) && ` of ${data?.entries.length ?? 0}`} term
          {filtered.length === 1 ? "" : "s"}
          {hiddenTermTypes.size > 0 && (
            <span className="text-ink-600">
              {" "}
              · {hiddenTermTypes.size} type{hiddenTermTypes.size === 1 ? "" : "s"} hidden
            </span>
          )}
        </p>
      )}

      {!isLoading && !isError && data && filtered.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-ink-800 bg-ink-900/50">
          <ul className="divide-y divide-ink-800/90">
            {filtered.map((entry) => (
              <GlossaryEntryRow
                key={entry.id}
                entry={entry}
                termTypeOptions={data.term_type_options}
                translationSuggestionOptions={data.translation_suggestion_options}
                termTypeOptionIds={termTypeOptionIds}
                expanded={openId === entry.id}
                onToggle={() =>
                  setOpenId((prev) => (prev === entry.id ? null : entry.id))
                }
              />
            ))}
          </ul>
        </div>
      )}

      {!isLoading && !isError && data && data.entries.length > 0 && filtered.length === 0 && (
        <p className="text-sm text-ink-400">
          No terms match that filter
          {hiddenTermTypes.size === (data.term_type_options?.length ?? 0)
            ? " (all types are hidden)"
            : ""}.
        </p>
      )}
    </section>
  );
}

function RunSubtitle({
  run,
  isLoading,
}: {
  run: GlossaryRunMeta | null;
  isLoading: boolean;
}) {
  if (isLoading) return null;
  if (!run) return null;
  return (
    <p className="mt-1.5 font-mono text-xs text-ink-400">
      <span className={runStatusTone(run.status)}>{run.status}</span>
      <span className="text-ink-600"> · </span>
      {formatWhen(run.started_at)}
      <span className="text-ink-600"> · </span>
      {run.entry_count} term{run.entry_count === 1 ? "" : "s"}
      {run.model && (
        <>
          <span className="text-ink-600"> · </span>
          <span className="text-ink-500">{run.model}</span>
        </>
      )}
    </p>
  );
}

function TermTypeBadge({
  termType,
  termTypeOptions,
  termTypeOptionIds,
}: {
  termType: string;
  termTypeOptions: GlossarySelectOption[];
  termTypeOptionIds: readonly string[];
}) {
  const id = canonicalTermTypeId(termType, termTypeOptionIds);
  const label = termTypeOptions.find((o) => o.id === id)?.label ?? id.replace(/_/g, " ");
  const meta = termTypeStyleFor(id);
  const { Icon } = meta;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
        meta.badge,
      )}
    >
      <Icon className={cn("h-3 w-3 shrink-0", meta.iconClass)} aria-hidden />
      <span>{label}</span>
      {id !== termType && (
        <span className="sr-only"> ({termType})</span>
      )}
    </span>
  );
}

function GlossaryEntryRow({
  entry,
  termTypeOptions,
  translationSuggestionOptions,
  termTypeOptionIds,
  expanded,
  onToggle,
}: {
  entry: GlossaryWorkingEntry;
  termTypeOptions: GlossarySelectOption[];
  translationSuggestionOptions: GlossarySelectOption[];
  termTypeOptionIds: readonly string[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const tr = readTranslation(entry.translation_recommendation);
  const dimmed = entry.status === "rejected";

  return (
    <li>
      <div
        className={cn(
          "transition-colors duration-200 ease-out",
          dimmed ? "opacity-50" : "",
          expanded ? "bg-ink-800/35" : "hover:bg-ink-800/25",
        )}
      >
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          className={cn(
            "flex w-full items-start gap-3 px-4 py-3.5 text-left",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/40",
          )}
        >
          <ChevronDown
            className={cn(
              "mt-0.5 h-4 w-4 shrink-0 text-ink-500 transition-transform duration-200 ease-out",
              expanded ? "rotate-180" : "rotate-0",
            )}
            aria-hidden
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="font-serif text-lg font-medium text-ink-50">
                {entry.canonical_form}
              </span>
              <TermTypeBadge
                termType={entry.term_type}
                termTypeOptions={termTypeOptions}
                termTypeOptionIds={termTypeOptionIds}
              />
              {entry.status !== "proposed" && (
                <span className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                  {entry.status}
                </span>
              )}
            </div>
            <p className="mt-1 line-clamp-2 font-sans text-sm leading-snug text-ink-300">
              {entry.meaning}
            </p>
            <p className="mt-2 font-mono text-xs text-ink-400">
              <span className="text-ink-500">
                {labelSuggestion(tr.suggestion, translationSuggestionOptions)}
              </span>
              {tr.proposed_target != null && tr.proposed_target !== "" && (
                <>
                  <span className="text-ink-600"> → </span>
                  <span className="text-accent-pink">{tr.proposed_target}</span>
                </>
              )}
              {tr.alternative_targets.length > 0 && (
                <span className="mt-1 block text-ink-500">
                  <span className="text-ink-600">Also: </span>
                  {tr.alternative_targets.join(" · ")}
                </span>
              )}
            </p>
          </div>
        </button>
        {expanded && (
          <div className="border-t border-ink-800/80 px-4 pb-4 pl-11 pr-4 pt-1">
            <div className="space-y-3 text-sm leading-relaxed text-ink-200">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                  Gloss
                </p>
                <p className="mt-1 font-serif text-base">{entry.meaning}</p>
              </div>
              {tr.alternative_targets.length > 0 && (
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                    Other viable renderings
                  </p>
                  <ul className="mt-2 list-inside list-disc space-y-1 font-sans text-ink-200">
                    {tr.alternative_targets.map((a) => (
                      <li key={a}>{a}</li>
                    ))}
                  </ul>
                </div>
              )}
              {tr.rationale ? (
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                    Translation note
                  </p>
                  <p className="mt-1 font-sans text-ink-300">{tr.rationale}</p>
                </div>
              ) : null}
              {entry.variants.length > 0 && (
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
                    Variants in text
                  </p>
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {entry.variants.map((v) => (
                      <li
                        key={v}
                        className="rounded border border-ink-700 bg-ink-900 px-2 py-1 font-mono text-xs text-ink-200"
                      >
                        {v}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="font-mono text-[10px] text-ink-600">
                First seen window {entry.first_seen_window}
                <span className="text-ink-700"> · </span>
                Occurrences {entry.occurrence_count}
              </p>
            </div>
          </div>
        )}
      </div>
    </li>
  );
}
