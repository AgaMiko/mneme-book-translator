import { CheckCircle2, Loader2, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/Button";
import type { BookDetail, MarkableStage } from "@/lib/api/client";
import { useSetStageFinished } from "@/lib/api/hooks";

import { showStageFinishedToggle } from "./tabs";

const NAMES: Record<MarkableStage, string> = { glossary: "glossary", voices: "voices" };

/**
 * Mark a stage as finished by hand, or take the mark back.
 *
 * For when a run was stopped partway and its result is good enough: the
 * next stage unlocks without running this one to the end. Hidden while a
 * run is going, and when the stage finished on its own (nothing to mark).
 */
export function StageFinishedToggle({
  book,
  stage,
  running,
  completed,
}: {
  book: BookDetail;
  stage: MarkableStage;
  running: boolean;
  completed: boolean;
}) {
  const setFinished = useSetStageFinished(book.id);
  const marked = book.stages_marked_finished.includes(stage);
  if (!showStageFinishedToggle(book, stage, running, completed)) return null;

  const busy = setFinished.isPending;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {marked ? (
        <>
          <span className="inline-flex items-center gap-1.5 text-xs text-success">
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
            You marked the {NAMES[stage]} as finished.
          </span>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            title={`The ${NAMES[stage]} counts as unfinished again`}
            onClick={() => setFinished.mutate({ stage, finished: false })}
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <Undo2 className="h-3.5 w-3.5" aria-hidden />
            )}
            Unmark
          </Button>
        </>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          className="border border-ink-700"
          disabled={busy}
          title={`Use the ${NAMES[stage]} as it is and unlock the next step`}
          onClick={() => setFinished.mutate({ stage, finished: true })}
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
          )}
          Mark {NAMES[stage]} as finished
        </Button>
      )}
      {setFinished.isError && (
        <span className="text-xs text-danger" role="alert">
          {setFinished.error.message}
        </span>
      )}
    </div>
  );
}
