import type { ProfileId } from '@/types';

const BASE = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '');

/** 카카오 로그인은 백엔드 OAuth 콜백을 거쳐 HttpOnly 서비스 세션을 만든다. */
export function startKakaoLogin(): void {
  window.location.assign(`${BASE}/api/auth/kakao/login`);
}

/** 게스트에서는 401을 조용히 무시하고, 로그인 사용자만 프로필을 저장한다. */
export async function persistProfile(profile: ProfileId): Promise<void> {
  const response = await fetch(`${BASE}/api/me/preferences`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile }),
  });
  if (response.status === 401 || response.status === 503) return;
  if (!response.ok) throw new Error(`profile save failed: ${response.status}`);
}
