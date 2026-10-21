import type { BookDetail } from "@/lib/api/client";
import { formatNumber } from "@/lib/utils";

/**
 * Sections of an open book — single source of truth.
 *
 * The tabs double as the pipeline: each one reports where its step
 * stands (`state`) and a one-line summary of what is inside (`caption`).
 * That is why the header no longer needs a row of status pills — the
 * navigation itself carries the state.
 *
 * `Voices` unlocks after glossary extraction completes (canonical
 * characters exist). `Translation` is always reachable; it works best after
 * the glossary and voices are reviewed, but can run on a single chapter
 * at any time.
 */

/**
 * `done` — the step finished. `active` — a run is in flight.
 * `idle` — reachable but not started. `locked` — a prerequisite is missing.
 */
export type TabState = "done" | "active" | "idle" | "locked";

/** Review counts the header needs for the captions. */
export interface TabCounts {
  glossaryTotal: number;
  glossaryPending: number;
  voicesTotal: number;
  voicesPending: number;
  translationStatus: "running" | "completed" | "failed" | "cancelled" | null;
  translationDone: number;
  translationTotal: number;
}

export const EMPTY_TAB_COUNTS: TabCounts = {
  glossaryTotal: 0,
  glossaryPending: 0,
  voicesTotal: 0,
  voicesPending: 0,
  translationStatus: null,
  translationDone: 0,
  translationTotal: 0,
};

export interface BookTabDef {
  id: "manuscript" | "glossary" | "voices" | "translation";
  label: string;
  disabled: boolean;
  state: (book: BookDetail, counts: TabCounts) => TabState;
  caption: (book: BookDetail, counts: TabCounts) => string;
}

/** `3/48` when a run reports window progress, otherwise "". */
function windowProgress(completed: number | null | undefined, total: number | null | undefined) {
  if (total == null || total <= 0) return "";
  return `${completed ?? 0}/${total}`;
}

export const BOOK_TABS: readonly BookTabDef[] = [
  {
    id: "manuscript",
    label: "Manuscript",
    disabled: false,
    // The text is always there — parsing happens at upload.
    state: () => "done",
    caption: (b) =>
      `${formatNumber(b.chapters.length)} chapter${b.chapters.length === 1 ? "" : "s"} · ${formatNumber(b.word_count)} words`,
  },
  {
    id: "glossary",
    label: "Glossary",
    disabled: false,
    state: (b) => {
      if (b.glossary_extraction_status === "completed") return "done";
      if (b.glossary_extraction_status === "running") return "active";
      return "idle";
    },
    caption: (b, counts) => {
      if (b.glossary_extraction_status === "running") {
        const p = windowProgress(
          b.glossary_extraction_windows_completed,
          b.glossary_extraction_windows_total,
        );
        return p ? `extracting · pass ${p}` : "extracting…";
      }
      if (b.glossary_extraction_status === "idle") return "not started";
      if (counts.glossaryTotal === 0) return "no terms yet";
      return `${formatNumber(counts.glossaryTotal)} terms · ${formatNumber(counts.glossaryPending)} pending`;
    },
  },
  {
    id: "voices",
    label: "Voices",
    disabled: false,
    state: (b) => {
      if (b.glossary_extraction_status !== "completed") return "locked";
      if (b.voice_extraction_status === "running" || b.speakers_extraction_status === "running") {
        return "active";
      }
      if (b.voice_extraction_status === "completed") return "done";
      return "idle";
    },
    caption: (b, counts) => {
      if (b.glossary_extraction_status !== "completed") return "glossary first";
      if (b.speakers_extraction_status === "running") {
        const p = windowProgress(
          b.speakers_extraction_windows_completed,
          b.speakers_extraction_windows_total,
        );
        return p ? `pass 1 · window ${p}` : "pass 1 running…";
      }
      if (b.voice_extraction_status === "running") {
        const p = windowProgress(
          b.voice_extraction_windows_completed,
          b.voice_extraction_windows_total,
        );
        return p ? `pass 2 · window ${p}` : "pass 2 running…";
      }
      if (counts.voicesTotal > 0) {
        return `${formatNumber(counts.voicesTotal)} profiles · ${formatNumber(counts.voicesPending)} pending`;
      }
      if (b.speakers_extraction_status === "completed") return "speakers mapped";
      return "not started";
    },
  },
  {
    id: "translation",
    label: "Translation",
    disabled: false,
    state: (_b, counts) => {
      if (counts.translationStatus === "running") return "active";
      if (counts.translationStatus === "completed") return "done";
      return "idle";
    },
    caption: (_b, counts) => {
      const p = windowProgress(counts.translationDone, counts.translationTotal);
      switch (counts.translationStatus) {
        case "running":
          return p ? `translating · ${p}` : "translating…";
        case "completed":
          return p ? `${p} fragments done` : "done";
        case "cancelled":
          return p ? `stopped · ${p}` : "stopped";
        case "failed":
          return p ? `errors · ${p}` : "failed";
        default:
          return "not started";
      }
    },
  },
];

export type BookTab = BookTabDef["id"];

export const BOOK_TAB_IDS: readonly BookTab[] = BOOK_TABS.map((t) => t.id);

export const DEFAULT_BOOK_TAB: BookTab = "manuscript";
