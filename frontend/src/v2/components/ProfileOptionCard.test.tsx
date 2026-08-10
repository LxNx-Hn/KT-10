// @vitest-environment jsdom

import { cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PROFILE_LIST, PROFILES } from '@/config/profiles';
import type { ProfileId } from '@/types';
import ProfileOptionCard from './ProfileOptionCard';

afterEach(() => {
  cleanup();
});

const MOBILE_LABEL: Record<ProfileId, string> = {
  general: '일반',
  elderly: '고령자',
  child: '아동',
  youth: '청소년',
  disabled: '장애인',
  pregnant: '임산부',
};

const MOBILE_DESCRIPTION: Record<ProfileId, string> = {
  general: '빠르기·편의·날씨를 균형 있게 봐요.',
  elderly: '계단을 피하고 짧은 도보를 우선해요.',
  child: '안전한 횡단과 단순한 환승을 우선해요.',
  youth: '빠르고 단순한 이동을 우선해요.',
  disabled: '승강기·저상버스·계단 회피를 우선해요.',
  pregnant: '긴 도보·급경사·복잡한 환승을 줄여요.',
};

describe('MOB-16 모바일 프로필 선택 카드', () => {
  it.each(PROFILE_LIST)('$label 프로필에 구분 가능한 아이콘과 짧은 설명을 표시한다', (item) => {
    const { container } = render(
      <ProfileOptionCard
        item={item}
        selected={false}
        mobile
        onSelect={() => undefined}
      />,
    );

    const option = container.querySelector(
      `[data-profile-option="${item.id}"]`,
    );
    expect(option).toBeTruthy();
    expect(option?.textContent).toContain(MOBILE_LABEL[item.id]);
    expect(
      option?.querySelector(`svg[data-profile-icon="${item.id}"]`),
    ).toBeTruthy();
    expect(option?.textContent).toContain(MOBILE_DESCRIPTION[item.id]);
  });

  it('선택 상태를 aria, 색상용 class, 체크 아이콘으로 함께 표시한다', () => {
    const { container, getByRole } = render(
      <ProfileOptionCard
        item={PROFILES.general}
        selected
        mobile
        onSelect={() => undefined}
      />,
    );

    const option = getByRole('radio', { name: /일반/ });
    expect(option.getAttribute('aria-checked')).toBe('true');
    expect(option.classList.contains('map-first__profile-option--selected')).toBe(true);
    expect(container.querySelector('.map-first__profile-option-check svg')).toBeTruthy();
  });

  it('카드를 누르면 해당 내부 profile id를 전달한다', () => {
    const onSelect = vi.fn();
    const { getByRole } = render(
      <ProfileOptionCard
        item={PROFILES.youth}
        selected={false}
        mobile
        onSelect={onSelect}
      />,
    );

    fireEvent.click(getByRole('radio', { name: /청소년/ }));
    expect(onSelect).toHaveBeenCalledWith('youth');
  });

  it('데스크톱에서는 기존 문구와 DOM을 유지한다', () => {
    const { container, getByRole } = render(
      <ProfileOptionCard
        item={PROFILES.youth}
        selected={false}
        mobile={false}
        onSelect={() => undefined}
      />,
    );

    const option = getByRole('radio', { name: /청소년/ });
    expect(option.textContent).toContain(PROFILES.youth.description);
    expect(container.querySelector('[data-profile-icon]')).toBeNull();
    expect(container.querySelector('.map-first__profile-option-check')).toBeNull();
  });
});
