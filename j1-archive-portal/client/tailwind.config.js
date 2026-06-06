/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: '#002147', light: '#003366', gold: '#B5A268' },
      },
    },
  },
  plugins: [],
};
