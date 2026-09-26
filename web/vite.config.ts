import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs separately; in the image FastAPI serves this build.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8080", "/static": "http://127.0.0.1:8080" } },
  build: { outDir: "dist", sourcemap: false },
});
