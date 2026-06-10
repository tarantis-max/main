import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the Node proxy (dashboard/server.js) so the
// browser never needs Jira credentials. In production server.js serves
// the built app from app/dist directly — same origin, no proxy needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8787" },
  },
});
