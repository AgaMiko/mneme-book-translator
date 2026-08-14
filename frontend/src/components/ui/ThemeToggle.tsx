import { Moon, Sun } from "lucide-react";

import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";

interface Props {
  className?: string;
}

/**
 * Quiet two-state theme toggle. Sun in dark mode (it's what you'd switch
 * *to*), moon in light mode. No text label — the icon and the title
 * attribute are enough; this lives in the sidebar footer next to the
 * version stamp and shouldn't shout for attention.
 */
export function ThemeToggle({ className }: Props) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggleTheme}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className={cn(
        "inline-flex h-7 w-7 items-center justify-center rounded-lg",
        "text-ink-400 transition-colors duration-150 ease-out",
        "hover:bg-ink-700 hover:text-ink-100",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        className,
      )}
    >
      {isDark ? (
        <Sun className="h-3.5 w-3.5" aria-hidden />
      ) : (
        <Moon className="h-3.5 w-3.5" aria-hidden />
      )}
    </button>
  );
}
