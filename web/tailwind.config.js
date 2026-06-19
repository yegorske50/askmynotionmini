/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          50: "#f7f7f8",
          100: "#eeeef0",
          200: "#d8d8dd",
          300: "#b5b5be",
          400: "#8a8a96",
          500: "#6c6c78",
          600: "#53535d",
          700: "#3f3f48",
          800: "#2a2a30",
          900: "#1a1a1f",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Inter",
          "Segoe UI",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
