import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import { fileURLToPath } from 'node:url';

// PWA 웹앱 설정. 큰 UI·접근성 중심 서비스이므로 standalone 표시 모드를 사용한다.
export default defineConfig(({ mode }) => {
  const frontendRoot = fileURLToPath(new URL('.', import.meta.url));
  const env = loadEnv(mode, frontendRoot, '');
  const devProxyTarget = (
    env.VITE_DEV_PROXY_TARGET || 'http://localhost:8080'
  ).trim();

  return {
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
          // 검증된 공유 앱 데이터셋(data/ai/) — 프론트/백엔드 단일 소스
          '@data': fileURLToPath(new URL('../data/ai', import.meta.url)),
      },
    },
    // 개발 서버의 /api는 현재 프로덕션형 로컬 스택으로 전달한다.
    // 브라우저에서는 같은 origin 요청이므로 운영 CORS 범위를 넓히지 않는다.
    server: {
      port: 5173,
      host: true,
      fs: { allow: ['..'] },
      proxy: {
        '/api': {
          target: devProxyTarget,
          changeOrigin: true,
        },
      },
    },
    plugins: [
      react(),
      VitePWA({
        registerType: 'autoUpdate',
        includeAssets: ['favicon.svg', 'robots.txt'],
        workbox: {
          navigateFallbackDenylist: [/^\/api\//],
        },
        manifest: {
          id: '/',
          name: '동넷 - 부산 접근성 길찾기',
          short_name: '동넷',
          description:
            '동넷 — 부산 전역 보행자·대중교통 이용자를 위한 접근성 중심 경로 추천 PWA',
          theme_color: '#007a43',
          background_color: '#f3f7f4',
          display: 'standalone',
          display_override: ['window-controls-overlay', 'standalone', 'minimal-ui'],
          lang: 'ko',
          scope: '/',
          start_url: '/',
          categories: ['navigation', 'travel', 'utilities', 'accessibility'],
          shortcuts: [
            {
              name: '경로 찾기',
              short_name: '길찾기',
              description: '출발지와 도착지를 입력해 접근성 경로를 비교합니다.',
              url: '/#main-content',
              icons: [{ src: 'icons/icon-192.png', sizes: '192x192' }],
            },
          ],
          icons: [
            { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
            { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png' },
            {
              src: 'icons/icon-512.png',
              sizes: '512x512',
              type: 'image/png',
              purpose: 'maskable',
            },
          ],
        },
        // 개발 중에는 서비스워커 비활성화(stale 모듈 캐싱 방지). 빌드 시에는 PWA 정상 생성.
        devOptions: { enabled: false },
      }),
    ],
    test: {
      globals: true,
      environment: 'node',
      include: ['src/**/*.test.{ts,tsx}'],
      env: { VITE_DATA_SOURCE: 'mock' },
    },
  };
});
