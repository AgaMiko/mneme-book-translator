import { useCallback, useRef, useState, type DragEvent } from "react";
import { AlertCircle, FileUp, Loader2, Plus } from "lucide-react";

import { useUploadBook } from "@/lib/api/hooks";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";

interface Props {
  onUploaded?: (bookId: string) => void;
}

export function UploadDropzone({ onUploaded }: Props) {
  const upload = useUploadBook();
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File) => {
      setError(null);
      if (!file.name.toLowerCase().endsWith(".docx")) {
        setError("Only .docx manuscripts are supported.");
        return;
      }
      upload.mutate(file, {
        onSuccess: (data) => onUploaded?.(data.book.id),
        onError: (err) => {
          setError(err instanceof ApiError ? err.detail : "Upload failed.");
        },
      });
    },
    [upload, onUploaded],
  );

  const onDrop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  const isUploading = upload.isPending;

  return (
    <div className="space-y-2">
      {/*
       * A bar, not a panel. On the library screen the list of manuscripts
       * is the subject; upload is one action above it and should occupy an
       * action's worth of space. Dropping still works — the whole bar is
       * the drop target — so the affordance is not lost by shrinking it.
       */}
      <label
        onDragEnter={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={cn(
          "flex h-[38px] w-full cursor-pointer items-center justify-center gap-2 rounded-lg border",
          "text-body font-medium transition-colors duration-150 ease-out",
          "focus-within:outline-none focus-within:ring-2 focus-within:ring-accent",
          dragOver
            ? "border-accent bg-accent-soft text-accent"
            : "border-ink-700 bg-ink-800 text-ink-100 hover:border-accent",
          isUploading && "pointer-events-none opacity-70",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".docx"
          className="sr-only"
          disabled={isUploading}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
            e.target.value = "";
          }}
        />
        {isUploading ? (
          <>
            <Loader2 className="h-[15px] w-[15px] animate-spin text-accent" aria-hidden />
            Parsing manuscript…
          </>
        ) : (
          <>
            {dragOver ? (
              <FileUp className="h-[15px] w-[15px]" aria-hidden />
            ) : (
              <Plus className="h-[15px] w-[15px] text-accent" aria-hidden />
            )}
            {dragOver ? "Drop to upload" : "Upload manuscript"}
          </>
        )}
      </label>
      <p className="mt-2 text-center text-small text-ink-500">or drop a .docx here · max 50 MB</p>

      {error && (
        <div
          role="alert"
          className="mt-2 flex items-start gap-2 rounded-lg border border-danger-border bg-danger-surface px-3 py-2 text-small text-danger"
        >
          <AlertCircle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
