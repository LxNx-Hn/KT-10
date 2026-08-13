import type { ProfileId } from '@/types';
import { API_BASE, ApiError } from '@/api/http';

const IS_LIVE = import.meta.env.VITE_DATA_SOURCE !== 'mock';

/** 탈퇴·세션 만료 등으로 클라이언트 인증 UI를 게스트로 맞출 때 사용한다. */
export const AUTH_SESSION_ENDED_EVENT = 'dongnet:auth-session-ended';

export function notifyAuthSessionEnded(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(AUTH_SESSION_ENDED_EVENT));
  }
}

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
  isAdmin: boolean;
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
    return {
      status: 'authenticated',
      user: { id: 'mock-user', isAdmin: false, preference: {} },
    };
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

/** 회원 탈퇴. 204 성공, 401·409는 ApiError status로 구분한다. */
export async function withdraw(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/auth/withdraw`, {
    method: 'POST',
    credentials: 'include',
  });
  if (response.status === 204) return;
  throw new ApiError('withdraw failed', response.status);
}

/** 이용약관 수락으로 가입을 완료한다. documentVersion·kakaoId는 보내지 않는다. */
export async function completeSignup(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/auth/signup/complete`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ acceptTerms: true }),
  });
  if (response.status === 204) return;
  throw new ApiError('signup complete failed', response.status);
}

/** 가입 대기 쿠키만 지운다. 계정은 만들지 않는다. */
export async function cancelSignup(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/auth/signup/cancel`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!response.ok && response.status !== 204) {
    throw new ApiError('signup cancel failed', response.status);
  }
}

/** 가입 대기 쿠키 확인. 만료(204)와 네트워크·서버 오류를 구분한다. */
export type ResolvedSignupStatus =
  | { status: 'pending' }
  | { status: 'absent' }
  | { status: 'unavailable' };

export async function resolveSignupStatus(): Promise<ResolvedSignupStatus> {
  if (!IS_LIVE) return { status: 'pending' };
  try {
    const response = await fetch(`${API_BASE}/api/auth/signup/status`, {
      credentials: 'include',
    });
    if (response.status === 200) {
      const body = await response.json() as { pending?: boolean };
      return body.pending === true ? { status: 'pending' } : { status: 'absent' };
    }
    if (response.status === 204) {
      return { status: 'absent' };
    }
    return { status: 'unavailable' };
  } catch {
    return { status: 'unavailable' };
  }
}

/** 계정 삭제 본인 확인용 Kakao OAuth. 일반 로그인과 분리한다. */
export function startAccountDeletionVerification(): void {
  window.location.assign(`${API_BASE}/api/auth/deletion/kakao/login`);
}

export type ResolvedDeletionStatus =
  | { status: 'verified' }
  | { status: 'absent' }
  | { status: 'unavailable' };

export async function resolveAccountDeletionStatus(): Promise<ResolvedDeletionStatus> {
  if (!IS_LIVE) return { status: 'absent' };
  try {
    const response = await fetch(`${API_BASE}/api/auth/deletion/status`, {
      credentials: 'include',
    });
    if (response.status === 200) {
      const body = await response.json() as { verified?: boolean };
      return body.verified === true ? { status: 'verified' } : { status: 'absent' };
    }
    if (response.status === 204) {
      return { status: 'absent' };
    }
    return { status: 'unavailable' };
  } catch {
    return { status: 'unavailable' };
  }
}

/** 공개 삭제 페이지용. mock/e2e는 게스트로 두고 인앱 mock 인증과 섞지 않는다. */
export async function resolveDeletionPageAuth(): Promise<ResolvedAuth> {
  if (!IS_LIVE) return { status: 'guest' };
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

export async function confirmExternalAccountDeletion(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/auth/deletion/confirm`, {
    method: 'POST',
    credentials: 'include',
  });
  if (response.status === 204) return;
  throw new ApiError('account deletion failed', response.status);
}

export async function cancelExternalAccountDeletion(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/auth/deletion/cancel`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!response.ok && response.status !== 204) {
    throw new ApiError('account deletion cancel failed', response.status);
  }
}
