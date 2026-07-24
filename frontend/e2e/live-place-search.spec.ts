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
  await expect(page.getByText('API 연결 모드', { exact: true })).toBeVisible();
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

  expect(consoleProblems, consoleProblems.join('\n')).toEqual([]);
});
