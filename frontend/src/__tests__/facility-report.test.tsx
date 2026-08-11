// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { resolveCurrentAuth } from '@/auth/api';
import FacilityReport from '@/components/FacilityReport';

vi.mock('@/auth/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/auth/api')>();
  return {
    ...actual,
    resolveCurrentAuth: vi.fn(),
    startKakaoLogin: vi.fn(),
  };
});

const resolveCurrentAuthMock = vi.mocked(resolveCurrentAuth);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

beforeEach(() => {
  resolveCurrentAuthMock.mockResolvedValue({
    status: 'authenticated',
    user: { id: 'mock-user', isAdmin: false, preference: {} },
  });
});

describe('시설물 신고', () => {
  it('로그인 상태에서는 신고 폼과 접수 버튼이 표시된다', async () => {
    render(<FacilityReport />);
    expect(await screen.findByRole('button', { name: '신고 접수' })).toBeTruthy();
    expect(screen.getByLabelText('시설물 이름')).toBeTruthy();
  });

  it('비로그인에서는 활성 신고 접수 버튼이 없고 제출되지 않는다', async () => {
    resolveCurrentAuthMock.mockResolvedValue({ status: 'guest' });
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    render(<FacilityReport />);
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '신고 접수' })).toBeNull();
    });
    expect(screen.getByRole('button', { name: '카카오 로그인' })).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('로그인 후 기존 제출 계약을 유지한다', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 201,
      ok: true,
      json: async () => ({ id: 'report-1', status: 'pending' }),
    } as Response);
    vi.stubGlobal('fetch', fetchMock);

    render(<FacilityReport />);
    fireEvent.change(await screen.findByLabelText('시설물 이름'), {
      target: { value: '서면역 승강기' },
    });
    fireEvent.click(screen.getByRole('button', { name: '신고 접수' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(String(url)).toContain('/api/facility-reports');
    expect(JSON.parse(String(init.body))).toMatchObject({
      facilityName: '서면역 승강기',
      facilityType: '승강기',
      issueType: 'relocated',
    });
  });
});
