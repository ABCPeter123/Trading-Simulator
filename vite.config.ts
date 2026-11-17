import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {target:"http://127.0.0.1:8000",proxyTimeout:660000,timeout:660000},
    },
  },
  // The public tunnel points ONLY at this production-bundle preview.
  // Never proxy its API to the private 8000 backend or expose Vite dev/HMR.
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    allowedHosts: [".trycloudflare.com"],
    proxy: {
      "/api": {target:"http://127.0.0.1:8001",proxyTimeout:660000,timeout:660000},
    },
  },
});
