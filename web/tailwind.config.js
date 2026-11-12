/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        asphalt: "#0f172a",
        panel: "#111c2e",
        hairline: "#1f2f45",
        ink: "#e5edf7",
        muted: "#8ba0b8",
        accent: "#38bdf8",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
        ui: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
