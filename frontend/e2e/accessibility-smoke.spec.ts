import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

test('초기 검색 화면에 자동 탐지 가능한 접근성 위반이 없다', async ({ page }) => {
  await page.goto('/');

  const results = await new AxeBuilder({ page }).analyze();
  const summary = results.violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    help: violation.help,
    targets: violation.nodes.map((node) => node.target.join(' ')),
  }));

  expect(summary, JSON.stringify(summary, null, 2)).toEqual([]);
});

test('모바일 핵심 조작부의 높이가 44px 이상이다', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-mobile-a11y');
  await page.goto('/');

  const controls = [
    page.getByRole('button', { name: '큰 글씨' }),
    page.getByRole('button', { name: '카카오 로그인' }),
    page.getByRole('textbox', { name: '건물 그늘 계산 시각' }),
    page.getByRole('button', { name: '지금' }),
    page.getByRole('button', { name: /음성 챗봇/ }),
  ];

  for (const control of controls) {
    await expect(control).toBeVisible();
    const box = await control.boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(44);
  }
});
