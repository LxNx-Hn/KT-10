// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, act } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import VoiceChatDock from './VoiceChatDock';
import { useVoiceChatStore } from '@/chat/voiceChatStore';

async function readMapFirstCss(): Promise<string> {
  // Vitest Node 런타임; 앱 tsconfig에 @types/node 없음.
  // Vite는 import.meta.url을 file:이 아닌 URL로 줄 수 있어 cwd 기준 경로를 사용한다.
  // @ts-expect-error node built-in
  const { readFileSync } = await import('node:fs');
  // @ts-expect-error node built-in
  const { resolve } = await import('node:path');
  const cwd = (globalThis as { process?: { cwd?: () => string } }).process
    ?.cwd?.();
  if (!cwd) {
    throw new Error('process.cwd unavailable');
  }
  return readFileSync(resolve(cwd, 'src/v2/map-first.css'), 'utf8') as string;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(window, 'visualViewport');
  useVoiceChatStore.setState({
    status: 'idle',
    messages: [],
    interim: '',
    awaiting: null,
    listenRequestId: 0,
  });
});

function stubVisualViewport(init: {
  width: number;
  height: number;
  offsetTop?: number;
  offsetLeft?: number;
}) {
  const listeners = new Map<string, Set<EventListener>>();
  const vv = {
    width: init.width,
    height: init.height,
    offsetTop: init.offsetTop ?? 0,
    offsetLeft: init.offsetLeft ?? 0,
    scale: 1,
    pageLeft: 0,
    pageTop: 0,
    onresize: null,
    onscroll: null,
    addEventListener(type: string, listener: EventListener) {
      const set = listeners.get(type) ?? new Set();
      set.add(listener);
      listeners.set(type, set);
    },
    removeEventListener(type: string, listener: EventListener) {
      listeners.get(type)?.delete(listener);
    },
    dispatchEvent() {
      return false;
    },
    emit(type: string) {
      for (const listener of listeners.get(type) ?? []) {
        listener(new Event(type));
      }
    },
  };
  Object.defineProperty(window, 'visualViewport', {
    configurable: true,
    value: vv,
  });
  return vv;
}

