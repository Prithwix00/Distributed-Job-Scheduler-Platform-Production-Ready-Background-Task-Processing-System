/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        ink: {
          900: "#0b0f14", 800: "#11161d", 700: "#171d26", 600: "#1e2630", 500: "#2a333f",
        },
        signal: {
          queued: "#5b8def", scheduled: "#a06bff", running: "#f0a63a",
          completed: "#2fbf88", dead: "#e5484d", cancelled: "#7a8699",
        },
      },
    },
  },
  plugins: [],
};
