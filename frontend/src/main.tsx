import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './index.css';

/**
 * 동일 origin에서 docker production PWA → vite dev로 전환하면
 * 이전 service worker가 구번들을 계속 제공할 수 있다.
 * 개발 모드에서는 등록된 SW와 Cache Storage를 비워 최신 모듈을 받게 한다.
 */
async function clearDevServiceWorkers(): Promise<void> {
  if (!import.meta.env.DEV || !('serviceWorker' in navigator)) return;
  try {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.map((registration) => registration.unregister()));
    if ('caches' in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));
    }
  } catch {
    // SW 정리는 best-effort. 실패해도 앱 부팅은 계속한다.
  }
}

void clearDevServiceWorkers().finally(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
