import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
const cached =
  "/home/jyryu/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome";
export default defineConfig({
  testDir: "e2e",
  timeout: 60000,
  workers: 1,
  use: {
    baseURL: process.env.DOCKSCHEDULE_URL || "http://127.0.0.1:8890",
    viewport: { width: 1440, height: 1000 },
    launchOptions: {
      executablePath:
        process.env.CHROMIUM_PATH || (existsSync(cached) ? cached : undefined),
      args: [
        "--no-sandbox",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
      ],
    },
    screenshot: "only-on-failure",
  },
  outputDir: "../test-results/browser",
});
