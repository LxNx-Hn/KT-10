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

test('초기 지도 검색 화면에 자동 탐지 가능한 접근성 위반이 없다', async ({ page }) => {
  await page.goto('/');
  await expectNoAutomaticViolations(page);
});

test('프로필과 이동 조건 drawer에 자동 탐지 가능한 접근성 위반이 없다', async ({
  page,
}) => {
  await page.goto('/');

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
    conditionsDialog.getByRole('textbox', { name: '건물 그늘 계산 시각' }),
  ).toBeVisible();
  await expectNoAutomaticViolations(page);
});

test('모바일 핵심 조작부의 높이가 44px 이상이다', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-mobile-a11y');
  await page.goto('/');

  const initialControls: Array<[string, Locator]> = [
    ['출발지', page.getByRole('combobox', { name: '출발지' })],
    ['도착지', page.getByRole('combobox', { name: '도착지' })],
    ['경로 찾기', page.getByRole('button', { name: '경로 찾기' })],
    ['큰 글씨', page.getByRole('button', { name: '큰 글씨' })],
    ['카카오 로그인', page.getByRole('button', { name: '카카오 로그인' })],
    ['프로필 선택', page.getByRole('button', { name: /프로필 선택, 현재/ })],
    ['조건', page.getByRole('button', { name: /^조건/ })],
    [
      '현재 위치',
      page.getByRole('button', { name: '현재 위치를 출발지로 사용' }),
    ],
    ['지도와 데이터 설명', page.getByRole('button', { name: '지도와 데이터 설명' })],
    ['음성 챗봇', page.getByRole('button', { name: '음성 챗봇' })],
  ];

  for (const [name, control] of initialControls) {
    await expectTapHeight(name, control);
  }

  await page.getByRole('button', { name: /^조건/ }).click();
  const conditionsDialog = page.getByRole('dialog', { name: '이번 이동 조건' });
  await expectTapHeight(
    '건물 그늘 계산 시각',
    conditionsDialog.getByRole('textbox', { name: '건물 그늘 계산 시각' }),
  );
  await expectTapHeight(
    '그늘 계산 시각 지금',
    conditionsDialog.getByRole('button', { name: '지금', exact: true }),
  );
  await expectTapHeight(
    '이동 조건 drawer 닫기',
    conditionsDialog.getByRole('button', { name: '이번 이동 조건 닫기' }),
  );
});
