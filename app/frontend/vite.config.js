import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Dev server proxies /api to the FastAPI backend on :8000.
// Production build emits to dist/, which app.py serves.
export default defineConfig({
    plugins: [react()],
    build: { outDir: "dist" },
    server: {
        port: 5173,
        proxy: { "/api": "http://localhost:8000" },
    },
});
