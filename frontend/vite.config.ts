import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const target = process.env.API_TARGET ?? "http://127.0.0.1:8000";
const url = new URL(target);
if (
  !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) ||
  url.protocol !== "http:"
) {
  throw new Error("API_TARGET must be a local HTTP API");
}
const proxy = { "/api": { target, changeOrigin: false } };
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy },
  preview: { host: "127.0.0.1", port: 5173, strictPort: true, proxy },
});
