import { useEffect, useRef } from "react";

import { useStepModel } from "@/hooks/useStepModel";
import type { BookDetail } from "@/lib/api/client";
import { useStartVoiceExtraction } from "@/lib/api/hooks";

/**
 * "Build voices" is one button for two passes: find who speaks each line,
 * then write a profile per character. The backend runs them as separate
 * jobs, so the frontend remembers that you asked for both and starts the
 * second when the first completes.
 *
 * The request is kept in localStorage per book, so it survives switching
 * tabs or reloading. The hook runs in the book shell, which stays mounted
 * on every tab. If the page is closed when the first pass ends, the
 * Voices tab offers "Write profiles" instead.
 */
const key = (bookId: string) => `mneme.voices-after-speakers.${bookId}`;

export function requestVoicesAfterSpeakers(bookId: string): void {
  try {
    localStorage.setItem(key(bookId), "1");
  } catch {
    // Storage blocked: the Voices tab still offers the second pass by hand.
  }
}

export function cancelVoicesAfterSpeakers(bookId: string): void {
  try {
    localStorage.removeItem(key(bookId));
  } catch {
    // Nothing stored.
  }
}

function voicesRequested(bookId: string): boolean {
  try {
    return localStorage.getItem(key(bookId)) === "1";
  } catch {
    return false;
  }
}

export function useChainVoicesAfterSpeakers(book: BookDetail | undefined): void {
  const startVoice = useStartVoiceExtraction(book?.id ?? "");
  const voicesModel = useStepModel("voices");
  const started = useRef(false);

  const speakers = book?.speakers_extraction_status;
  const voices = book?.voice_extraction_status;

  useEffect(() => {
    if (!book || started.current || !voicesRequested(book.id)) return;
    // The second pass already ran or runs: the request is done.
    if (voices !== "idle") {
      cancelVoicesAfterSpeakers(book.id);
      return;
    }
    // Wait for the model list, so the pass runs on the model picked for it.
    if (speakers !== "completed" || voicesModel.model === undefined) return;
    started.current = true;
    cancelVoicesAfterSpeakers(book.id);
    startVoice.mutate({ model: voicesModel.model });
  }, [book, speakers, voices, startVoice, voicesModel.model]);
}
