/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./web/index.html",
    "./web/app.js",
    "./web/js/**/*.js"
  ],
  theme: {
    extend: {
      colors: {
        base: "#0f1115",
        sidebar: "#161b22",
        card: "#1e293b",
        "card-hover": "#283548",
        "border-subtle": "rgba(255, 255, 255, 0.05)",
        "border-light": "rgba(255, 255, 255, 0.1)"
      }
    }
  },
  plugins: []
};







