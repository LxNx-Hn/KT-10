// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resolveCurrentAuth } from '@/auth/api';
import AdminReviewsPage from './AdminReviewsPage';

vi.mock('@/auth/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/auth/api')>();
  return { ...actual, resolveCurrentAuth: vi.fn(), startKakaoLogin: vi.fn() };
});

const resolveAuthMock = vi.mocked(resolveCurrentAuth);
const listItem = {
  id: 'review-1',
  routeId: 'route-1',
  rating: 2,
  wasUsable: false,
  issueType: 'slope',
  informationAccurate: false,
  trainingConsent: false,
  moderationStatus: 'pending' as const,
  resolutionNote: null,
  reviewedAt: null,
  createdAt: '2026-08-11T01:00:00',
  rank: 2,
  profile: 'disabled',
  modelVersion: 'rules-live-v1',
};
const detail = {
  ...listItem,
  stairsDifficulty: null,
  slopeDifficulty: 5,
  transferDifficulty: null,
  crowdingDifficulty: null,
  transferInformationDifficulty: null,
  accessibilityFacilityDifficulty: null,
  actualDurationMin: 31,
  wouldReuse: false,
  comment: '표시보다 경사가 가팔랐습니다.',
  featureSnapshot: { avg_slope_percent: 4.2, stairs_count: null },
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

beforeEach(() => {
  resolveAuthMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('관리자 리뷰 검토 화면', () => {
  it('일반 사용자는 목록을 요청하지 않고 접근을 차단한다', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    resolveAuthMock.mockResolvedValue({
      status: 'authenticated',
      user: { id: 'member', isAdmin: false, preference: {} },
    });

    render(<AdminReviewsPage />);

    expect(await screen.findByText('접근 권한이 없습니다')).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('관리자는 목록·상세 스냅샷을 보고 검토 결과를 저장한다', async () => {
    resolveAuthMock.mockResolvedValue({
      status: 'authenticated',
      user: { id: 'admin', isAdmin: true, preference: {} },
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'PATCH') {
        expect(JSON.parse(String(init.body))).toEqual({
          status: 'verified',
          resolutionNote: '현장 사진과 대조했습니다.',
        });
        return jsonResponse({
          ...detail,
          moderationStatus: 'verified',
          resolutionNote: '현장 사진과 대조했습니다.',
          reviewedAt: '2026-08-11T02:00:00',
        });
      }
      if (url.endsWith('/api/admin/route-reviews/review-1')) {
        return jsonResponse(detail);
      }
      return jsonResponse({ items: [listItem], total: 1, limit: 25, offset: 0 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<AdminReviewsPage />);
    const issueLabel = await screen.findByText('경사', { selector: 'strong' });
    fireEvent.click(issueLabel.closest('button')!);

    expect(await screen.findByText('표시보다 경사가 가팔랐습니다.')).toBeTruthy();
    fireEvent.click(screen.getByText('서버 경로 계산 스냅샷 원문 보기'));
    expect(screen.getByText(/avg_slope_percent/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('검토 근거·조치 내용'), {
      target: { value: '현장 사진과 대조했습니다.' },
    });
    fireEvent.click(screen.getByRole('button', { name: '검토 결과 저장' }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(true);
    });
    expect(await screen.findByDisplayValue('현장 사진과 대조했습니다.')).toBeTruthy();
  });
});
