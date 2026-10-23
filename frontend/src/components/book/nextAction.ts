import type { BookDetail } from "@/lib/api/client";

import { glossaryUsable, voicesFinished, type BookTab } from "./tabs";

/**
 * The one thing to do next.
 *
 * This is the state machine the old `WorkflowHint` bar used, distilled
 * from a sentence into a button. Same reading of the pipeline —
 * glossary, then speakers, then voices — but instead of narrating the
 * state it names the step and takes you there. A glossary run that was
 * stopped or failed keeps its terms, so the next step is speakers; the
 * Glossary tab still offers to resume or retry the run.
 *
 * Returns `null` when the next step is the tab you are already on:
 * the destination is on screen, so the button would be a no-op. The
 * tab captions carry the detail in that case. Silence is a feature.
 */
export interface NextAction {
  label: string;
  onClick: () => void;
}

interface Step {
  label: string;
  tab: BookTab;
}

function nextStep(book: BookDetail): Step {
  const glossary = book.glossary_extraction_status;

  if (glossary === "running") return { label: "Watch glossary run", tab: "glossary" };
  if (!glossaryUsable(book)) return { label: "Build glossary", tab: "glossary" };

  // The glossary has its terms — voices attach to its character entries.
  if (voicesFinished(book)) return { label: "Translate", tab: "translation" };
  const speakers = book.speakers_extraction_status;
  if (speakers === "running") return { label: "Watch speaker run", tab: "voices" };
  if (speakers !== "completed") return { label: "Identify speakers", tab: "voices" };

  if (book.voice_extraction_status === "running") {
    return { label: "Watch voice run", tab: "voices" };
  }
  return { label: "Extract voices", tab: "voices" };
}

export function computeNextAction(
  book: BookDetail,
  activeTab: BookTab,
  selectTab: (tab: BookTab) => void,
): NextAction | null {
  const step = nextStep(book);
  if (step.tab === activeTab) return null;
  return { label: step.label, onClick: () => selectTab(step.tab) };
}
