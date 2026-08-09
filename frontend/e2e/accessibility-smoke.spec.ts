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

function usesMobileHome(page: Page): boolean {
  return (page.viewportSize()?.width ?? Number.POSITIVE_INFINITY) <= 479;
}

const MOBILE_STARTUP_STORAGE_KEY = 'dongnet.startup.seen.v1';

async function gotoMapHome(page: Page) {
  await page.addInitScript(
    (storageKey) => window.localStorage.setItem(storageKey, '1'),
    MOBILE_STARTUP_STORAGE_KEY,
  );
  await page.goto('/');
}

/** 최초 진입은 collapsed 한 줄 검색. 출발지·도착지는 expanded 이후에만 존재한다. */
async function expandSearchPanel(page: Page) {
  const collapsed = page.getByRole('button', { name: '어디로 갈까요?' });
  await expect(collapsed).toBeVisible();
  await collapsed.click();
  await expect(page.getByRole('combobox', { name: '출발지' })).toBeVisible();
}

test('첫 방문 시작 화면에 자동 탐지 가능한 접근성 위반이 없다', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: '로그인 없이 시작하기' })).toBeVisible();
  await expectNoAutomaticViolations(page);
});

test('초기 지도 검색 화면에 자동 탐지 가능한 접근성 위반이 없다', async ({ page }) => {
  await gotoMapHome(page);
  await expectNoAutomaticViolations(page);
});

test('프로필과 이동 조건 drawer에 자동 탐지 가능한 접근성 위반이 없다', async ({
  page,
}) => {
  await gotoMapHome(page);

  if (usesMobileHome(page)) {
    await page.getByRole('button', { name: '내 설정 메뉴' }).click();
    const settingsDialog = page.getByRole('dialog', { name: '내 설정' });
    await expect(settingsDialog).toBeVisible();
    await expect(settingsDialog.getByRole('radio')).toHaveCount(6);
    await expect(
      settingsDialog.getByRole('button', { name: '짐 많음' }),
    ).toBeVisible();
    await expect(
      settingsDialog.getByRole('button', { name: /유아차 이용/ }),
    ).toBeVisible();
    await expect(
      settingsDialog.getByRole('button', { name: /건물 그늘 우선/ }),
    ).toBeVisible();
    await expectNoAutomaticViolations(page);
    return;
  }

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
  await gotoMapHome(page);

  const mapHomeControls: Array<[string, Locator]> = [
    ['검색 시작', page.getByRole('button', { name: '어디로 갈까요?' })],
    ['현재 프로필', page.getByRole('button', { name: /현재 프로필/ })],
    ['현재 이동 조건', page.getByRole('button', { name: /현재 이동 조건/ })],
    [
      '현재 위치',
      page.getByRole('button', { name: '현재 위치를 출발지로 사용' }),
    ],
    ['지도 정보', page.getByRole('button', { name: '지도 정보' })],
    ['음성 챗봇', page.getByRole('button', { name: '음성 챗봇' })],
    ['지도 홈 메뉴', page.getByRole('button', { name: '지도 홈 메뉴' })],
    ['검색 메뉴', page.getByRole('button', { name: '검색 메뉴' })],
    ['내 설정 메뉴', page.getByRole('button', { name: '내 설정 메뉴' })],
  ];

  for (const [name, control] of mapHomeControls) {
    await expectTapHeight(name, control);
  }

  await page.getByRole('button', { name: '검색 메뉴' }).click();
  await expect(page.getByRole('combobox', { name: '출발지' })).toBeVisible();
  const searchControls: Array<[string, Locator]> = [
    ['검색창 접기', page.getByRole('button', { name: '검색창 접기' })],
    ['출발지', page.getByRole('combobox', { name: '출발지' })],
    ['도착지', page.getByRole('combobox', { name: '도착지' })],
    [
      '출발지와 도착지 바꾸기',
      page.getByRole('button', { name: '출발지와 도착지 바꾸기' }),
    ],
    ['경로 찾기', page.getByRole('button', { name: '경로 찾기' })],
  ];

  for (const [name, control] of searchControls) {
    await expectTapHeight(name, control);
  }

  await page.getByRole('button', { name: '검색창 접기' }).click();
  await page.getByRole('button', { name: '내 설정 메뉴' }).click();
  const settingsDialog = page.getByRole('dialog', { name: '내 설정' });
  await expect(settingsDialog).toBeVisible();
  await expectTapHeight(
    '프로필 선택',
    settingsDialog.getByRole('radio').first(),
  );
  await expectTapHeight(
    '짐 많음',
    settingsDialog.getByRole('button', { name: '짐 많음' }),
  );
  await expectTapHeight(
    '계단 회피',
    settingsDialog.getByRole('button', { name: '계단 회피' }),
  );
  await expectTapHeight(
    '유아차 이용',
    settingsDialog.getByRole('button', { name: /유아차 이용/ }),
  );
  await expectTapHeight(
    '내 설정 drawer 닫기',
    settingsDialog.getByRole('button', { name: '내 설정 닫기' }),
  );
});
