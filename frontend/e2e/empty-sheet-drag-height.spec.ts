import { expect, test, type Page } from '@playwright/test';

const VIEW = { width: 320, height: 568 };
const EMPTY_EXPANDED = 210;
const EMPTY_COLLAPSED = 120;
const MEDIUM_H = VIEW.height * 0.55; // ≈312.4
const TOL = 4;
/** 단조성: 다음 샘플이 이전보다 “의미 있게” 역전하지 않는 허용(레이아웃 노이즈) */
const MONO_EPS = 1.5;

type SheetSample = {
  rectHeight: number;
  inlineHeight: number | null;
  snap: string | null;
  className: string;
};

async function readSheetSample(page: Page): Promise<SheetSample> {
  return page.evaluate(() => {
    const sheet = document.querySelector('.map-first__sheet') as HTMLElement | null;
    if (!sheet) {
      return { rectHeight: 0, inlineHeight: null, snap: null, className: '' };
    }
    const inline = sheet.style.height.trim();
    let inlineHeight: number | null = null;
    if (inline.endsWith('px')) {
      const n = Number.parseFloat(inline);
      if (Number.isFinite(n)) inlineHeight = n;
    }
    return {
      rectHeight: sheet.getBoundingClientRect().height,
      inlineHeight,
      snap: sheet.getAttribute('data-sheet-snap'),
      className: sheet.className,
    };
  });
}

/**
 * snap·목표 rect가 일치하고, 연속 2개 animation frame에서
 * 높이 변화가 TOL 이내일 때까지 대기한다.
 * 검증값은 항상 getBoundingClientRect().height (inline은 진단 필드만).
 */
async function waitForStableSnapHeight(
  page: Page,
  snap: 'collapsed' | 'expanded',
  targetHeight: number,
  timeoutMs = 5000,
) {
  await page.waitForFunction(
    ({ snap: want, target, tol }) => {
      const sheet = document.querySelector('.map-first__sheet') as HTMLElement | null;
      if (!sheet) return false;
      if (sheet.getAttribute('data-sheet-snap') !== want) return false;
      if (sheet.classList.contains('map-first__sheet--medium')) return false;
      const h = sheet.getBoundingClientRect().height;
      if (Math.abs(h - target) > tol) return false;

      return new Promise<boolean>((resolve) => {
        requestAnimationFrame(() => {
          const h1 = sheet.getBoundingClientRect().height;
          requestAnimationFrame(() => {
            const h2 = sheet.getBoundingClientRect().height;
            resolve(
              Math.abs(h1 - target) <= tol
                && Math.abs(h2 - target) <= tol
                && Math.abs(h2 - h1) <= tol,
            );
          });
        });
      });
    },
    { snap, target: targetHeight, tol: TOL },
    { timeout: timeoutMs },
  );
}

async function dispatchPointer(
  page: Page,
  type: 'pointerdown' | 'pointermove' | 'pointerup',
  init: {
    pointerId: number;
    clientY: number;
    button?: number;
    target?: 'toggle' | 'window';
  },
  buttonName?: string,
) {
  await page.evaluate(
    ({ type: evType, init: evInit, buttonName: label }) => {
      const target: EventTarget =
        evInit.target === 'toggle'
          ? (Array.from(document.querySelectorAll('button')).find(
              (el) => el.getAttribute('aria-label') === label,
            ) as HTMLElement)
          : window;
      if (!target) throw new Error('pointer target missing');
      target.dispatchEvent(
        new PointerEvent(evType, {
          bubbles: true,
          cancelable: true,
          pointerId: evInit.pointerId,
          clientY: evInit.clientY,
          button: evInit.button ?? 0,
          pointerType: 'mouse',
        }),
      );
    },
    {
      type,
      init,
      buttonName: buttonName ?? '',
    },
  );
}

async function dragToggleSampling(
  page: Page,
  buttonName: string,
  deltaY: number,
  steps: number,
) {
  const toggle = page.getByRole('button', { name: buttonName });
  await expect(toggle).toBeVisible();
  const box = await toggle.boundingBox();
  if (!box) throw new Error(`toggle "${buttonName}" not found`);
  const startY = box.y + Math.min(8, box.height / 2);
  const pointerId = 88;

  const beforeDown = await readSheetSample(page);

  await dispatchPointer(
    page,
    'pointerdown',
    { pointerId, clientY: startY, button: 0, target: 'toggle' },
    buttonName,
  );
  // paint 후 즉시 측정 — 스파이크를 숨기지 않음
  await page.evaluate(() => new Promise<void>((r) => requestAnimationFrame(() => r())));
  const afterDown = await readSheetSample(page);

  const moveSamples: SheetSample[] = [];
  for (let i = 1; i <= steps; i += 1) {
    const y = startY + (deltaY * i) / steps;
    await dispatchPointer(page, 'pointermove', {
      pointerId,
      clientY: y,
      target: 'window',
    });
    await page.evaluate(() => new Promise<void>((r) => requestAnimationFrame(() => r())));
    moveSamples.push(await readSheetSample(page));
  }

  await dispatchPointer(page, 'pointerup', {
    pointerId,
    clientY: startY + deltaY,
    target: 'window',
  });

  return { beforeDown, afterDown, moveSamples };
}

