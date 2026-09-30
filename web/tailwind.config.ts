import type { Config } from "tailwindcss";

// The approved palette (docs/design/README.md). Every value is a CSS variable set in
// app/globals.css, so the tokens live in exactly one place.
const v = (name: string) => `var(--${name})`;

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"), "bg-2": v("bg-2"),
        surface: v("surface"), "surface-2": v("surface-2"), "surface-3": v("surface-3"),
        line: v("line"), "line-soft": v("line-soft"),
        text: v("text"), muted: v("muted"), faint: v("faint"),
        amber: v("ochre"), "amber-2": v("ochre-2"),
        rust: v("rust"), sage: v("sage"), "sage-text": v("sage-text"),
        slate: v("slate"), water: v("water"), live: v("live"),
      },
      fontFamily: { sans: v("sans"), mono: v("mono") },
      borderRadius: { card: "10px" },
    },
  },
  plugins: [],
} satisfies Config;
