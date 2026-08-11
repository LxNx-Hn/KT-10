// @vitest-environment jsdom

import { cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PROFILE_LIST, PROFILES } from '@/config/profiles';
import ProfileOptionCard from './ProfileOptionCard';

afterEach(() => {
  cleanup();
});

describe('MOB-16 모바일 프로필 선택 카드', () => {
  it.each(PROFILE_LIST)('$label 프로필에 아이콘과 핵심 키워드 chip을 표시한다', (item) => {
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
    expect(option?.textContent).toContain(item.label);
    expect(
      option?.querySelector(`svg[data-profile-icon="${item.id}"]`),
    ).toBeTruthy();
    expect(item.keywords.length).toBeGreaterThanOrEqual(2);
    for (const keyword of item.keywords.slice(0, 2)) {
      expect(option?.textContent).toContain(keyword);
    }
    expect(option?.getAttribute('aria-label')).toContain(item.description);
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

  it('모바일 키워드 chip은 nowrap/ellipsis로 잘리지 않도록 CSS가 허용한다', async () => {
    // @ts-expect-error node built-in
    const { readFileSync } = await import('node:fs');
    // @ts-expect-error node built-in
    const { resolve } = await import('node:path');
    const cwd = (globalThis as { process?: { cwd?: () => string } }).process
      ?.cwd?.();
    expect(cwd).toBeTruthy();
    const css = readFileSync(
      resolve(cwd!, 'src/v2/map-first.css'),
      'utf8',
    ) as string;
    const blockStart = css.indexOf('.map-first__profile-keyword {');
    expect(blockStart).toBeGreaterThan(-1);
    const block = css.slice(blockStart, blockStart + 450);
    expect(block).toContain('white-space: normal');
    expect(block).toContain('overflow: visible');
    expect(block).not.toContain('text-overflow: ellipsis');
    expect(block).not.toContain('white-space: nowrap');
  });
});
