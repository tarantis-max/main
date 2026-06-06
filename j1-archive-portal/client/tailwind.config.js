/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: '#024D36', light: '#035940', gold: '#FBBF16' },
      },
    },
  },
  plugins: [],
};
