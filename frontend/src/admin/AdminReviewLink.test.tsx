// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { resolveCurrentAuth } from '@/auth/api';
import AdminReviewLink from './AdminReviewLink';

vi.mock('@/auth/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/auth/api')>();
  return { ...actual, resolveCurrentAuth: vi.fn() };
});

const resolveAuthMock = vi.mocked(resolveCurrentAuth);

afterEach(() => {
  cleanup();
  resolveAuthMock.mockReset();
});

describe('관리자 리뷰 진입 링크', () => {
  it('관리자에게만 설정 화면 진입 링크를 표시한다', async () => {
    resolveAuthMock.mockResolvedValueOnce({
      status: 'authenticated',
      user: { id: 'member', isAdmin: false, preference: {} },
    });
    const memberView = render(<AdminReviewLink />);
    await Promise.resolve();
    expect(screen.queryByRole('link', { name: '사용자 리뷰 검토' })).toBeNull();
    memberView.unmount();

    resolveAuthMock.mockResolvedValueOnce({
      status: 'authenticated',
      user: { id: 'admin', isAdmin: true, preference: {} },
    });
    render(<AdminReviewLink />);
    const link = await screen.findByRole('link', { name: '사용자 리뷰 검토' });
    expect(link.getAttribute('href')).toBe('/admin/reviews');
  });
});
