/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        // Distinctive but readable: a modern grotesk for UI chrome,
        // a literary serif for the manuscript reader, mono for technical bits.
        sans: ["Geist", "system-ui", "sans-serif"],
        serif: ["Lora", "Georgia", "serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        // Neutrals + dual accent: lime (primary chrome, CTAs) and pink (highlights, prose).
        ink: {
          DEFAULT: "#0a0a0a",
          50: "#f7f7f6",
          100: "#ececea",
          200: "#d6d6d2",
          300: "#a8a8a3",
          400: "#787873",
          500: "#525250",
          600: "#3a3a38",
          700: "#26262a",
          800: "#181818",
          900: "#0a0a0a",
        },
        accent: {
          DEFAULT: "#bef264", // lime — buttons, rings, drop caps
          lime: "#d9f99d", // lighter lime for hovers from dark lime fills
          soft: "#fbcfe8", // pink-200 — subtle fills, borders on dark
          pink: "#f472b6", // pink-400 — chapter titles, secondary emphasis
        },
      },
      maxWidth: {
        prose: "68ch",
      },
    },
  },
  plugins: [],
};
