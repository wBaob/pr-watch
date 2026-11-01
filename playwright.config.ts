import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:8877', browserName: 'chromium', channel: process.env.PW_CHANNEL || undefined },
  webServer: { command: 'python -m inbox.server --demo --port 8877 --db output/browser.sqlite3', url: 'http://127.0.0.1:8877', reuseExistingServer: false },
});
