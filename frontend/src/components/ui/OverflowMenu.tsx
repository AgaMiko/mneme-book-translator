import { useEffect, useRef, useState } from "react";
import { MoreHorizontal, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export interface OverflowMenuItem {
  label: string;
  icon: LucideIcon;
  onClick: () => void;
  /** Red styling for destructive items. */
  danger?: boolean;
  disabled?: boolean;
}

interface Props {
  items: OverflowMenuItem[];
  disabled?: boolean;
  /** Announced to screen readers in place of "More actions". */
  label?: string;
}

/**
 * The secondary-actions menu behind a row or card. Everything that is
 * real but rare lives here — merges, flags, resets — so the one or two
 * actions you take constantly can stay visible and unambiguous.
 *
 * Closes on outside click and on Escape; items are plain buttons, so
 * confirmation dialogs stay in the caller's hands.
 */
export function OverflowMenu({ items, disabled = false, label = "More actions" }: Props) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={wrapRef}>
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-transparent text-ink-400",
          "hover:border-ink-700 hover:bg-ink-800 hover:text-ink-200",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          "disabled:pointer-events-none disabled:opacity-40",
          open && "border-ink-700 bg-ink-800 text-ink-100",
        )}
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden />
        <span className="sr-only">{label}</span>
      </button>
      {open ? (
        <ul
          role="menu"
          className={cn(
            "absolute right-0 top-full z-30 mt-1 min-w-[14rem] rounded-lg border border-ink-700 bg-ink-900 py-1 shadow-xl",
            "ring-1 ring-black/20",
          )}
        >
          {items.map((item) => (
            <li key={item.label} role="presentation">
              <button
                type="button"
                role="menuitem"
                disabled={item.disabled}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-2 text-left text-body",
                  item.danger
                    ? "text-danger hover:bg-danger-surface focus-visible:bg-danger-surface"
                    : "text-ink-100 hover:bg-ink-800 focus-visible:bg-ink-800",
                  "focus-visible:outline-none disabled:pointer-events-none disabled:opacity-40",
                )}
                onClick={(e) => {
                  e.stopPropagation();
                  item.onClick();
                  setOpen(false);
                }}
              >
                <item.icon
                  className={cn(
                    "h-3.5 w-3.5 shrink-0",
                    item.danger ? "opacity-80" : "text-ink-500",
                  )}
                  aria-hidden
                />
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
