import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  if (!!env.DEV_TLS_CERT !== !!env.DEV_TLS_KEY)
    throw new Error(
      "DEV_TLS_CERT and DEV_TLS_KEY must be configured together.",
    );
  const https = env.DEV_TLS_CERT
    ? {
        cert: readFileSync(env.DEV_TLS_CERT),
        key: readFileSync(env.DEV_TLS_KEY),
      }
    : undefined;
  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      https,
      proxy: {
        "/api": {
          target: env.BACKEND_URL || "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
    preview: { host: "0.0.0.0" },
    build: { target: "es2022" },
  };
});
