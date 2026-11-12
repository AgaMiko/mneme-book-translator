import { ArrowRight, CheckCircle2, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/Button";
import type { BookDetail, MarkableStage } from "@/lib/api/client";
import { useSetStageFinished } from "@/lib/api/hooks";

/**
 * The end of a step page, below the review list.
 *
 * Finishing a step means finishing its review, so the way on sits where
 * the review ends. When the run did not finish on its own (stopped, or
 * you want to go on with what it found), "Done reviewing" marks the step
 * finished and opens the next one. When the step is already finished,
 * the button only opens the next one. Pending items are named, never
 * blocking: `pendingNote` says what happens to them.
 */
export function StepFinish({
  book,
  stage,
  running,
  completed,
  canFinish = true,
  cannotFinishReason,
  pendingNote,
  nextLabel,
  onNext,
}: {
  book: BookDetail;
  stage: MarkableStage;
  running: boolean;
  /** The run finished on its own. */
  completed: boolean;
  canFinish?: boolean;
  cannotFinishReason?: string;
  /** What happens to items you did not review, or null when there are none. */
  pendingNote: string | null;
  /** Name of the next step, e.g. "Voices". */
  nextLabel: string;
  onNext: () => void;
}) {
  const setFinished = useSetStageFinished(book.id);
  const marked = book.stages_marked_finished.includes(stage);
  const finished = completed || marked;
  const busy = setFinished.isPending;

  if (running) return null;

  return (
    <section
      aria-label="Finish this step"
      className="mt-8 flex flex-wrap items-center gap-3 rounded-lg border border-ink-800 bg-ink-900 px-4 py-3"
    >
      <div className="min-w-0 flex-1 text-body">
        {finished ? (
          <p className="inline-flex items-center gap-1.5 text-success">
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
            {marked && !completed ? "You finished this step." : "This step is finished."}
          </p>
        ) : (
          <p className="text-ink-200">
            {canFinish
              ? `Finished reviewing? ${nextLabel} works from what is here now.`
              : cannotFinishReason}
          </p>
        )}
        {pendingNote && <p className="mt-0.5 text-small text-ink-400">{pendingNote}</p>}
        {setFinished.isError && (
          <p className="mt-1 text-small text-danger" role="alert">
            {setFinished.error.message}
          </p>
        )}
      </div>

      {marked && !completed && (
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          title="The step counts as unfinished again"
          onClick={() => setFinished.mutate({ stage, finished: false })}
        >
          Undo
        </Button>
      )}
      {finished ? (
        <Button variant="accent" size="sm" onClick={onNext}>
          Go to {nextLabel}
          <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </Button>
      ) : (
        <Button
          variant="accent"
          size="sm"
          disabled={!canFinish || busy}
          onClick={() => setFinished.mutate({ stage, finished: true }, { onSuccess: onNext })}
        >
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
          Done reviewing
          <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </Button>
      )}
    </section>
  );
}

/**
 * The end of a step with nothing to mark as finished (Check): where the
 * review stands and the way on. It never blocks.
 */
export function StepNext({
  done,
  doneText,
  todoText,
  nextLabel,
  onNext,
}: {
  done: boolean;
  doneText: string;
  todoText: string;
  nextLabel: string;
  onNext: () => void;
}) {
  return (
    <section
      aria-label="Next step"
      className="mt-8 flex flex-wrap items-center gap-3 rounded-lg border border-ink-800 bg-ink-900 px-4 py-3"
    >
      <p className="min-w-0 flex-1 text-body">
        {done ? (
          <span className="inline-flex items-center gap-1.5 text-success">
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
            {doneText}
          </span>
        ) : (
          <span className="text-ink-200">{todoText}</span>
        )}
      </p>
      <Button variant="accent" size="sm" onClick={onNext}>
        Go to {nextLabel}
        <ArrowRight className="h-3.5 w-3.5" aria-hidden />
      </Button>
    </section>
  );
}
