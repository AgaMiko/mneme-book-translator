import { BookList } from "@/components/BookList";
import { UploadDropzone } from "@/components/UploadDropzone";
import { BrandMark } from "@/components/ui/BrandMark";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { useBooks } from "@/lib/api/hooks";

interface Props {
  onSelect: (id: string) => void;
}

/**
 * The library — one of two screens. Everything that used to be crammed
 * into a 320px rail gets the whole window here: the brand can speak, the
 * dropzone is a target rather than a sliver, and the book rows have room
 * to report where each manuscript stands.
 *
 * Opening a book replaces this screen entirely; there is no permanent
 * sidebar to navigate back through, only the `← Library` button in the
 * book header.
 */
export function LibraryScreen({ onSelect }: Props) {
  const { data } = useBooks();
  const isEmpty = data != null && data.length === 0;

  return (
    <div className="reader-surface flex h-full min-h-0 w-full flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-[760px] flex-1 px-6">
        <header className="pt-16">
          <div className="flex items-center gap-3">
            <BrandMark size={36} className="text-ink-100" />
            <div className="min-w-0">
              <h1 className="font-serif text-2xl font-semibold leading-none text-ink-100">Mneme</h1>
              <p className="mt-1.5 font-serif text-[11px] italic leading-none text-ink-400">
                Μνήμη
              </p>
            </div>
          </div>
          <p className="mt-4 text-sm leading-snug text-ink-400">Translation that remembers.</p>
        </header>

        {/* The brand's promise only earns this much room when there is
            nothing else on the screen to look at. */}
        {isEmpty && (
          <div className="mt-12 max-w-prose">
            <h2 className="font-serif text-2xl text-ink-50">We keep what matters.</h2>
            <p className="mt-2 font-serif text-lg italic text-ink-300">
              So your story stays whole.
            </p>
            <p className="mt-5 text-sm leading-relaxed text-ink-400">
              Drop a <span className="font-mono text-xs text-ink-200">.docx</span> below. Mneme will
              read your book end to end, build a glossary you can review, and remember every
              decision you make as translation proceeds.
            </p>
          </div>
        )}

        <div className="mt-10">
          <UploadDropzone onUploaded={onSelect} />
        </div>

        <div className="mt-12 pb-16">
          <div className="mb-3 flex items-center gap-2">
            <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">Library</p>
            {data && data.length > 0 && (
              <span className="font-mono text-[10px] tabular-nums text-ink-400">{data.length}</span>
            )}
          </div>
          <BookList selectedId={null} onSelect={onSelect} onDeleted={() => {}} />
        </div>
      </div>

      <footer className="mx-auto flex w-full max-w-[760px] items-center justify-between border-t border-ink-800 px-6 py-3">
        <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">mneme · v0.1</p>
        <ThemeToggle />
      </footer>
    </div>
  );
}
