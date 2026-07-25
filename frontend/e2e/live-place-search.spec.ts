import { expect, test } from '@playwright/test';

test('Kakao Places에서 북구청과 부산역을 실제 검색·선택한다', async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => {
    consoleProblems.push(`pageerror: ${error.message}`);
  });

  await page.goto('/');
  await expect(page.getByText('API 연결 모드', { exact: true })).toHaveCount(0);
  await expect(page.getByText('검증용 내장 데이터', { exact: true })).toHaveCount(0);

  const origin = page.getByRole('combobox', { name: '출발지' });
  await origin.fill('북구청');
  const bukgu = page.getByRole('option', { name: /부산.*북구청/ }).first();
  await expect(bukgu).toBeVisible();
  await bukgu.click();
  await expect(origin).toHaveValue(/북구청/);

  const destination = page.getByRole('combobox', { name: '도착지' });
  await destination.fill('부산역');
  const busanStation = page.getByRole('option', { name: /부산역/ }).first();
  await expect(busanStation).toBeVisible();
  await busanStation.click();
  await expect(destination).toHaveValue(/부산역/);

  await page.getByRole('button', { name: '경로 찾기' }).click();
  await expect(page.getByRole('heading', { name: '추천 경로 3개' })).toBeVisible({
    timeout: 20_000,
  });
  const routeCards = page
    .getByRole('list', { name: '점수순 경로 카드' })
    .locator(':scope > [role="listitem"]');
  await expect(routeCards).toHaveCount(3);
  await expect(routeCards.first()).toContainText(
    '프로필 적합 점수',
  );

  const floatingControls = page.locator(
    '.map-first__fab:visible, .map-first__voice:visible, .map-first__map-legend:visible',
  );
  const controlCount = await floatingControls.count();
  const boxes = await Promise.all(
    Array.from({ length: controlCount }, (_, index) =>
      floatingControls.nth(index).boundingBox(),
    ),
  );
  for (let left = 0; left < boxes.length; left += 1) {
    for (let right = left + 1; right < boxes.length; right += 1) {
      const a = boxes[left];
      const b = boxes[right];
      if (!a || !b) continue;
      const overlaps = !(
        a.x + a.width <= b.x ||
        b.x + b.width <= a.x ||
        a.y + a.height <= b.y ||
        b.y + b.height <= a.y
      );
      expect(
        overlaps,
        `지도 조작부 ${left + 1}번과 ${right + 1}번이 겹치면 안 됩니다.`,
      ).toBe(false);
    }
  }

  expect(consoleProblems, consoleProblems.join('\n')).toEqual([]);
});
