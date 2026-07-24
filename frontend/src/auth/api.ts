import type { ProfileId } from '@/types';
import { API_BASE } from '@/api/http';

const IS_LIVE = import.meta.env.VITE_DATA_SOURCE === 'live';

export interface UserPreferences {
  profile: ProfileId;
  usesWheelchair: boolean;
  usesWalkingAid: boolean;
  visualSupportRequired: boolean;
  hearingSupportRequired: boolean;
  avoidStairsRequired: boolean;
  maxWalkDistanceM?: number;
  trainingConsent: boolean;
}

export interface CurrentUser {
  id: string;
  nickname?: string;
  preference: Partial<UserPreferences>;
}

/** 카카오 로그인은 백엔드 OAuth 콜백을 거쳐 HttpOnly 서비스 세션을 만든다. */
export function startKakaoLogin(): void {
  window.location.assign(`${API_BASE}/api/auth/kakao/login`);
}

/** 게스트에서는 401을 조용히 무시하고, 로그인 사용자만 프로필을 저장한다. */
export async function persistProfile(profile: ProfileId): Promise<void> {
  if (!IS_LIVE) return;
  const response = await fetch(`${API_BASE}/api/me/preferences`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile }),
  });
  if (response.status === 401 || response.status === 503) return;
  if (!response.ok) throw new Error(`profile save failed: ${response.status}`);
}

export async function getCurrentUser(): Promise<CurrentUser | null> {
  if (!IS_LIVE) return null;
  const response = await fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' });
  if (response.status === 204 || response.status === 401 || response.status === 503) return null;
  if (!response.ok) throw new Error(`current user load failed: ${response.status}`);
  return response.json() as Promise<CurrentUser>;
}

export async function savePreferences(preference: Partial<UserPreferences>): Promise<UserPreferences> {
  const response = await fetch(`${API_BASE}/api/me/preferences`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(preference),
  });
  if (!response.ok) throw new Error(`preference save failed: ${response.status}`);
  return response.json() as Promise<UserPreferences>;
}

export async function logout(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/auth/logout`, { method: 'POST', credentials: 'include' });
  if (!response.ok && response.status !== 204) throw new Error(`logout failed: ${response.status}`);
}
