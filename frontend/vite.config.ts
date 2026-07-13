import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import { fileURLToPath } from 'node:url';

// PWA 웹앱 설정. 큰 UI·접근성 중심 서비스이므로 standalone 표시 모드를 사용한다.
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
        // 검증된 공유 앱 데이터셋(data/ai/) — 프론트/백엔드 단일 소스
        '@data': fileURLToPath(new URL('../data/ai', import.meta.url)),
    },
  },
  // data/ 가 프로젝트 루트(frontend/) 밖에 있으므로 dev 서버 접근 허용
  server: { port: 5173, host: true, fs: { allow: ['..'] } },
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'robots.txt'],
      manifest: {
        name: '교통약자 접근성 경로 추천 PWA',
        short_name: '접근성경로',
        description:
          '보행자·대중교통·교통약자를 위한 접근성 중심 경로 추천 PWA (부산진구 데모)',
        theme_color: '#1f6feb',
        background_color: '#ffffff',
        display: 'standalone',
        orientation: 'portrait',
        lang: 'ko',
        start_url: '/',
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
  },
});
