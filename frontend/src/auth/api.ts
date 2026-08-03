import type { ProfileId } from '@/types';
import { API_BASE } from '@/api/http';

const IS_LIVE = import.meta.env.VITE_DATA_SOURCE !== 'mock';

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

/** UI 노출용 인증 구분. 게스트(204/401)와 일시적 확인 불가(503·네트워크)를 분리한다. */
export type ResolvedAuth =
  | { status: 'authenticated'; user: CurrentUser }
  | { status: 'guest' }
  | { status: 'unavailable' };

export async function resolveCurrentAuth(): Promise<ResolvedAuth> {
  // mock/demo·단위 테스트에서는 세션 API가 없으므로 제출 UI를 열어 둔다.
  if (!IS_LIVE) {
    return { status: 'authenticated', user: { id: 'mock-user', preference: {} } };
  }
  try {
    const response = await fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' });
    if (response.status === 200) {
      return { status: 'authenticated', user: await response.json() as CurrentUser };
    }
    if (response.status === 204 || response.status === 401) {
      return { status: 'guest' };
    }
    return { status: 'unavailable' };
  } catch {
    return { status: 'unavailable' };
  }
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
