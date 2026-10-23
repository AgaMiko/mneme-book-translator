import type { BookDetail, MarkableStage } from "@/lib/api/client";
import { formatNumber } from "@/lib/utils";

/**
 * Sections of an open book — single source of truth.
 *
 * The tabs double as the pipeline: each one reports where its step
 * stands (`state`) and a one-line summary of what is inside (`caption`).
 * That is why the header no longer needs a row of status pills — the
 * navigation itself carries the state.
 *
 * `Voices` unlocks once the glossary is usable (canonical characters
 * exist). `Translation` unlocks once the voices are extracted too: the
 * translation prompts use both. A book with translated text keeps the tab
 * open so the result stays readable.
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

/**
 * Later steps can use the glossary: extraction finished, or was stopped or
 * failed after finding terms (those are kept), or you marked it finished.
 * Never while it runs. Mirrors `glossary_ready` in `backend/app/services/stages.py`.
 */
export function glossaryUsable(book: BookDetail): boolean {
  const s = book.glossary_extraction_status;
  if (s === "running") return false;
  return (
    book.stages_marked_finished.includes("glossary") ||
    s === "completed" ||
    s === "cancelled" ||
    s === "failed"
  );
}

/** Voices are done: Pass 2 completed, or you marked the stage finished. Never while running. */
export function voicesFinished(book: BookDetail): boolean {
  if (book.voice_extraction_status === "running" || book.speakers_extraction_status === "running") {
    return false;
  }
  return (
    book.stages_marked_finished.includes("voices") || book.voice_extraction_status === "completed"
  );
}

/** Whether the toggle has anything to offer: hidden while running and after a real finish. */
export function showStageFinishedToggle(
  book: BookDetail,
  stage: MarkableStage,
  running: boolean,
  completed: boolean,
): boolean {
  return !running && (!completed || book.stages_marked_finished.includes(stage));
}

/** Steps that must finish before a translation can start (mirrors the backend check). */
export function translationBlockers(book: BookDetail): ("glossary" | "voices")[] {
  const missing: ("glossary" | "voices")[] = [];
  if (!glossaryUsable(book)) missing.push("glossary");
  if (!voicesFinished(book)) missing.push("voices");
  return missing;
}

/**
 * Translation stays closed until its prerequisites are done, unless the
 * book already has translated text to read.
 */
function translationLocked(book: BookDetail, counts: Pick<TabCounts, "translationDone">): boolean {
  return translationBlockers(book).length > 0 && counts.translationDone === 0;
}

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
      if (b.glossary_extraction_status === "running") return "active";
      if (b.glossary_extraction_status === "completed") return "done";
      if (b.stages_marked_finished.includes("glossary")) return "done";
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
      if (!glossaryUsable(b)) return "locked";
      if (b.voice_extraction_status === "running" || b.speakers_extraction_status === "running") {
        return "active";
      }
      if (voicesFinished(b)) return "done";
      return "idle";
    },
    caption: (b, counts) => {
      if (!glossaryUsable(b)) return "glossary first";
      if (b.speakers_extraction_status === "running") {
        const p = windowProgress(
          b.speakers_extraction_windows_completed,
          b.speakers_extraction_windows_total,
        );
        return p ? `pass 1 · part ${p}` : "pass 1 running…";
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
    state: (b, counts) => {
      if (translationLocked(b, counts)) return "locked";
      if (counts.translationStatus === "running") return "active";
      if (counts.translationStatus === "completed") return "done";
      return "idle";
    },
    caption: (b, counts) => {
      if (translationLocked(b, counts)) return `${translationBlockers(b)[0]} first`;
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

/**
 * The tab a book opens on: the furthest stage that has been started.
 * A fresh upload opens on the manuscript; a book whose voices are done
 * opens on voices; once a translation run exists, on translation, but
 * only if that tab is open (a run with nothing translated, on a book whose
 * voices are not done, does not count).
 */
export function startTabFor(
  book: BookDetail,
  counts: Pick<TabCounts, "translationStatus" | "translationDone">,
): BookTab {
  if (counts.translationStatus !== null && !translationLocked(book, counts)) {
    return "translation";
  }
  const started = (s: string) => s !== "idle";
  if (started(book.voice_extraction_status) || started(book.speakers_extraction_status)) {
    return "voices";
  }
  if (started(book.glossary_extraction_status)) return "glossary";
  return "manuscript";
}
