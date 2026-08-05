/** @type {import('tailwindcss').Config} */

// Palette and type roles per the Phase 6 design plan (spec Part 11.1).
// Concept: the official FIA session timing document, annotated — warm paper
// stock, monospaced numerals, hairline rules, no decoration. Deliberately
// not a dark dashboard with neon accents: spec 11.2 mandates team colours
// for driver lines, and 10+ saturated hues on a dark field all glow and stop
// separating. Neutral paper chrome makes team colour the only saturated
// thing on screen, which is what should carry the data.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F4F1EA", // page; document stock
        ink: "#1A1917", // all text, real-timeline lines, axes (~14:1 on paper)
        rule: "#C9C3B6", // hairlines, gridlines, table rules. never text
        wash: "#E8E4DA", // panel fills, selected rows
        // Counterfactual ONLY. Oxide red, an editor's mark — not a racing
        // red. Hairlines and small marks only, never a large fill.
        annotation: "#A33A2E",
        // Epistemic warning ONLY: "this answer is past its evidence."
        // Extrapolation laps, long drift horizons, prior-driven parameters.
        caution: "#A8761F",
      },
      fontFamily: {
        // Every numeral: lap times, deltas, gaps, positions, timing tower.
        mono: ["'IBM Plex Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
        // UI labels, section headers, axis labels. The form-field voice.
        sans: ["Archivo", "ui-sans-serif", "system-ui", "sans-serif"],
        // Prose only: narrative summaries, methodology caveats. The
        // marginalia voice. If this appears near a number, it's a mistake.
        serif: ["Spectral", "ui-serif", "Georgia", "serif"],
      },
      fontSize: {
        micro: ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.08em" }],
      },
    },
  },
  plugins: [],
};
