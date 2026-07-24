import { defineConfig, devices } from '@playwright/test';

const PORT = 4174;

export default defineConfig({
  testDir: './e2e',
  testMatch: 'accessibility-smoke.spec.ts',
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  timeout: 30_000,
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
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium-mobile-a11y',
      use: { ...devices['Pixel 7'] },
    },
    {
      name: 'chromium-desktop-a11y',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
