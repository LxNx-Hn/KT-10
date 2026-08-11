import { describe, expect, it } from 'vitest';

async function readMapFirstCss(): Promise<string> {
  // @ts-expect-error node built-in
  const { readFileSync } = await import('node:fs');
  // @ts-expect-error node built-in
  const { resolve } = await import('node:path');
  const cwd = (globalThis as { process?: { cwd?: () => string } }).process
    ?.cwd?.();
  if (!cwd) throw new Error('process.cwd unavailable');
  return readFileSync(resolve(cwd, 'src/v2/map-first.css'), 'utf8') as string;
}

describe('map-first P0 layout CSS contracts', () => {
  it('검색은 frame 안 fixed/absolute가 아니라 .map-first__search-screen overlay를 쓴다', async () => {
    const css = await readMapFirstCss();
    expect(css).toContain('.map-first__search-screen {');
    expect(css).toContain(
      'bottom: var(--mf-search-vv-bottom-inset, 0px)',
    );
    expect(css).toContain(
      'padding-top: max(12px, env(safe-area-inset-top, 0px))',
    );
    const badHeader = css.indexOf(
      '.map-first__frame--search .map-first__search-header {',
    );
    expect(badHeader).toBe(-1);
  });

  it('desktop은 expanded 결과에서 search/fab가 sheet handle을 가로채지 않는다', async () => {
    const css = await readMapFirstCss();
    const desktopIdx = css.indexOf('@media (min-width: 480px)');
    const desktop = css.slice(desktopIdx, desktopIdx + 4500);
    expect(desktop).toContain(
      '.map-first__frame--results:has(.map-first__sheet--expanded) .map-first__search-header',
    );
    expect(desktop).toContain('pointer-events: none');
    expect(desktop).toContain('--mf-desktop-fab-gap: 16px');
    expect(desktop).not.toContain('top: 20%');
  });

  it('desktop mapInfo popover는 FAB bottom 정렬로 sheet와 겹치지 않게 위로 펼친다', async () => {
    const css = await readMapFirstCss();
    const desktopIdx = css.indexOf('@media (min-width: 480px)');
    const desktop = css.slice(desktopIdx, desktopIdx + 4500);
    const panelIdx = desktop.indexOf('.map-first__map-info-panel {');
    const panel = desktop.slice(panelIdx, panelIdx + 500);
    expect(panel).toContain('right: calc(100% + 12px)');
    expect(panel).toContain('bottom: 0');
    expect(panel).toContain('top: auto');
    expect(panel).toContain('max-height: 280px');
  });

  it('mobile mapInfo panel은 FAB % width가 아니라 고정 card 폭을 쓴다', async () => {
    const css = await readMapFirstCss();
    const mobileIdx = css.indexOf('@media (max-width: 479px)');
    expect(mobileIdx).toBeGreaterThan(-1);
    const mobile = css.slice(mobileIdx);
    const panelIdx = mobile.indexOf(
      '/* 6) 지도 정보 패널: FAB 위 floating card. width는 FAB %가 아니라 고정 px */',
    );
    expect(panelIdx).toBeGreaterThan(-1);
    const panel = mobile.slice(panelIdx, panelIdx + 550);
    expect(panel).toContain('width: 220px');
    expect(panel).toContain('min-width: 200px');
    expect(panel).toContain('max-width: 220px');
    expect(panel).not.toContain('calc(100% - 32px)');
    expect(panel).toContain('white-space: nowrap');
  });

  it('desktop voice dock은 frame 내부 absolute floating card다', async () => {
    const css = await readMapFirstCss();
    const desktopIdx = css.indexOf('@media (min-width: 480px)');
    const desktop = css.slice(desktopIdx, desktopIdx + 4500);
    expect(desktop).toContain(
      '.map-first__frame .voicedock.voicedock--map-first',
    );
    expect(desktop).toContain('width: min(360px, calc(100% - 32px))');
    expect(desktop).toContain('right: 16px');
    expect(desktop).toContain('bottom: 16px');
    expect(desktop).not.toContain('transform: translateX(-50%)');
  });

  it('검색 focus ring은 inset box-shadow로 clipping 밖으로 나가지 않는다', async () => {
    const css = await readMapFirstCss();
    expect(css).toContain(
      '.map-first__search-screen .map-first__search-input:focus-visible',
    );
    expect(css).toContain(
      'box-shadow: inset 0 0 0 3px rgba(25, 31, 40, 0.92)',
    );
  });
});
