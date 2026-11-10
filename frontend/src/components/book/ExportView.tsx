import { CheckCircle2, CircleAlert, Download, Info } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { type BookDetail, type TranslationStage, translationExportUrl } from "@/lib/api/client";
import { usePassages, useTranslation } from "@/lib/api/hooks";
import { cn, formatNumber } from "@/lib/utils";

import { BOOK_PANEL_CONTAINER, BOOK_PANEL_SURFACE } from "./layout";
import { translationComplete, type BookTab, type TabCounts } from "./tabs";
import { LABEL, SECTION_HEADING } from "@/components/ui/typography";

const STAGES: { id: TranslationStage; label: string; hint: string }[] = [
  { id: "faithful", label: "Draft", hint: "Faithful draft: complete and accurate, not yet edited" },
  { id: "line_edit", label: "Line edit", hint: "Edited into natural English prose" },
  // The last stage is called "Final" in the UI; its API id stays `polish`.
  { id: "polish", label: "Final", hint: "The finished English" },
];

type Tone = "ok" | "warn" | "info";

/**
 * The Export step: what the file will contain, then the download.
 *
 * Each line of the checklist says how one earlier step stands and what
 * that means for the file. Nothing here blocks a download. A passage that
 * breaks its rule with no checked translation makes the file a draft: the
 * server adds `_DRAFT` to its name, and the buttons say so.
 */
export function ExportView({
  book,
  counts,
  onSelectTab,
}: {
  book: BookDetail;
  counts: TabCounts;
  onSelectTab: (tab: BookTab) => void;
}) {
  const translation = useTranslation(book.id);
  const passages = usePassages(book.id);
  const [stage, setStage] = useState<TranslationStage>("polish");

  const stages = useMemo(() => {
    const present = new Set<TranslationStage>();
    for (const ch of translation.data?.chapters ?? []) {
      for (const f of ch.fragments) {
        for (const s of Object.keys(f.stages) as TranslationStage[]) present.add(s);
      }
    }
    return STAGES.filter((s) => present.has(s.id));
  }, [translation.data?.chapters]);

  const { translationDone: done, translationTotal: total } = counts;
  const blocking = counts.passagesBlocking;
  const openPassages = counts.passagesOpen;
  // Exports wait for the passage list: it decides whether the file is a draft.
  const ready = (passages.isSuccess || passages.isError) && done > 0;
  const draft = blocking > 0;
  const proposedTerms = counts.glossaryProposed;
  const pendingVoices = counts.voicesPending;

  return (
    <div className={BOOK_PANEL_SURFACE}>
      <div className={cn(BOOK_PANEL_CONTAINER, "py-8")}>
        <h2 className={SECTION_HEADING}>Export</h2>
        <p className="mt-1 text-body text-ink-400">
          What the file will contain. Nothing here stops a download.
        </p>

        <ul className="mt-5 divide-y divide-ink-800 rounded-lg border border-ink-800 bg-ink-900">
          <Check
            tone={translationComplete(counts) ? "ok" : "warn"}
            action={
              translationComplete(counts) ? null : (
                <Go label="Translate" onClick={() => onSelectTab("translation")} />
              )
            }
          >
            {total === 0
              ? "Nothing is translated yet."
              : translationComplete(counts)
                ? `The whole book is translated (${formatNumber(total)} fragments).`
                : `${formatNumber(done)} of ${formatNumber(total)} fragments are translated. The parts not translated yet are marked in the file.`}
          </Check>
          <Check
            tone={blocking > 0 ? "warn" : openPassages > 0 ? "info" : "ok"}
            action={
              blocking > 0 || openPassages > 0 ? (
                <Go label="Check" onClick={() => onSelectTab("review")} />
              ) : null
            }
          >
            {blocking > 0
              ? `${blocking} special passage${blocking === 1 ? " breaks its rule" : "s break their rule"} with no checked translation. Until you decide, the file is a draft and its name ends in _DRAFT.`
              : openPassages > 0
                ? `${openPassages} checked special passage${openPassages === 1 ? " waits" : "s wait"} for your review. The checked translation goes into the file.`
                : counts.passagesTotal > 0
                  ? "Every special passage is reviewed."
                  : "No special passages were found."}
          </Check>
          {proposedTerms > 0 && (
            <Check
              tone="info"
              action={<Go label="Glossary" onClick={() => onSelectTab("glossary")} />}
            >
              {`${formatNumber(proposedTerms)} glossary term${proposedTerms === 1 ? " was" : "s were"} not reviewed. The translation used accepted terms only.`}
            </Check>
          )}
          {pendingVoices > 0 && (
            <Check tone="info" action={<Go label="Voices" onClick={() => onSelectTab("voices")} />}>
              {`${formatNumber(pendingVoices)} voice profile${pendingVoices === 1 ? " was" : "s were"} not reviewed. The translation used them as drafted.`}
            </Check>
          )}
        </ul>

        {stages.length > 1 && (
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <p className={LABEL}>Version</p>
            <div className="inline-flex rounded-lg border border-ink-700 bg-ink-900 p-0.5">
              {stages.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  title={s.hint}
                  onClick={() => setStage(s.id)}
                  aria-pressed={stage === s.id}
                  className={cn(
                    "rounded-md px-3 py-1 text-small transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    stage === s.id ? "bg-ink-700 text-ink-50" : "text-ink-400 hover:text-ink-100",
                  )}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <p className="text-small text-ink-500">
              Fragments missing at this stage fall back to an earlier one.
            </p>
          </div>
        )}

        <div className="mt-6 flex flex-wrap items-center gap-2">
          {(["pdf", "epub", "docx"] as const).map((fmt) => {
            const label = `${draft ? "Draft " : "Download "}${fmt.toUpperCase()}`;
            return ready ? (
              <a
                key={fmt}
                href={translationExportUrl(book.id, fmt, stage, draft)}
                download
                className={cn(
                  "inline-flex h-9 items-center gap-2 rounded-lg border border-accent bg-accent-soft px-4 text-body font-medium text-accent",
                  "hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                )}
              >
                <Download className="h-3.5 w-3.5" aria-hidden />
                {label}
              </a>
            ) : (
              <span
                key={fmt}
                aria-disabled="true"
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-ink-700 px-4 text-body font-medium text-ink-500"
              >
                <Download className="h-3.5 w-3.5" aria-hidden />
                {label}
              </span>
            );
          })}
        </div>
        <p className="mt-2 text-small text-ink-500">The PDF is typeset in EB Garamond.</p>
      </div>
    </div>
  );
}

function Check({
  tone,
  action,
  children,
}: {
  tone: Tone;
  action?: ReactNode;
  children: ReactNode;
}) {
  const Icon = tone === "ok" ? CheckCircle2 : tone === "warn" ? CircleAlert : Info;
  return (
    <li className="flex items-start gap-3 px-4 py-3 text-body">
      <Icon
        className={cn(
          "mt-0.5 h-4 w-4 shrink-0",
          tone === "ok" ? "text-success" : tone === "warn" ? "text-warning" : "text-ink-400",
        )}
        aria-hidden
      />
      <p className="min-w-0 flex-1 text-ink-200">{children}</p>
      {action}
    </li>
  );
}

function Go({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="shrink-0 rounded text-small text-accent underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      Go to {label}
    </button>
  );
}
