import { useCallback, useRef, useState, type DragEvent } from "react";
import { FileUp, Loader2, AlertCircle } from "lucide-react";

import { useUploadBook } from "@/lib/api/hooks";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";

interface Props {
  onUploaded?: (bookId: string) => void;
}

const SOURCE_LANGUAGES = [
  { value: "pl", label: "Polish" },
  { value: "de", label: "German" },
  { value: "en", label: "English" },
];

export function UploadDropzone({ onUploaded }: Props) {
  const upload = useUploadBook();
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceLanguage, setSourceLanguage] = useState("pl");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File) => {
      setError(null);
      if (!file.name.toLowerCase().endsWith(".docx")) {
        setError("Only .docx manuscripts are supported.");
        return;
      }
      upload.mutate(
        { file, sourceLanguage },
        {
          onSuccess: (data) => onUploaded?.(data.book.id),
          onError: (err) => {
            setError(err instanceof ApiError ? err.detail : "Upload failed.");
          },
        },
      );
    },
    [upload, onUploaded, sourceLanguage],
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
      <label htmlFor="source-language" className="text-xs text-ink-300">
        Manuscript language
      </label>
      <select
        id="source-language"
        value={sourceLanguage}
        onChange={(e) => setSourceLanguage(e.target.value)}
        disabled={isUploading}
        className="w-full rounded-md border border-ink-600 bg-ink-800 px-2 py-1.5 text-sm text-ink-100"
      >
        {SOURCE_LANGUAGES.map((lang) => (
          <option key={lang.value} value={lang.value}>
            {lang.label}
          </option>
        ))}
      </select>
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
          "flex flex-col items-center justify-center gap-2 rounded-lg",
          "border border-dashed py-8 px-4 cursor-pointer text-center",
          "transition-colors duration-150 ease-out",
          "focus-within:ring-2 focus-within:ring-accent focus-within:ring-offset-2",
          "focus-within:ring-offset-ink-900",
          dragOver
            ? "border-accent bg-accent-soft"
            : "border-ink-600 hover:border-ink-500 hover:bg-ink-800",
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
            <Loader2 className="h-5 w-5 animate-spin text-accent" />
            <span className="text-sm text-ink-200">Parsing manuscript…</span>
          </>
        ) : (
          <>
            <FileUp className="h-5 w-5 text-ink-300" aria-hidden />
            <span className="text-sm text-ink-100">
              <span className="font-medium text-accent">Choose a file</span>
              <span className="text-ink-300"> or drag a .docx here</span>
            </span>
            <span className="text-xs text-ink-400">Up to 50 MB</span>
          </>
        )}
      </label>

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-danger-border bg-danger-surface px-3 py-2 text-xs text-danger"
        >
          <AlertCircle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
