import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import type { BookDetail, Passage, PassageKind, PassageParagraph } from "@/lib/api/client";
import {
  useCheckPassages,
  useCreatePassage,
  usePassages,
  useResolvePassage,
  useScanPassages,
  useUpdatePassage,
} from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

import { BOOK_PANEL_CONTAINER, BOOK_PANEL_SURFACE } from "./layout";

/**
 * Step 6: special passages and their flags.
 *
 * A special passage follows a rule that normal translation breaks: verse
 * or a song (lines, rhyme), a hidden message (letters that spell
 * something), wordplay the plot depends on. They are found by a scan of
 * the manuscript, checked after translation, translated again when the
 * English breaks the rule, and listed here for the author.
 */

const KIND_LABEL: Record<PassageKind, string> = {
  verse: "Verse or song",
  hidden_message: "Hidden message",
  wordplay: "Wordplay",
};

const STATUS: Record<Passage["status"], { label: string; tone: string }> = {
  unchecked: { label: "Not checked yet", tone: "text-ink-400 border-ink-700" },
  passed: { label: "Rule kept", tone: "text-success border-success-border bg-success-surface" },
  corrected: {
    label: "Corrected automatically",
    tone: "text-accent border-accent bg-accent-soft",
  },
  failed: {
    label: "Needs your decision",
    tone: "text-danger border-danger-border bg-danger-surface",
  },
  author: { label: "Your text", tone: "text-success border-success-border bg-success-surface" },
  dismissed: { label: "Not a special passage", tone: "text-ink-500 border-ink-700" },
};

const INPUT =
  "w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 font-sans text-sm text-ink-100 " +
  "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-60";
const LABEL = "font-mono text-[10px] uppercase tracking-wider text-ink-500";

export function PassagesView({ book }: { book: BookDetail }) {
  const passages = usePassages(book.id);
  const scan = useScanPassages(book.id);
  const check = useCheckPassages(book.id);
  const [showAll, setShowAll] = useState(false);

  const view = passages.data;
  const state = view?.state;
  const busy = state?.status === "scanning" || state?.status === "checking";
  const all = useMemo(() => view?.passages ?? [], [view]);
  const open = all.filter((p) => p.status !== "dismissed" && p.flag?.status !== "accepted");
  const shown = showAll ? all : open;
  const toCheck = all.filter((p) => p.translated && (p.status === "unchecked" || p.stale)).length;
  const error = scan.error ?? check.error;

  return (
    <div className={BOOK_PANEL_SURFACE}>
      <div className={cn(BOOK_PANEL_CONTAINER, "py-10")}>
        <h2 className="font-serif text-2xl text-ink-50">Review</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-300">
          Some passages follow a rule that an ordinary translation breaks: a poem or song that
          rhymes, a letter whose first letters spell a message, a pun the plot depends on. They are
          found in the manuscript, checked once they are translated, and translated again when the
          English breaks the rule. Each one is listed here so you can read what was done.
        </p>

        <div className="mt-6 flex flex-wrap items-center gap-2">
          <Button
            variant="accent"
            size="sm"
            disabled={busy || scan.isPending}
            title="Reads every chapter once. Passages already listed are kept."
            onClick={() => scan.mutate()}
          >
            {state?.scanned ? "Scan the manuscript again" : "Scan the manuscript"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy || check.isPending || toCheck === 0}
            title="Checks translated passages that were not checked yet, or whose English changed"
            onClick={() => check.mutate()}
          >
            {toCheck > 0
              ? `Check ${toCheck} translated passage${toCheck === 1 ? "" : "s"}`
              : "Nothing to check"}
          </Button>
          {busy && state && (
            <span className="text-[12.5px] text-ink-300" role="status">
              {state.status === "scanning" ? "Reading chapters" : "Checking passages"}
              {state.total > 0 ? ` · ${state.done}/${state.total}` : "…"}
            </span>
          )}
        </div>
        <p className="mt-2 text-xs leading-relaxed text-ink-400">
          The first scan starts by itself when you translate, and the check runs when a translation
          finishes.
        </p>
        {(error || state?.error) && (
          <p className="mt-3 text-sm text-danger" role="alert">
            {error?.message ?? state?.error}
          </p>
        )}

        <MarkPassage book={book} disabled={busy} />

        <div className="mt-8 flex items-center gap-3">
          <p className={LABEL}>
            {open.length} to review · {all.length} in total
          </p>
          {all.length > open.length && (
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              className="rounded text-[12.5px] text-ink-300 underline-offset-2 hover:text-ink-100 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              {showAll ? "Show only those to review" : "Show all"}
            </button>
          )}
        </div>

        {passages.isLoading && <p className="mt-6 text-sm text-ink-400">Loading…</p>}
        {view && shown.length === 0 && (
          <p className="mt-6 text-sm text-ink-400">
            {all.length === 0
              ? state?.scanned
                ? "The scan found no special passages. If you know of one, mark it above."
                : "Nothing here yet. Scan the manuscript to find special passages."
              : "Nothing left to review."}
          </p>
        )}

        <div className="mt-4 space-y-6">
          {shown.map((p) => (
            <PassageCard key={p.id} bookId={book.id} passage={p} busy={busy} />
          ))}
        </div>
      </div>
    </div>
  );
}

