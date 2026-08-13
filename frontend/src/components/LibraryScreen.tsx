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
        <header className="flex items-center justify-between gap-2.5 pt-16">
          <div className="flex min-w-0 items-center gap-2.5">
            <BrandMark size={26} className="text-ink-100" />
            <div className="min-w-0">
              {/* Greek sits beside the wordmark, not under it — one
                  line of brand rather than a stacked lockup. */}
              <div className="flex items-baseline gap-[7px]">
                <h1 className="font-serif text-[19px] font-semibold leading-none text-ink-100">
                  Mneme
                </h1>
                <span className="font-serif text-xs italic text-ink-500">Μνήμη</span>
              </div>
              <p className="mt-[5px] text-xs leading-none text-ink-400">
                Translation that remembers.
              </p>
            </div>
          </div>
          <ThemeToggle />
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

        <div className="mt-6">
          <UploadDropzone onUploaded={onSelect} />
        </div>

        <div className="pb-8 pt-4">
          <div className="mb-2 flex items-center justify-between px-0.5">
            <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">Library</p>
            {data && data.length > 0 && (
              <span className="font-mono text-[10px] tabular-nums text-ink-600">{data.length}</span>
            )}
          </div>
          <BookList selectedId={null} onSelect={onSelect} onDeleted={() => {}} />
        </div>
      </div>

      <footer className="mx-auto flex w-full max-w-[760px] items-center justify-between border-t border-ink-800 px-6 py-3">
        <p className="font-mono text-[10px] uppercase tracking-wider text-ink-600">mneme · v0.1</p>
        <span className="font-mono text-[10px] uppercase tracking-wider text-ink-600">pl → en</span>
      </footer>
    </div>
  );
}