function assertNoMedium(sample: SheetSample) {
  expect(sample.snap).not.toBe('medium');
  expect(sample.className).not.toContain('sheet--medium');
  expect(Math.abs(sample.rectHeight - MEDIUM_H)).toBeGreaterThan(20);
}

function assertNear(actual: number, expected: number, label: string) {
  expect(
    Math.abs(actual - expected),
    `${label}: actual=${actual} expected≈${expected}`,
  ).toBeLessThanOrEqual(TOL);
}

/** 아래로 접을 때: 각 샘플이 이전보다 의미 있게 커지지 않음 */
function assertNonIncreasing(heights: number[]) {
  for (let i = 1; i < heights.length; i += 1) {
    expect(
      heights[i]! - heights[i - 1]!,
      `non-increasing broken at ${i}: ${heights[i - 1]} → ${heights[i]}`,
    ).toBeLessThanOrEqual(MONO_EPS);
  }
}

/** 위로 펼칠 때: 각 샘플이 이전보다 의미 있게 작아지지 않음 */
function assertNonDecreasing(heights: number[]) {
  for (let i = 1; i < heights.length; i += 1) {
    expect(
      heights[i - 1]! - heights[i]!,
      `non-decreasing broken at ${i}: ${heights[i - 1]} → ${heights[i]}`,
    ).toBeLessThanOrEqual(MONO_EPS);
  }
}

test('empty sheet drag mid-heights stay collapsed↔expanded and never hit medium', async ({
  page,
}) => {
  await page.setViewportSize(VIEW);
  await page.goto('/');
  await page.waitForSelector('.map-first__sheet--empty');
  await waitForStableSnapHeight(page, 'expanded', EMPTY_EXPANDED);

  const startSample = await readSheetSample(page);
  assertNear(startSample.rectHeight, EMPTY_EXPANDED, 'expanded start');
  assertNoMedium(startSample);

  const down = await dragToggleSampling(page, '경로 결과 접기', 140, 14);
  assertNear(down.beforeDown.rectHeight, EMPTY_EXPANDED, 'down before pointerdown');
  assertNear(down.afterDown.rectHeight, EMPTY_EXPANDED, 'down after pointerdown (no move)');
  expect(Math.abs(down.afterDown.rectHeight - down.beforeDown.rectHeight)).toBeLessThanOrEqual(
    TOL,
  );

  const downHeights = [
    down.afterDown.rectHeight,
    ...down.moveSamples.map((s) => s.rectHeight),
  ];
  assertNonIncreasing(downHeights);
  for (const h of downHeights) {
    expect(h).toBeGreaterThanOrEqual(EMPTY_COLLAPSED - TOL);
    expect(h).toBeLessThanOrEqual(EMPTY_EXPANDED + TOL);
    expect(Math.abs(h - MEDIUM_H)).toBeGreaterThan(20);
  }
  assertNoMedium(down.afterDown);
  for (const s of down.moveSamples) assertNoMedium(s);

  await waitForStableSnapHeight(page, 'collapsed', EMPTY_COLLAPSED);
  const collapsedStable = await readSheetSample(page);
  assertNear(collapsedStable.rectHeight, EMPTY_COLLAPSED, 'collapsed settled');
  assertNoMedium(collapsedStable);

  const up = await dragToggleSampling(page, '경로 결과 펼치기', -140, 14);
  assertNear(up.beforeDown.rectHeight, EMPTY_COLLAPSED, 'up before pointerdown');
  assertNear(up.afterDown.rectHeight, EMPTY_COLLAPSED, 'up after pointerdown (no move)');
  expect(Math.abs(up.afterDown.rectHeight - up.beforeDown.rectHeight)).toBeLessThanOrEqual(
    TOL,
  );

  const upHeights = [
    up.afterDown.rectHeight,
    ...up.moveSamples.map((s) => s.rectHeight),
  ];
  assertNonDecreasing(upHeights);
  for (const h of upHeights) {
    expect(h).toBeGreaterThanOrEqual(EMPTY_COLLAPSED - TOL);
    expect(h).toBeLessThanOrEqual(EMPTY_EXPANDED + TOL);
    expect(Math.abs(h - MEDIUM_H)).toBeGreaterThan(20);
  }
  assertNoMedium(up.afterDown);
  for (const s of up.moveSamples) assertNoMedium(s);

  await waitForStableSnapHeight(page, 'expanded', EMPTY_EXPANDED);
  assertNoMedium(await readSheetSample(page));

  const report = {
    start: startSample,
    down: {
      beforeDown: down.beforeDown,
      afterDown: down.afterDown,
      moveSamples: down.moveSamples,
      rectHeights: downHeights.map((h) => Math.round(h * 10) / 10),
    },
    collapsedStable,
    up: {
      beforeDown: up.beforeDown,
      afterDown: up.afterDown,
      moveSamples: up.moveSamples,
      rectHeights: upHeights.map((h) => Math.round(h * 10) / 10),
    },
    mediumForbidden: Math.round(MEDIUM_H * 10) / 10,
  };
  console.log(JSON.stringify(report));
});
