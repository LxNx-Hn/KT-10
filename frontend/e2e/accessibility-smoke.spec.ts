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

test('모바일 검색 focus ring은 inset이며 네 변이 clipping 밖에 나가지 않는다', async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-mobile-a11y');
  await page.setViewportSize({ width: 393, height: 852 });
  await gotoMapHome(page);
  await page.getByRole('button', { name: '검색 메뉴' }).click();

  for (const name of ['출발지', '도착지'] as const) {
    const input = page.getByRole('combobox', { name });
    await input.focus();
    const metrics = await input.evaluate((el) => {
      const style = getComputedStyle(el);
      let clip: Element | null = el.parentElement;
      while (clip) {
        const overflow = getComputedStyle(clip).overflow;
        if (overflow !== 'visible') break;
        clip = clip.parentElement;
      }
      const er = el.getBoundingClientRect();
      const cr = clip?.getBoundingClientRect();
      return {
        outlineStyle: style.outlineStyle,
        outlineWidth: style.outlineWidth,
        outlineOffset: style.outlineOffset,
        boxShadow: style.boxShadow,
        inputTop: er.top,
        clipTop: cr?.top ?? null,
        ringFitsInsideClip:
          cr != null && er.top >= cr.top - 0.5 && er.bottom <= cr.bottom + 0.5,
      };
    });

    expect(metrics.outlineStyle, `${name} outline`).toBe('none');
    expect(metrics.boxShadow, `${name} inset ring`).toContain('inset');
    expect(metrics.ringFitsInsideClip, `${name} inside clip ancestor`).toBe(
      true,
    );
  }
});

test('desktop mapInfo·voice는 app frame 안에서만 overlay한다', async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop-a11y');
  await page.setViewportSize({ width: 1440, height: 900 });
  await gotoMapHome(page);

  const frame = page.locator('.map-first__frame');
  await expect(frame).toBeVisible();
  const frameBox = await frame.boundingBox();
  expect(frameBox).not.toBeNull();

  const mapInfoFab = page.getByRole('button', { name: '지도 정보' });
  await mapInfoFab.click();
  const panel = page.getByRole('dialog', { name: '지도 정보' });
  await expect(panel).toBeVisible();
  await expect(panel.getByText('도보 경사')).toBeVisible();

  const geometry = await page.evaluate(() => {
    const frameEl = document.querySelector('.map-first__frame');
    const panelEl = document.querySelector('.map-first__map-info-panel');
    const fabEl = document.querySelector(
      '.map-first__map-info > button[aria-label="지도 정보"]',
    );
    const sheetEl = document.querySelector('.map-first__sheet');
    const slope = Array.from(
      panelEl?.querySelectorAll('.map-first__map-info-label') ?? [],
    ).find((node) => node.textContent?.includes('도보 경사'));
    if (!frameEl || !panelEl || !fabEl) {
      return null;
    }
    const frame = frameEl.getBoundingClientRect();
    const panel = panelEl.getBoundingClientRect();
    const fab = fabEl.getBoundingClientRect();
    const sheet = sheetEl?.getBoundingClientRect() ?? null;
    const slopeRect = slope?.getBoundingClientRect() ?? null;
    return {
      frameTop: frame.top,
      frameBottom: frame.bottom,
      frameLeft: frame.left,
      frameRight: frame.right,
      panelTop: panel.top,
      panelBottom: panel.bottom,
      panelLeft: panel.left,
      panelRight: panel.right,
      panelWidth: panel.width,
      fabBottom: fab.bottom,
      sheetTop: sheet?.top ?? null,
      slopeTop: slopeRect?.top ?? null,
      slopeBottom: slopeRect?.bottom ?? null,
    };
  });

  expect(geometry).not.toBeNull();
  expect(geometry!.panelLeft).toBeGreaterThanOrEqual(geometry!.frameLeft - 1);
  expect(geometry!.panelRight).toBeLessThanOrEqual(geometry!.frameRight + 1);
  expect(geometry!.panelTop).toBeGreaterThanOrEqual(geometry!.frameTop - 1);
  expect(geometry!.panelBottom).toBeLessThanOrEqual(geometry!.frameBottom + 1);
  expect(geometry!.panelWidth).toBeGreaterThan(160);
  // FAB bottom 정렬: popover가 FAB보다 아래로 거의 내려가지 않음
  expect(geometry!.panelBottom).toBeLessThanOrEqual(geometry!.fabBottom + 2);
  expect(geometry!.slopeBottom).not.toBeNull();
  expect(geometry!.slopeBottom!).toBeLessThanOrEqual(geometry!.panelBottom + 1);
  if (geometry!.sheetTop != null) {
    expect(geometry!.panelBottom).toBeLessThanOrEqual(geometry!.sheetTop - 8);
  }

  await page.getByRole('button', { name: '음성 챗봇' }).click();
  const dock = page.getByRole('region', { name: '음성 챗봇' });
  await expect(dock).toBeVisible();
  expect(
    await frame.locator('.voicedock.voicedock--map-first').count(),
  ).toBe(1);
  const dockBox = await dock.boundingBox();
  expect(dockBox).not.toBeNull();
  expect(dockBox!.x).toBeGreaterThanOrEqual(frameBox!.x - 1);
  expect(dockBox!.x + dockBox!.width).toBeLessThanOrEqual(
    frameBox!.x + frameBox!.width + 1,
  );
});

test('mobile mapInfo panel은 frame 안 floating card로 한 줄 라벨을 유지한다', async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-mobile-a11y');

  for (const viewport of [
    { width: 353, height: 850 },
    { width: 393, height: 852 },
  ]) {
    await page.setViewportSize(viewport);
    await gotoMapHome(page);
    await page.getByRole('button', { name: '지도 정보' }).click();
    const panel = page.getByRole('dialog', { name: '지도 정보' });
    await expect(panel).toBeVisible();

    const metrics = await page.evaluate(() => {
      const frameEl = document.querySelector('.map-first__frame');
      const panelEl = document.querySelector('.map-first__map-info-panel');
      if (!frameEl || !panelEl) return null;
      const frame = frameEl.getBoundingClientRect();
      const panel = panelEl.getBoundingClientRect();
      const labels = Array.from(
        panelEl.querySelectorAll('.map-first__map-info-label'),
      ).map((el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return {
          text: el.textContent?.trim() ?? '',
          width: rect.width,
          height: rect.height,
          whiteSpace: style.whiteSpace,
        };
      });
      return {
        frameLeft: frame.left,
        frameRight: frame.right,
        panelLeft: panel.left,
        panelRight: panel.right,
        panelWidth: panel.width,
        labels,
      };
    });

    expect(metrics, `${viewport.width}x${viewport.height}`).not.toBeNull();
    expect(metrics!.panelWidth).toBeGreaterThanOrEqual(180);
    expect(metrics!.panelLeft).toBeGreaterThanOrEqual(metrics!.frameLeft - 1);
    expect(metrics!.panelRight).toBeLessThanOrEqual(metrics!.frameRight + 1);
    for (const label of metrics!.labels) {
      expect(label.whiteSpace).toBe('nowrap');
      // 한 글자씩 세로로 쌓이면 높이가 비정상적으로 커진다
      expect(label.height).toBeLessThan(40);
      expect(label.width).toBeGreaterThan(48);
    }
    await expect(panel.getByText('편의시설', { exact: true })).toBeVisible();
    await expect(panel.getByText('건물 그늘', { exact: true })).toBeVisible();
    await expect(panel.getByText('도보 경사', { exact: true })).toBeVisible();
  }
});
