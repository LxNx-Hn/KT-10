import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Locator, type Page } from '@playwright/test';

async function expectNoAutomaticViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const summary = results.violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    help: violation.help,
    targets: violation.nodes.map((node) => node.target.join(' ')),
  }));

  expect(summary, JSON.stringify(summary, null, 2)).toEqual([]);
}

async function expectTapHeight(
  controlName: string,
  control: Locator,
) {
  await expect(control, `${controlName} 조작부가 보여야 합니다.`).toBeVisible();
  const box = await control.boundingBox();
  expect(box, `${controlName} 조작부의 크기를 측정할 수 있어야 합니다.`).not.toBeNull();
  expect(
    box!.height,
    `${controlName} 조작부 높이는 현재 ${box!.height}px입니다.`,
  ).toBeGreaterThanOrEqual(44);
}

/** 최초 진입은 collapsed 한 줄 검색. 프로필·출발지 등은 expanded 이후에만 존재한다. */
async function expandSearchPanel(page: Page) {
  const collapsed = page.getByRole('button', { name: '어디로 갈까요?' });
  await expect(collapsed).toBeVisible();
  await collapsed.click();
  await expect(page.getByRole('combobox', { name: '출발지' })).toBeVisible();
  await expect(
    page.getByRole('button', { name: /프로필 선택, 현재/ }),
  ).toBeVisible();
}

test('초기 지도 검색 화면에 자동 탐지 가능한 접근성 위반이 없다', async ({ page }) => {
  await page.goto('/');
  await expectNoAutomaticViolations(page);
});

test('프로필과 이동 조건 drawer에 자동 탐지 가능한 접근성 위반이 없다', async ({
  page,
}) => {
  await page.goto('/');
  await expandSearchPanel(page);

  await page.getByRole('button', { name: /프로필 선택, 현재/ }).click();
  const profileDialog = page.getByRole('dialog', { name: '이동 프로필 선택' });
  await expect(profileDialog).toBeVisible();
  await expect(profileDialog.getByRole('radio')).toHaveCount(6);
  await expectNoAutomaticViolations(page);
  await profileDialog
    .getByRole('button', { name: '이동 프로필 선택 닫기' })
    .click();

  await page.getByRole('button', { name: /^조건/ }).click();
  const conditionsDialog = page.getByRole('dialog', { name: '이번 이동 조건' });
  await expect(conditionsDialog).toBeVisible();
  await expect(
    conditionsDialog.getByRole('button', { name: /유아차 이용/ }),
  ).toBeVisible();
  await expect(
    conditionsDialog.getByRole('button', { name: /건물 그늘 우선/ }),
  ).toBeVisible();
  await expectNoAutomaticViolations(page);
});

test('모바일 핵심 조작부의 높이가 44px 이상이다', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-mobile-a11y');
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto('/');
  await expandSearchPanel(page);

  const initialControls: Array<[string, Locator]> = [
    ['출발지', page.getByRole('combobox', { name: '출발지' })],
    ['도착지', page.getByRole('combobox', { name: '도착지' })],
    ['경로 찾기', page.getByRole('button', { name: '경로 찾기' })],
    ['프로필 선택', page.getByRole('button', { name: /프로필 선택, 현재/ })],
    ['짐 많음', page.getByRole('button', { name: '짐 많음' })],
    ['계단 회피', page.getByRole('button', { name: '계단 회피' })],
    ['쉬운 화면', page.getByRole('button', { name: '쉬운 화면' })],
    ['조건', page.getByRole('button', { name: /^조건/ })],
    [
      '현재 위치',
      page.getByRole('button', { name: '현재 위치를 출발지로 사용' }),
    ],
    ['지도 정보', page.getByRole('button', { name: '지도 정보' })],
    ['음성 챗봇', page.getByRole('button', { name: '음성 챗봇' })],
  ];

  for (const [name, control] of initialControls) {
    await expectTapHeight(name, control);
  }

  // 상황 칩·조건은 동일 context-bar에 있다. 320px에서는 칩이 2열로 줄바꿈될 수 있다.
  const contextBar = page.locator('.map-first__context-bar');
  await expect(contextBar.getByRole('button', { name: '짐 많음' })).toBeVisible();
  await expect(contextBar.getByRole('button', { name: '계단 회피' })).toBeVisible();
  await expect(contextBar.getByRole('button', { name: '쉬운 화면' })).toBeVisible();
  await expect(contextBar.getByRole('button', { name: /^조건/ })).toBeVisible();

  await page.getByRole('button', { name: /^조건/ }).click();
  const conditionsDialog = page.getByRole('dialog', { name: '이번 이동 조건' });
  await expectTapHeight(
    '유아차 이용',
    conditionsDialog.getByRole('button', { name: /유아차 이용/ }),
  );
  await expectTapHeight(
    '이동 조건 drawer 닫기',
    conditionsDialog.getByRole('button', { name: '이번 이동 조건 닫기' }),
  );
});
