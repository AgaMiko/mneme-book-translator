import { useState } from "react";

import { BookList } from "@/components/BookList";
import { BookReader } from "@/components/BookReader";
import { UploadDropzone } from "@/components/UploadDropzone";
import { BrandMark } from "@/components/ui/BrandMark";
import { ThemeToggle } from "@/components/ui/ThemeToggle";

export default function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-ink-900 text-ink-50">
      {/* Sidebar */}
      <aside className="flex w-80 shrink-0 flex-col border-r border-ink-800 bg-ink-900">
        <header className="border-b border-ink-800 px-5 py-5">
          <div className="flex items-center gap-2.5">
            <BrandMark size={28} className="text-ink-100" />
            <div className="min-w-0">
              <h1 className="font-serif text-xl font-semibold leading-none text-ink-100">Mneme</h1>
              <p className="mt-1 font-serif text-[11px] italic leading-none text-ink-400">Μνήμη</p>
            </div>
          </div>
          <p className="mt-3 text-xs leading-snug text-ink-500">Translation that remembers.</p>
          <p className="mt-2 font-mono text-[10px] uppercase tracking-wider text-ink-500">
            pl → en
          </p>
        </header>

        <div className="border-b border-ink-800 p-4">
          <UploadDropzone onUploaded={setSelectedId} />
        </div>

        <div className="flex-1 overflow-y-auto p-3">
          <p className="mb-2 px-2 text-xs uppercase tracking-wider text-ink-400">Library</p>
          <BookList
            selectedId={selectedId}
            onSelect={setSelectedId}
            onDeleted={(id) => {
              if (id === selectedId) setSelectedId(null);
            }}
          />
        </div>

        <footer className="flex items-center justify-between border-t border-ink-800 px-4 py-2.5">
          <p className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
            mneme · v0.1
          </p>
          <ThemeToggle />
        </footer>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-hidden">
        {selectedId ? <BookReader bookId={selectedId} /> : <EmptyState />}
      </main>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="reader-surface flex h-full items-center justify-center">
      <div className="max-w-md px-6 text-center">
        {/* Brand mark — bigger here than in the sidebar; this is the
            empty-state hero, the moment the brand can speak. */}
        <BrandMark size={72} className="mx-auto text-ink-100" />
        <h2 className="mt-8 font-serif text-3xl text-ink-50">We keep what matters.</h2>
        <p className="mt-3 font-serif text-lg italic text-ink-300">So your story stays whole.</p>
        <p className="mt-8 text-sm leading-relaxed text-ink-400">
          Drop a <span className="font-mono text-xs text-ink-200">.docx</span> into the sidebar.
          Mneme will read your book end to end, build a glossary you can review, and remember every
          decision you make as translation proceeds.
        </p>
        <p className="mt-5 text-xs leading-relaxed text-ink-500">
          AI drafts. You decide. The book stays whole.
        </p>
      </div>
    </div>
  );
}
