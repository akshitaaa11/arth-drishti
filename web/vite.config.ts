import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API serves the built dashboard at /app; in development, proxy API calls to uvicorn on :8000.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      ["budgets", "sectors", "stocks", "backtest", "simulate", "credibility", "ledger", "sources", "health"].map((p) => [`/${p}`, "http://127.0.0.1:8000"]),
    ),
  },
  build: { outDir: "dist", sourcemap: false },
});
