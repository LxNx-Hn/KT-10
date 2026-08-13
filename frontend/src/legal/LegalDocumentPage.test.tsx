// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import LegalDocumentPage from './LegalDocumentPage';
import { PRIVACY_DOCUMENT, TERMS_DOCUMENT } from './legalDocuments';

afterEach(() => {
  cleanup();
});

describe('LegalDocumentPage', () => {
  it('이용약관 문서에 main·h1·section 구조와 홈 링크를 제공한다', () => {
    render(<LegalDocumentPage documentId="terms" />);

    expect(screen.getByRole('main')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 1, name: '이용약관' })).toBeTruthy();
    expect(
      screen.getByRole('heading', { level: 2, name: TERMS_DOCUMENT.sections[0].heading }),
    ).toBeTruthy();
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: TERMS_DOCUMENT.sections[TERMS_DOCUMENT.sections.length - 1].heading,
      }),
    ).toBeTruthy();
    const homeLinks = screen.getAllByRole('link', { name: '동넷으로 돌아가기' });
    expect(homeLinks.length).toBeGreaterThanOrEqual(1);
    expect(homeLinks[0].getAttribute('href')).toBe('/');
    expect(screen.getByText(/즉시 삭제/)).toBeTruthy();
    expect(
      screen.getByText(/탈퇴 후 다시 가입하는 경우 새로운 계정으로 처리됩니다/),
    ).toBeTruthy();
    expect(screen.queryByText(/30일 이내/)).toBeNull();
    expect(screen.queryByText(/재로그인.*철회/)).toBeNull();
    expect(screen.queryByText('TODO')).toBeNull();
    expect(screen.queryByText('미정')).toBeNull();
  });

  it('개인정보처리방침에 코드 기반 수집·위치·외부연동·탈퇴 설명을 포함한다', () => {
    render(<LegalDocumentPage documentId="privacy" />);

    expect(screen.getByRole('heading', { level: 1, name: '개인정보처리방침' })).toBeTruthy();
    expect(
      screen.getByRole('heading', { level: 2, name: '1. 개인정보 처리 목적' }),
    ).toBeTruthy();
    expect(
      screen.getByRole('heading', { level: 2, name: PRIVACY_DOCUMENT.sections[0].heading }),
    ).toBeTruthy();
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: PRIVACY_DOCUMENT.sections[PRIVACY_DOCUMENT.sections.length - 1].heading,
      }),
    ).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: '7. 경로 후기 및 피드백' })).toBeTruthy();
    expect(
      screen.getByRole('heading', { level: 2, name: '13. 개인정보 파기 절차 및 방법' }),
    ).toBeTruthy();
    expect(
      screen.getByRole('heading', { level: 2, name: '14. 개인정보 보호조치' }),
    ).toBeTruthy();
    expect(screen.getByText(/카카오 회원 식별값/)).toBeTruthy();
    expect(screen.getByText(/이메일·프로필 사진을 서비스 데이터베이스에 저장하지 않습니다/)).toBeTruthy();
    expect(screen.getByText(/navigator.geolocation/)).toBeTruthy();
    expect(screen.getByText(/신고 당시 브라우저에서 확인된 현재 위치/)).toBeTruthy();
    expect(
      screen.getByText(/이용자별 이동 이력으로 별도 영구 저장하지 않습니다/),
    ).toBeTruthy();
    expect(screen.getByText(/Kakao OAuth/)).toBeTruthy();
    expect(screen.getByText(/OpenRouteService/)).toBeTruthy();
    expect(
      screen.getByText(
        /다음 외부 서비스의 API와 연동할 수 있으며/,
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/제3자 제공/)).toBeNull();
    expect(screen.queryByText(/처리위탁/)).toBeNull();
    expect(screen.queryByText(/국외 이전/)).toBeNull();
    expect(screen.getByText(/시설 관리에 필요한 정보가 남을 수 있습니다/)).toBeTruthy();
    expect(screen.getByText(/이 값은 개인정보를 포함하지 않습니다/)).toBeTruthy();
    expect(
      screen.queryByText(/이동지원 세부 설정 저장 UI를 제공한다고 단정하지 않습니다/),
    ).toBeNull();
    expect(screen.queryByText(/경로 후기 및 인상/)).toBeNull();
    expect(screen.queryByText(/example@/i)).toBeNull();
    expect(PRIVACY_DOCUMENT.path).toBe('/privacy');
  });
});
