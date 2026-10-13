import { defineConfig } from "@playwright/test";
const artifactDir = process.env.BROWSER_ARTIFACT_DIR || "../artifacts/m5";
const recording = process.env.DEMO_RECORD === "true";
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  retries: 0,
  timeout: recording ? 600_000 : 240_000,
  expect: { timeout: 60_000 },
  reporter: [
    ["list"],
    ["json", { outputFile: `${artifactDir}/browser_results.json` }],
  ],
  use: {
    baseURL: process.env.BROWSER_BASE_URL || "http://127.0.0.1:5174",
    actionTimeout: 15_000,
    channel: "msedge",
    viewport: { width: 1366, height: 900 },
    headless: true,
    trace: "off",
    screenshot: "only-on-failure",
    video: recording
      ? { mode: "on", size: { width: 1366, height: 900 } }
      : "off",
  },
});
