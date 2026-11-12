/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],

  // Theme switching is driven by a `data-theme="dark"` attribute on
  // <html>, set by useTheme. `selector` strategy lets us key off any
  // attribute, but Tailwind v3.4+ supports the simpler form below.
  darkMode: ["selector", '[data-theme="dark"]'],

  theme: {
    extend: {
      fontFamily: {
        // Three voices, each with one job:
        // - serif (Lora): the book's text and headings — the title,
        //   section headings, chapter headings, names of terms and
        //   characters, and every paragraph of prose.
        // - sans (Inter, the default): everything you operate — buttons,
        //   controls, explanations, status lines.
        // - mono (JetBrains Mono): short labels in capitals, numbers,
        //   model names and file names.
        sans: ["Inter", "system-ui", "sans-serif"],
        serif: ["Lora", "Georgia", "serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },

      // The type scale. Use these names, not pixel sizes, so the same
      // role has the same size on every screen.
      fontSize: {
        // Labels in capitals, badges, numbers and other small print (mono).
        label: ["11px", { lineHeight: "16px" }],
        // Helper text, captions, secondary lines.
        small: ["12px", { lineHeight: "18px" }],
        // Default for controls and explanations.
        body: ["13px", { lineHeight: "20px" }],
        // Prose of the book, source and English (serif).
        reading: ["16px", { lineHeight: "1.7" }],
        // Names of terms, characters, passages and books (serif).
        subheading: ["17px", { lineHeight: "24px" }],
        // Section headings: Terms, Profiles, Chapters, Export (serif).
        heading: ["22px", { lineHeight: "28px" }],
        // The book's title (serif).
        title: ["28px", { lineHeight: "34px" }],
      },

      // The palette is now driven by CSS variables defined in index.css.
      // Existing component code referencing `bg-ink-900`, `text-ink-50`,
      // `text-accent`, etc. continues to work — the names are stable;
      // only what the names *resolve to* now flows from the active theme.
      //
      // Keeping the legacy `ink-N` and `accent-*` names (rather than
      // renaming everything) means this refactor is one-file rather than
      // a 200-site sweep, and any future Cursor-generated component
      // immediately picks up the right palette without our review.
      colors: {
        ink: {
          DEFAULT: "var(--color-text-primary)",
          50: "var(--color-text-primary)",
          100: "var(--color-text-primary)",
          200: "var(--color-text-secondary)",
          300: "var(--color-text-secondary)",
          400: "var(--color-text-tertiary)",
          500: "var(--color-text-tertiary)",
          600: "var(--color-border)",
          700: "var(--color-border)",
          800: "var(--color-surface-elevated)",
          900: "var(--color-surface)",
          950: "var(--color-surface)",
        },
        accent: {
          DEFAULT: "var(--color-accent)",
          // Legacy alias: `accent-pink` (originally a secondary accent
          // for chapter titles) now maps to the same clay as `accent`.
          // Kept so existing JSX doesn't break; visually merged.
          pink: "var(--color-accent)",
          // Soft / lighter accent for hover states and subtle fills.
          soft: "var(--color-accent-soft)",
        },

        // Semantic status tokens. Components that previously hardcoded
        // `text-emerald-300`, `border-red-900/60`, etc. should be moved
        // here — those raw Tailwind colors don't adapt across modes.
        success: {
          DEFAULT: "var(--color-success)",
          surface: "var(--color-success-surface)",
          border: "var(--color-success-border)",
        },
        warning: {
          DEFAULT: "var(--color-warning)",
          surface: "var(--color-warning-surface)",
          border: "var(--color-warning-border)",
        },
        danger: {
          DEFAULT: "var(--color-danger)",
          surface: "var(--color-danger-surface)",
          border: "var(--color-danger-border)",
        },
      },

      maxWidth: {
        prose: "68ch",
      },
    },
  },
  plugins: [],
};
