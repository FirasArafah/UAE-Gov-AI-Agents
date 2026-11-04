import { defineConfig } from "vite";

const target = process.env.API_TARGET || "http://localhost:8000";

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 5173,
    // File-change events do not cross a Windows/macOS bind mount into the container.
    watch: process.env.VITE_POLL ? { usePolling: true, interval: 300 } : undefined,
    allowedHosts: [".trycloudflare.com"],
    proxy: {
      "/api": {
        target,
        changeOrigin: true,
        ws: true, // the chat's WebSocket under /api/ws
      },
    },
  },
});