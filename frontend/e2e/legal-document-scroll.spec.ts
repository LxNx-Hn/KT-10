import { expect, test, type Locator, type Page } from '@playwright/test';

async function readScrollMetrics(page: Page) {
  return page.evaluate(() => {
    const scrolling = document.scrollingElement;
    if (!scrolling) {
      return { scrollY: window.scrollY, scrollHeight: 0, clientHeight: 0 };
    }
    return {
      scrollY: window.scrollY,
      scrollHeight: scrolling.scrollHeight,
      clientHeight: scrolling.clientHeight,
    };
  });
}

async function expectInViewport(locator: Locator) {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box, 'heading bounding box').not.toBeNull();
  const viewport = locator.page().viewportSize();
  expect(viewport, 'viewport size').not.toBeNull();
  expect(box!.y + box!.height).toBeGreaterThan(0);
  expect(box!.y).toBeLessThan(viewport!.height);
}

async function wheelUntilHeadingInView(
  page: Page,
  heading: Locator,
  maxWheels = 40,
) {
  for (let i = 0; i < maxWheels; i += 1) {
    const box = await heading.boundingBox();
    const viewport = page.viewportSize();
    if (
      box &&
      viewport &&
      box.y >= 0 &&
      box.y + Math.min(box.height, 24) <= viewport.height
    ) {
      return;
    }
    await page.mouse.wheel(0, 700);
  }
  await expectInViewport(heading);
}

test.describe('legal document real wheel scrolling (350×850)', () => {
  test('/terms does not apply map-first body overflow lock', async ({ page }) => {
    await page.goto('/terms');
    await expect(page.getByRole('heading', { level: 1, name: '이용약관' })).toBeVisible();

    const styles = await page.evaluate(() => {
      const body = getComputedStyle(document.body);
      const html = getComputedStyle(document.documentElement);
      return {
        bodyOverflowY: body.overflowY,
        htmlOverflowY: html.overflowY,
        hasMapFirst: Boolean(document.querySelector('.map-first')),
      };
    });

    expect(styles.hasMapFirst).toBe(false);
    expect(styles.bodyOverflowY).not.toBe('hidden');
    expect(styles.htmlOverflowY).not.toBe('hidden');
  });

  test('/terms: mouse.wheel moves scrollY and reaches 10. 준거법', async ({
    page,
  }) => {
    await page.goto('/terms');
    await expect(page.getByRole('heading', { level: 1, name: '이용약관' })).toBeVisible();

    const initial = await readScrollMetrics(page);
    expect(initial.scrollY).toBe(0);
    expect(initial.scrollHeight).toBeGreaterThan(initial.clientHeight);

    // Programmatic scrollTo는 이 버그를 검출하지 못하므로 사용하지 않는다.
    await page.mouse.wheel(0, 700);
    await expect
      .poll(async () => (await readScrollMetrics(page)).scrollY)
      .toBeGreaterThan(0);

    const lastHeading = page.getByRole('heading', {
      level: 2,
      name: '10. 준거법',
    });
    await wheelUntilHeadingInView(page, lastHeading);
    await expectInViewport(lastHeading);
  });

  test('/privacy: mouse.wheel moves scrollY and reaches last section', async ({
    page,
  }) => {
    await page.goto('/privacy');
    await expect(
      page.getByRole('heading', { level: 1, name: '개인정보처리방침' }),
    ).toBeVisible();

    const initial = await readScrollMetrics(page);
    expect(initial.scrollY).toBe(0);
    expect(initial.scrollHeight).toBeGreaterThan(initial.clientHeight);

    await page.mouse.wheel(0, 700);
    await expect
      .poll(async () => (await readScrollMetrics(page)).scrollY)
      .toBeGreaterThan(0);

    const lastHeading = page.getByRole('heading', {
      level: 2,
      name: '15. 이용자의 권리',
    });
    await wheelUntilHeadingInView(page, lastHeading);
    await expectInViewport(lastHeading);
  });
});
