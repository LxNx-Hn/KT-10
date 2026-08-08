import { defineConfig } from '@playwright/test';

const PORT = 5194;

export default defineConfig({
  testDir: './e2e',
  testMatch: 'empty-sheet-drag-height.spec.ts',
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  timeout: 60_000,
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      VITE_DATA_SOURCE: 'mock',
      VITE_API_BASE: '',
      VITE_KAKAO_MAP_KEY: '',
    },
  },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    locale: 'ko-KR',
    colorScheme: 'light',
    channel: 'chrome',
    headless: true,
    viewport: { width: 320, height: 568 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chrome-empty-drag', use: {} }],
});
