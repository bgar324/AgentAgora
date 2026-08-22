import path from "node:path"

import { defineConfig } from "@playwright/test"

const repositoryRoot = path.resolve(__dirname, "..")

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://localhost:3011",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command:
        `${repositoryRoot}/.venv/bin/uvicorn e2e_server:app ` +
        "--app-dir tests --host 127.0.0.1 --port 8011",
      cwd: repositoryRoot,
      url: "http://127.0.0.1:8011/api/v1/focused/health",
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        PYTHONPATH: path.join(repositoryRoot, "src"),
      },
    },
    {
      command: "pnpm dev -p 3011",
      cwd: __dirname,
      url: "http://localhost:3011/focused",
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        API_URL: "http://127.0.0.1:8011",
        NEXT_DIST_DIR: ".next-e2e",
      },
    },
  ],
})
