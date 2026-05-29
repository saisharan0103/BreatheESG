/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#0F4C3A",
          50: "#E7F1ED",
          100: "#C5E0D5",
          500: "#0F4C3A",
          600: "#0C3D2F",
          700: "#082E23",
        },
      },
    },
  },
  plugins: [],
};
