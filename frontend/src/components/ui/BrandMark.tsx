import type { SVGProps } from "react";

import { cn } from "@/lib/utils";

interface Props extends Omit<SVGProps<SVGSVGElement>, "children"> {
  /** Override the default size (24px). Used as both width and height. */
  size?: number;
  /**
   * When `true` the brackets and the M share the same color. When `false`
   * (default) the brackets carry the clay accent and the M takes on the
   * surrounding text color, which is how the brand board renders the
   * primary mark.
   */
  monochrome?: boolean;
}

/**
 * The Mneme brand mark.
 *
 * Two squared brackets framing a serif M, with two small horizontal rule
 * marks suggesting page lines on either side. Reads as both a letter and
 * an icon of "text in brackets" — which is what translation does to the
 * source. Renders crisply at any size; used in the sidebar, empty state,
 * and (rasterized via the favicon) browser chrome.
 *
 * Colors flow from CSS variables via Tailwind's `text-accent` / `text-current`.
 * That means the mark adapts to the active theme without prop changes.
 */
export function BrandMark({ size = 24, monochrome = false, className, ...props }: Props) {
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Mneme"
      className={cn("shrink-0", className)}
      {...props}
    >
      {/* Left bracket */}
      <path
        d="M14 8 H8 V56 H14"
        stroke={monochrome ? "currentColor" : "var(--color-accent)"}
        strokeWidth="2.5"
        strokeLinecap="square"
        strokeLinejoin="miter"
      />
      {/* Right bracket */}
      <path
        d="M50 8 H56 V56 H50"
        stroke={monochrome ? "currentColor" : "var(--color-accent)"}
        strokeWidth="2.5"
        strokeLinecap="square"
        strokeLinejoin="miter"
      />
      {/* Page-line decorations on the left */}
      <line
        x1="16.5"
        y1="22"
        x2="22.5"
        y2="22"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.55"
      />
      <line
        x1="16.5"
        y1="28"
        x2="22.5"
        y2="28"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.55"
      />
      <line
        x1="16.5"
        y1="34"
        x2="22.5"
        y2="34"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.55"
      />
      <line
        x1="16.5"
        y1="40"
        x2="22.5"
        y2="40"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.55"
      />
      {/* Page-line decorations on the right */}
      <line
        x1="41.5"
        y1="22"
        x2="47.5"
        y2="22"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.55"
      />
      <line
        x1="41.5"
        y1="28"
        x2="47.5"
        y2="28"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.55"
      />
      <line
        x1="41.5"
        y1="34"
        x2="47.5"
        y2="34"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.55"
      />
      <line
        x1="41.5"
        y1="40"
        x2="47.5"
        y2="40"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.55"
      />
      {/* The M — serif, slightly heavier than the brackets so it earns
          its place as the focal element. */}
      <text
        x="32"
        y="42"
        textAnchor="middle"
        fontFamily="Lora, Georgia, serif"
        fontSize="28"
        fontWeight="600"
        fill="currentColor"
      >
        M
      </text>
    </svg>
  );
}
