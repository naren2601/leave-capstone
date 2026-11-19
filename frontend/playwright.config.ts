import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end tests: a real browser drives the real app, which talks to the real API.
 *
 * - By default they run against the dev server (`npm start`, port 4200). Start the API
 *   first (start-dev.ps1 does both); Playwright starts `npm start` itself if it is not
 *   already running.
 * - Set E2E_BASE_URL to test somewhere else, for example the Docker web service:
 *   `$env:E2E_BASE_URL="http://localhost:8080"; npm run e2e`
 */
const externalUrl = process.env['E2E_BASE_URL'];

export default defineConfig({
  testDir: './e2e',
  // The tests share the demo users and their balances, so they run one at a time.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env['CI'],
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  globalSetup: './e2e/global-setup.ts',
  use: {
    baseURL: externalUrl ?? 'http://localhost:4200',
    // On a failure, keep a trace (open it with `npx playwright show-trace`) and a screenshot.
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: externalUrl
    ? undefined
    : {
        command: 'npm start',
        url: 'http://localhost:4200',
        reuseExistingServer: true,
        timeout: 120_000,
      },
});
