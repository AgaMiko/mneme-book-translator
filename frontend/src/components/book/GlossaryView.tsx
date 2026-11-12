import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { GlossaryExtractionWorkspace } from "@/components/GlossaryExtractionWorkspace";
import { GlossaryReviewPanel } from "@/components/GlossaryReviewPanel";
import { useStepModel } from "@/hooks/useStepModel";
import {
  bookKeys,
  useContinueGlossaryExtraction,
  useExpandGlossary,
  useGlossaryExtractionEstimate,
  useStartGlossaryExtraction,
  useStopGlossaryExtraction,
  useWorkingGlossary,
} from "@/lib/api/hooks";
import type { BookDetail } from "@/lib/api/client";
import { cn, formatNumber } from "@/lib/utils";

import { BOOK_PANEL_CONTAINER, BOOK_PANEL_SURFACE } from "./layout";
import { StepFinish } from "./StepFinish";
import type { BookTab } from "./tabs";

interface Props {
  book: BookDetail;
  /** A glossary entry to open and scroll to (from the Translation tab). */
  focusEntryId?: string | null;
  onFocusHandled?: () => void;
  onSelectTab: (tab: BookTab) => void;
}

/**
 * The glossary step: the run in one line, the terms to review, and at the
 * end of the list the way on to Voices.
 */
export function GlossaryView({ book, focusEntryId = null, onFocusHandled, onSelectTab }: Props) {
  const queryClient = useQueryClient();
  const glossaryModel = useStepModel("glossary");
  const estimate = useGlossaryExtractionEstimate(book.id, true, glossaryModel.model);
  const startGlossary = useStartGlossaryExtraction(book.id);
  const continueGlossary = useContinueGlossaryExtraction(book.id);
  const stopGlossary = useStopGlossaryExtraction(book.id);
  const expandGlossary = useExpandGlossary(book.id);
  /**
   * Same query key the review panel below uses — react-query serves both
   * from one fetch, so the run card can name the run without a second
   * request.
   */
  const working = useWorkingGlossary(book.id, {
    enabled: true,
    refetchIntervalMs: book.glossary_extraction_status === "running" ? 2000 : false,
  });

  // Proposals are left out of the voices and the translation until accepted.
  const proposed = (working.data?.entries ?? []).filter((e) => e.status === "proposed").length;
  const status = book.glossary_extraction_status;

  const prevStatus = useRef<string | null>(null);
  useEffect(() => {
    const prev = prevStatus.current;
    prevStatus.current = book.glossary_extraction_status;
    if (prev === "running" && book.glossary_extraction_status !== "running") {
      void queryClient.invalidateQueries({
        queryKey: bookKeys.workingGlossary(book.id),
      });
    }
  }, [book.glossary_extraction_status, book.id, queryClient]);

  return (
    <div className={BOOK_PANEL_SURFACE}>
      <div className={cn(BOOK_PANEL_CONTAINER, "py-8")}>
        <GlossaryExtractionWorkspace
          book={book}
          estimate={estimate}
          startGlossary={startGlossary}
          continueGlossary={continueGlossary}
          stopGlossary={stopGlossary}
          expandGlossary={expandGlossary}
          model={glossaryModel}
          run={working.data?.run ?? null}
        />

        <div className="mt-8">
          <GlossaryReviewPanel
            bookId={book.id}
            focusEntryId={focusEntryId}
            onFocusHandled={onFocusHandled}
            pollWhileRunning={book.glossary_extraction_status === "running"}
          />
        </div>

        {/* Only with a run: finishing an empty glossary would unlock voices with no characters. */}
        <StepFinish
          book={book}
          stage="glossary"
          running={status === "running"}
          completed={status === "completed"}
          canFinish={Boolean(working.data?.run)}
          cannotFinishReason="Build or import a glossary first."
          pendingNote={
            proposed > 0
              ? `${formatNumber(proposed)} proposed term${proposed === 1 ? " is" : "s are"} not accepted yet. The voices and the translation use accepted terms only.`
              : null
          }
          nextLabel="Voices"
          onNext={() => onSelectTab("voices")}
        />
      </div>
    </div>
  );
}
