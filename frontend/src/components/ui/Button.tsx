import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type Variant = "primary" | "accent" | "ghost" | "danger";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

/**
 * Button variants reference the semantic accent / status tokens, not
 * raw Tailwind colors. Each token resolves to a different actual hex
 * in light vs. dark mode (via CSS variables in index.css), so these
 * variants automatically work in both modes without `dark:` overrides.
 *
 * `primary` uses the clay accent on a white-text body — adequate
 * contrast in both modes because clay is mid-tone and stays roughly
 * the same lightness across modes.
 */
const variants: Record<Variant, string> = {
  primary:
    "bg-accent text-white hover:opacity-90 active:translate-y-px " + "focus-visible:ring-accent",
  // Clay outline. The quiet-but-affirmative variant the row-level
  // `Accept` actions use — clearly the positive choice without competing
  // with the one solid `primary` button per screen.
  // `accent-soft` is already a translucent clay wash and the palette
  // cannot express a second opacity step, so hover shifts the whole
  // button rather than just its fill.
  accent:
    "border border-accent bg-accent-soft text-accent hover:opacity-80 " +
    "focus-visible:ring-accent",
  ghost: "text-ink-100 hover:bg-ink-800 active:bg-ink-700 " + "focus-visible:ring-ink-300",
  danger:
    "text-ink-100 hover:bg-danger-surface hover:text-danger active:bg-danger-surface " +
    "focus-visible:ring-danger",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-[12.5px]",
  md: "h-9 px-4 text-[13px]",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", className, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium",
        "transition-colors duration-150 ease-out",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
        "focus-visible:ring-offset-ink-900",
        "disabled:pointer-events-none disabled:opacity-40",
        sizes[size],
        variants[variant],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