function PassageCard({
  bookId,
  passage: p,
  busy,
}: {
  bookId: string;
  passage: Passage;
  busy: boolean;
}) {
  const resolve = useResolvePassage(bookId);
  const check = useCheckPassages(bookId);
  const update = useUpdatePassage(bookId);
  const [editing, setEditing] = useState<Record<string, string> | null>(null);
  const [rule, setRule] = useState<{ rule: string; message: string } | null>(null);

  const status = STATUS[p.status];
  const pending = resolve.isPending || check.isPending || update.isPending || busy;
  const rows = [...p.paragraphs, ...p.dependent_paragraphs];
  const changed = rows.some((r) => r.first_text != null && r.first_text !== r.text);
  const answered = p.flag != null && p.flag.status !== "open";
  const act = (body: Parameters<typeof resolve.mutate>[0]["body"]) =>
    resolve.mutate({ passageId: p.id, body });
  const error = resolve.error ?? check.error ?? update.error;

  return (
    <article className="rounded-lg border border-ink-700 bg-ink-800/50">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 pt-4">
        <h3 className="text-[15px] font-medium text-ink-50">{KIND_LABEL[p.kind]}</h3>
        <span className="text-[12.5px] text-ink-400">{p.chapter_label}</span>
        <span
          className={cn("ml-auto rounded-full border px-2.5 py-0.5 text-[11.5px]", status.tone)}
        >
          {status.label}
          {answered && p.status !== "dismissed" && p.status !== "author" ? " · accepted" : ""}
        </span>
      </header>

      <div className="space-y-3 px-5 pb-5 pt-3">
        <div>
          <p className={LABEL}>Rule</p>
          <p className="mt-1 text-sm leading-relaxed text-ink-100">
            {p.rule || "Not worked out yet. The first check does that."}
          </p>
          {(p.source_message || p.target_message) && (
            <p className="mt-1 font-mono text-[12.5px] text-ink-200">
              {p.source_message ?? "?"} → {p.target_message ?? "?"}
            </p>
          )}
          {p.origin === "author" && <p className="mt-1 text-xs text-ink-400">Marked by you.</p>}
        </div>

        {p.flag && <p className="text-sm leading-relaxed text-ink-200">{p.flag.question}</p>}
        {p.stale && (
          <p className="text-sm text-warning">
            The English changed after the last check. Check the passage again.
          </p>
        )}
        {p.problems.length > 0 && (
          <div>
            <p className={LABEL}>What the first translation got wrong</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-ink-200">
              {p.problems.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </div>
        )}

        <Rows
          title="Passage"
          rows={p.paragraphs}
          showFirst={changed}
          editing={editing}
          onEdit={setEditing}
        />
        {p.dependent_paragraphs.length > 0 && (
          <Rows
            title="Paragraphs that quote or decode it"
            rows={p.dependent_paragraphs}
            showFirst={changed}
            editing={editing}
            onEdit={setEditing}
          />
        )}

        {p.candidates.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-ink-300 hover:text-ink-100">
              {p.candidates.length} new translation{p.candidates.length === 1 ? "" : "s"} tried
            </summary>
            <div className="mt-2 space-y-3">
              {p.candidates.map((c, i) => (
                <div key={i} className="rounded-lg border border-ink-700 p-3">
                  <p className={LABEL}>
                    Version {i + 1} · {c.problems.length ? "failed the check" : "passed the check"}
                    {c.target_message ? ` · spells ${c.target_message}` : ""}
                  </p>
                  {c.paragraphs.map((cp) => (
                    <p key={cp.paragraph_id} className="mt-2 whitespace-pre-line text-ink-100">
                      {cp.text}
                    </p>
                  ))}
                  {c.notes && <p className="mt-2 text-xs text-ink-400">{c.notes}</p>}
                  {c.problems.map((x) => (
                    <p key={x} className="mt-1 text-xs text-danger">
                      {x}
                    </p>
                  ))}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mt-2"
                    disabled={pending}
                    onClick={() => act({ action: "use_candidate", candidate: i })}
                  >
                    Use this version
                  </Button>
                </div>
              ))}
            </div>
          </details>
        )}

        {rule && (
          <div className="space-y-2 rounded-lg border border-ink-700 p-3">
            <label className="block">
              <span className={LABEL}>Rule</span>
              <textarea
                className={cn(INPUT, "mt-1")}
                rows={3}
                value={rule.rule}
                onChange={(e) => setRule({ ...rule, rule: e.target.value })}
              />
            </label>
            {p.kind === "hidden_message" && (
              <label className="block">
                <span className={LABEL}>What the English should spell</span>
                <input
                  className={cn(INPUT, "mt-1")}
                  value={rule.message}
                  onChange={(e) => setRule({ ...rule, message: e.target.value })}
                />
              </label>
            )}
            <div className="flex gap-2">
              <Button
                variant="accent"
                size="sm"
                disabled={pending}
                onClick={() =>
                  update.mutate(
                    { passageId: p.id, rule: rule.rule, target_message: rule.message },
                    { onSuccess: () => setRule(null) },
                  )
                }
              >
                Save. The passage will be checked again
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setRule(null)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {error && (
          <p className="text-sm text-danger" role="alert">
            {error.message}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          {editing ? (
            <>
              <Button
                variant="accent"
                size="sm"
                disabled={pending}
                onClick={() =>
                  resolve.mutate(
                    {
                      passageId: p.id,
                      body: {
                        action: "edit",
                        paragraphs: Object.entries(editing).map(([paragraph_id, text]) => ({
                          paragraph_id,
                          text,
                        })),
                      },
                    },
                    { onSuccess: () => setEditing(null) },
                  )
                }
              >
                Save my text
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setEditing(null)}>
                Cancel
              </Button>
            </>
          ) : p.status === "dismissed" ? (
            <p className="text-xs text-ink-400">
              Translated like ordinary text. A new scan will not list it again.
            </p>
          ) : (
            <>
              {p.flag?.status === "open" && (
                <Button
                  variant="accent"
                  size="sm"
                  disabled={pending}
                  onClick={() => act({ action: "accept" })}
                >
                  Accept
                </Button>
              )}
              {p.translated && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={pending}
                  onClick={() =>
                    setEditing(Object.fromEntries(rows.map((r) => [r.paragraph_id, r.text ?? ""])))
                  }
                >
                  Edit the English
                </Button>
              )}
              {changed && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={pending}
                  onClick={() => act({ action: "restore" })}
                >
                  Restore the first translation
                </Button>
              )}
              {p.translated && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={pending}
                  onClick={() => check.mutate(p.id)}
                >
                  Check again
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                disabled={pending}
                onClick={() => setRule({ rule: p.rule, message: p.target_message ?? "" })}
              >
                Change the rule
              </Button>
              <Button
                variant="danger"
                size="sm"
                className="ml-auto"
                disabled={pending}
                title="Puts back the first translation and stops checking this passage"
                onClick={() => act({ action: "dismiss" })}
              >
                Not a special passage
              </Button>
            </>
          )}
        </div>
        {!p.translated && (
          <p className="text-xs text-ink-400">
            Not translated yet. It is checked after translation.
          </p>
        )}
      </div>
    </article>
  );
}

function Rows({
  title,
  rows,
  showFirst,
  editing,
  onEdit,
}: {
  title: string;
  rows: PassageParagraph[];
  showFirst: boolean;
  editing: Record<string, string> | null;
  onEdit: (next: Record<string, string>) => void;
}) {
  return (
    <div>
      <div className={cn("grid gap-x-5", showFirst ? "md:grid-cols-3" : "md:grid-cols-2")}>
        <p className={LABEL}>{title} · source</p>
        {showFirst && <p className={cn(LABEL, "hidden md:block")}>First translation</p>}
        <p className={cn(LABEL, "hidden md:block")}>English now</p>
      </div>
      {rows.map((r) => (
        <div
          key={r.paragraph_id}
          className={cn(
            "mt-2 grid gap-x-5 gap-y-1 border-t border-ink-700/60 pt-2 text-sm leading-relaxed",
            showFirst ? "md:grid-cols-3" : "md:grid-cols-2",
          )}
        >
          <p className="whitespace-pre-line text-ink-300">{r.source}</p>
          {showFirst && (
            <p className="whitespace-pre-line text-ink-400">{r.first_text ?? r.text ?? ""}</p>
          )}
          {editing && r.paragraph_id in editing ? (
            <textarea
              aria-label="English text of this paragraph"
              className={INPUT}
              rows={Math.min(
                14,
                Math.max(3, (editing[r.paragraph_id] ?? "").split("\n").length + 2),
              )}
              value={editing[r.paragraph_id]}
              onChange={(e) => onEdit({ ...editing, [r.paragraph_id]: e.target.value })}
            />
          ) : (
            <p className="whitespace-pre-line text-ink-100">
              {r.text ?? <span className="text-ink-500">Not translated yet</span>}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

/** Mark a run of paragraphs by hand, for passages the scan missed. */
function MarkPassage({ book, disabled }: { book: BookDetail; disabled: boolean }) {
  const create = useCreatePassage(book.id);
  const [chapterId, setChapterId] = useState(book.chapters[0]?.id ?? "");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [kind, setKind] = useState<PassageKind>("verse");
  const [rule, setRule] = useState("");

  const chapter = book.chapters.find((c) => c.id === chapterId);
  const options = (chapter?.paragraphs ?? [])
    .filter((p) => p.text.trim())
    .map((p, i) => ({ id: p.id, label: `${i + 1} · ${p.text.trim().slice(0, 70)}` }));

  return (
    <details className="mt-6 rounded-lg border border-ink-700 px-4 py-3">
      <summary className="cursor-pointer text-sm text-ink-200 hover:text-ink-50">
        Mark a passage yourself
      </summary>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <label className="block">
          <span className={LABEL}>Chapter</span>
          <select
            className={cn(INPUT, "mt-1")}
            value={chapterId}
            onChange={(e) => {
              setChapterId(e.target.value);
              setFirst("");
              setLast("");
            }}
          >
            {book.chapters.map((c, i) => (
              <option key={c.id} value={c.id}>
                {i + 1} · {(c.title ?? "").split("\n")[0]}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className={LABEL}>Kind</span>
          <select
            className={cn(INPUT, "mt-1")}
            value={kind}
            onChange={(e) => setKind(e.target.value as PassageKind)}
          >
            {Object.entries(KIND_LABEL).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className={LABEL}>First paragraph</span>
          <select
            className={cn(INPUT, "mt-1")}
            value={first}
            onChange={(e) => setFirst(e.target.value)}
          >
            <option value="">Choose…</option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className={LABEL}>Last paragraph</span>
          <select
            className={cn(INPUT, "mt-1")}
            value={last}
            onChange={(e) => setLast(e.target.value)}
          >
            <option value="">The same paragraph</option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block md:col-span-2">
          <span className={LABEL}>What the translation must keep (optional)</span>
          <input
            className={cn(INPUT, "mt-1")}
            value={rule}
            placeholder="Left empty, the first check works out the rule."
            onChange={(e) => setRule(e.target.value)}
          />
        </label>
      </div>
      {create.error && (
        <p className="mt-2 text-sm text-danger" role="alert">
          {create.error.message}
        </p>
      )}
      <Button
        variant="accent"
        size="sm"
        className="mt-3"
        disabled={disabled || !first || create.isPending}
        onClick={() =>
          create.mutate(
            { first_paragraph_id: first, last_paragraph_id: last || first, kind, rule },
            {
              onSuccess: () => {
                setFirst("");
                setLast("");
                setRule("");
              },
            },
          )
        }
      >
        Mark the passage
      </Button>
    </details>
  );
}
