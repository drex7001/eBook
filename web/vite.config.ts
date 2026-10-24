import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies the API to the Python server on :8000
export default defineConfig({
  plugins: [react()],
  server: { host: true, proxy: { "/api": "http://localhost:8000" } },
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 800 },
});
