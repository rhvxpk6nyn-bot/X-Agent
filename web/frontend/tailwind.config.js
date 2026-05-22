/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "#0A0A0B",
        layer1: "#141416",
        layer2: "#1C1C1F",
        layer3: "#252528",
        accent: "#6C5CE7",
        accent2: "#00D2FF",
        "text-primary": "#EDEDEF",
        "text-secondary": "#8B8B90",
        "text-tertiary": "#5C5C60",
        success: "#20C05C",
        warning: "#F5A623",
        error: "#F54B4B",
        border: "#1E1E22",
        "border-medium": "#2E2E34",
      },
      fontFamily: {
        sans: ['"SF Pro Display"', '"Inter"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', '"Fira Code"', "monospace"],
      },
    },
  },
  plugins: [],
};
