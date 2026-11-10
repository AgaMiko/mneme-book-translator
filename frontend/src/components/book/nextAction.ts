import type { BookDetail } from "@/lib/api/client";
import { formatNumber } from "@/lib/utils";

import {
  glossaryUsable,
  translationComplete,
  voicesFinished,
  type BookTab,
  type TabCounts,
} from "./tabs";

/**
 * The one thing to do next, and reminders of review work left behind.
 *
 * The main step follows the pipeline to the end: glossary, speakers,
 * voices, translation, the special passages in Review, then export. A
 * glossary run that was stopped or failed keeps its terms, so the next
 * step is speakers; the Glossary tab still offers to resume or retry it.
 *
 * Reminders name pending glossary terms and voice profiles. They never
 * block the main step: a translation uses them as they are.
 *
 * The main step is `null` when it points at the tab you are already on:
 * the destination is on screen, so the button would do nothing.
 */
export interface NextAction {
  label: string;
  onClick: () => void;
}

export interface NextActions {
  primary: NextAction | null;
  reminders: NextAction[];
}

interface Step {
  label: string;
  tab: BookTab;
}

function plural(n: number, one: string, many: string): string {
  return `${formatNumber(n)} ${n === 1 ? one : many}`;
}

function nextStep(book: BookDetail, counts: TabCounts): Step {
  const glossary = book.glossary_extraction_status;

  if (glossary === "running") return { label: "Watch glossary run", tab: "glossary" };
  if (!glossaryUsable(book)) return { label: "Build glossary", tab: "glossary" };

  // The glossary has its terms — voices attach to its character entries.
  if (!voicesFinished(book)) {
    // One step for the author; the Voices tab runs both passes.
    const running =
      book.speakers_extraction_status === "running" || book.voice_extraction_status === "running";
    return { label: running ? "Watch voices run" : "Build voices", tab: "voices" };
  }

  const { translationDone: done, translationTotal: total } = counts;
  if (counts.translationStatus === "running") {
    return {
      label: total > 0 ? `Watch translation (${done}/${total})` : "Watch translation",
      tab: "translation",
    };
  }
  if (!translationComplete(counts)) {
    return {
      label: done > 0 && total > 0 ? `Continue translation (${done}/${total})` : "Translate",
      tab: "translation",
    };
  }

  // Whole book translated: the special passages, then export.
  if (counts.passagesStatus === "scanning" || counts.passagesStatus === "checking") {
    return { label: "Watch passage check", tab: "review" };
  }
  if (counts.passagesBlocking > 0) {
    return {
      label: `Decide on ${plural(counts.passagesBlocking, "passage", "passages")}`,
      tab: "review",
    };
  }
  if (counts.passagesOpen > 0) {
    return {
      label: `Review ${plural(counts.passagesOpen, "passage", "passages")}`,
      tab: "review",
    };
  }
  return { label: "Export", tab: "export" };
}

function reminderSteps(book: BookDetail, counts: TabCounts): Step[] {
  const steps: Step[] = [];
  if (
    glossaryUsable(book) &&
    counts.glossaryPending > 0 &&
    book.glossary_extraction_status !== "running"
  ) {
    steps.push({
      label: `${plural(counts.glossaryPending, "term", "terms")} to review`,
      tab: "glossary",
    });
  }
  if (voicesFinished(book) && counts.voicesPending > 0) {
    steps.push({
      label: `${plural(counts.voicesPending, "voice profile", "voice profiles")} to review`,
      tab: "voices",
    });
  }
  return steps;
}

export function computeNextActions(
  book: BookDetail,
  counts: TabCounts,
  activeTab: BookTab,
  selectTab: (tab: BookTab) => void,
): NextActions {
  const toAction = (step: Step): NextAction => ({
    label: step.label,
    onClick: () => selectTab(step.tab),
  });
  const step = nextStep(book, counts);
  return {
    primary: step.tab === activeTab ? null : toAction(step),
    reminders: reminderSteps(book, counts)
      .filter((s) => s.tab !== activeTab)
      .map(toAction),
  };
}
