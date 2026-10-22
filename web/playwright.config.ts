import { defineConfig } from '@playwright/test'

const port = Number(process.env.HYPERKNOW_WEB_PORT ?? '5173')
const baseURL = `http://127.0.0.1:${port}`

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['json', { outputFile: '.verification/browser-report.json' }]],
  use: {
    baseURL,
    browserName: 'chromium',
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: `npm run dev -- --port ${port}`,
    url: baseURL,
    reuseExistingServer: true,
    timeout: 30_000,
  },
})