describe('VoiceChatDock MOB-22 viewport', () => {
  it('map-first 열기·닫기와 입력·보내기를 유지한다', () => {
    const onOpenChange = vi.fn();
    const { rerender } = render(
      <VoiceChatDock variant="map-first" open onOpenChange={onOpenChange} />,
    );

    expect(screen.getByRole('region', { name: '음성 챗봇' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '음성 챗봇 닫기' })).toBeTruthy();
    const input = screen.getByRole('textbox', { name: '챗봇 텍스트 입력' });
    fireEvent.change(input, { target: { value: '서면역까지' } });
    fireEvent.submit(input.closest('form')!);

    fireEvent.click(screen.getByRole('button', { name: '음성 챗봇 닫기' }));
    expect(onOpenChange).toHaveBeenCalledWith(false);

    rerender(
      <VoiceChatDock variant="map-first" open={false} onOpenChange={onOpenChange} />,
    );
    expect(screen.queryByRole('region', { name: '음성 챗봇' })).toBeNull();
  });

  it('열린 map-first 패널에 visual viewport CSS 변수를 반영한다', () => {
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      value: 844,
    });
    const vv = stubVisualViewport({
      width: 390,
      height: 520,
      offsetTop: 100,
      offsetLeft: 0,
    });

    const { container, unmount } = render(
      <VoiceChatDock variant="map-first" open onOpenChange={() => undefined} />,
    );
    const dock = container.querySelector('.voicedock--map-first') as HTMLElement;
    expect(dock.getAttribute('data-vv-bound')).toBe('true');
    expect(dock.style.getPropertyValue('--mf-vv-width')).toBe('390px');
    expect(dock.style.getPropertyValue('--mf-vv-height')).toBe('520px');
    expect(dock.style.getPropertyValue('--mf-vv-offset-top')).toBe('100px');
    expect(dock.style.getPropertyValue('--mf-vv-bottom-inset')).toBe('224px');

    act(() => {
      vv.height = 400;
      vv.offsetTop = 180;
      vv.emit('resize');
    });
    expect(dock.style.getPropertyValue('--mf-vv-height')).toBe('400px');
    expect(dock.style.getPropertyValue('--mf-vv-bottom-inset')).toBe('264px');

    unmount();
  });

  it('visualViewport 미지원 시 innerWidth/Height fallback 변수를 쓴다', () => {
    Reflect.deleteProperty(window, 'visualViewport');
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: 375,
    });
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      value: 667,
    });

    const { container } = render(
      <VoiceChatDock variant="map-first" open onOpenChange={() => undefined} />,
    );
    const dock = container.querySelector('.voicedock--map-first') as HTMLElement;
    expect(dock.style.getPropertyValue('--mf-vv-width')).toBe('375px');
    expect(dock.style.getPropertyValue('--mf-vv-height')).toBe('667px');
    expect(dock.style.getPropertyValue('--mf-vv-bottom-inset')).toBe('0px');
  });

  it('긴 결과에서도 본문(log) 스크롤 영역과 헤더·입력이 분리된다', () => {
    useVoiceChatStore.setState({
      messages: Array.from({ length: 24 }, (_, index) => ({
        id: `m-${index}`,
        role: index % 2 === 0 ? 'user' : 'assistant',
        text: `메시지 ${index + 1} — 경로 안내 테스트 문장입니다.`,
        createdAt: new Date(Date.now() + index).toISOString(),
      })),
    });

    const { container } = render(
      <VoiceChatDock variant="map-first" open onOpenChange={() => undefined} />,
    );
    const dock = container.querySelector('.voicedock--map-first')!;
    const handle = dock.querySelector('.voicedock__handle')!;
    const body = dock.querySelector('.voicedock__body')!;
    const log = dock.querySelector('.voicedock__log')!;
    const entry = dock.querySelector('.voicedock__textentry')!;

    expect(handle.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(log.compareDocumentPosition(entry) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(handle.textContent).toContain('닫기');
    expect(screen.getByRole('textbox', { name: '챗봇 텍스트 입력' })).toBeTruthy();
    expect(log.querySelectorAll('.chatmsg').length).toBe(24);
  });

  it('닫히면 visual viewport listener 구독을 중단한다', () => {
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      value: 844,
    });
    const vv = stubVisualViewport({ width: 390, height: 700 });
    const removeSpy = vi.spyOn(vv, 'removeEventListener');
    const { rerender } = render(
      <VoiceChatDock variant="map-first" open onOpenChange={() => undefined} />,
    );

    rerender(
      <VoiceChatDock
        variant="map-first"
        open={false}
        onOpenChange={() => undefined}
      />,
    );
    expect(removeSpy).toHaveBeenCalledWith('resize', expect.any(Function));
    expect(removeSpy).toHaveBeenCalledWith('scroll', expect.any(Function));
  });

  it('텍스트 입력 포커스 전후 focus-within이 구분되고 입력·보내기 구조를 유지한다', () => {
    render(
      <VoiceChatDock variant="map-first" open onOpenChange={() => undefined} />,
    );
    const input = screen.getByRole('textbox', {
      name: '챗봇 텍스트 입력',
    }) as HTMLInputElement;
    const form = input.closest('form') as HTMLFormElement;
    const submit = form.querySelector('button[type="submit"]');

    expect(form.classList.contains('voicedock__textentry')).toBe(true);
    expect(submit).toBeTruthy();
    // jsdom은 :focus-within 매칭이 불안정하므로 포커스 포함 여부로 전/후를 구분한다.
    expect(form.contains(document.activeElement)).toBe(false);

    act(() => {
      input.focus();
    });
    expect(document.activeElement).toBe(input);
    expect(form.contains(document.activeElement)).toBe(true);

    act(() => {
      input.blur();
    });
    expect(document.activeElement === input).toBe(false);
    expect(form.querySelector('button[type="submit"]')).toBe(submit);
  });

  it('모바일 CSS에 키보드 보조 바 보호·16px 입력이 있고 desktop는 frame 내부 floating card다', async () => {
    const css = await readMapFirstCss();
    const mobileIdx = css.indexOf('@media (max-width: 479px)');
    const desktopIdx = css.indexOf('@media (min-width: 480px)');
    const accessoryRule = css.indexOf(
      '--mf-voice-kb-accessory: calc(44px + 8px)',
    );
    const focusWithin = css.indexOf(
      '.voicedock__textentry:focus-within',
    );
    const mobileFontMarker =
      '.voicedock.voicedock--map-first .voicedock__textentry input';
    const mobileInputBlock = css.indexOf(mobileFontMarker, mobileIdx);
    const font16 = css.indexOf('font-size: 16px', mobileInputBlock);
    const desktop = css.slice(desktopIdx, desktopIdx + 4500);

    expect(mobileIdx).toBeGreaterThan(-1);
    expect(accessoryRule).toBeGreaterThan(mobileIdx);
    expect(focusWithin).toBeGreaterThan(mobileIdx);
    expect(mobileInputBlock).toBeGreaterThan(mobileIdx);
    expect(font16).toBeGreaterThan(mobileInputBlock);
    expect(css).toContain('--mf-voice-kb-accessory');
    expect(css).toMatch(/padding-bottom:\s*max\(/);
    expect(css).toContain('var(--mf-voice-kb-accessory)');
    expect(css).toContain('env(safe-area-inset-bottom, 0px)');
    expect(desktopIdx).toBeGreaterThan(-1);
    expect(desktop).toContain('width: min(360px, calc(100% - 32px))');
    expect(desktop).not.toContain('transform: translateX(-50%)');
    // 입력 16px·accessory는 max-width:479 모바일 블록 안에 있다.
    expect(font16).toBeGreaterThan(mobileIdx);
  });
});
