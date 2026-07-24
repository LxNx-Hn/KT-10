// @vitest-environment jsdom
import { act, cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { adapters } from '@/adapters';
import { useAppStore } from '@/store/appStore';
import type { Place } from '@/types';
import SearchBar from './SearchBar';

const BUSAN_STATION: Place = {
  id: 'busan-station',
  name: '부산역',
  lat: 35.1151,
  lng: 129.0414,
  category: '지하철역',
  address: '부산 동구 중앙대로 206',
};

beforeEach(() => {
  vi.useFakeTimers();
  useAppStore.setState({
    origin: null,
    destination: null,
    loading: false,
    error: null,
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function finishDebounce() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(200);
  });
}

describe('출발지·도착지 장소 검색', () => {
  it('선택되지 않은 출발지를 즉시 안내하고 해당 입력으로 초점을 옮긴다', () => {
    const { getByLabelText, getByRole } = render(<SearchBar />);

    fireEvent.click(getByRole('button', { name: '경로 찾기' }));

    expect(getByRole('alert').textContent).toContain('출발지');
    expect(document.activeElement).toBe(getByLabelText('출발지'));
  });

  it('부산역 Kakao 검색 결과를 키보드 Enter로 출발지에 선택한다', async () => {
    const search = vi.spyOn(adapters.places, 'searchPlaces').mockResolvedValue([BUSAN_STATION]);
    const { getByLabelText, getByRole } = render(<SearchBar />);
    const input = getByLabelText('출발지');

    fireEvent.change(input, { target: { value: '부산역' } });
    await finishDebounce();

    expect(search).toHaveBeenCalledWith('부산역');
    expect(getByRole('option', { name: /부산역/ })).toBeTruthy();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(useAppStore.getState().origin).toEqual(BUSAN_STATION);
    expect((input as HTMLInputElement).value).toBe('부산역');
  });

  it('선택한 장소명을 수정하면 이전 좌표를 즉시 해제한다', async () => {
    vi.spyOn(adapters.places, 'searchPlaces').mockResolvedValue([BUSAN_STATION]);
    const { getByLabelText } = render(<SearchBar />);
    const input = getByLabelText('출발지');

    fireEvent.change(input, { target: { value: '부산역' } });
    await finishDebounce();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(useAppStore.getState().origin).toEqual(BUSAN_STATION);

    fireEvent.change(input, { target: { value: '북구청' } });
    expect(useAppStore.getState().origin).toBeNull();
  });

  it('새 검색 중에는 이전 결과를 숨기고 이전 응답이 선택 결과를 덮지 않는다', async () => {
    let resolveFirst!: (places: Place[]) => void;
    const first = new Promise<Place[]>((resolve) => {
      resolveFirst = resolve;
    });
    const search = vi.spyOn(adapters.places, 'searchPlaces')
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce([BUSAN_STATION]);
    const { getByLabelText, queryByRole, getByRole } = render(<SearchBar />);
    const input = getByLabelText('출발지');

    fireEvent.change(input, { target: { value: '북구청' } });
    await finishDebounce();
    fireEvent.change(input, { target: { value: '부산역' } });
    expect(queryByRole('option')).toBeNull();
    await finishDebounce();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(useAppStore.getState().origin).toEqual(BUSAN_STATION);

    await act(async () => {
      resolveFirst([{
        id: 'buk-gu-office',
        name: '부산광역시북구청',
        lat: 35.1969,
        lng: 128.9902,
      }]);
      await first;
    });
    expect(search).toHaveBeenCalledTimes(2);
    expect(useAppStore.getState().origin).toEqual(BUSAN_STATION);
    expect(queryByRole('option')).toBeNull();
    expect(getByRole('combobox', { name: '출발지' })).toBe(input);
  });

  it('빈 응답은 검색어와 서비스 권역을 포함해 안내한다', async () => {
    vi.spyOn(adapters.places, 'searchPlaces').mockResolvedValue([]);
    const { getByLabelText, getByRole } = render(<SearchBar />);

    fireEvent.change(getByLabelText('도착지'), { target: { value: '북구청' } });
    await finishDebounce();

    expect(getByRole('status').textContent).toContain('‘북구청’에 대한 부산 지역 검색 결과');
    expect(getByRole('status').textContent).toContain('장소명이나 주소');
  });

  it('입력 영역 밖을 누르면 열려 있던 장소 결과를 닫는다', async () => {
    vi.spyOn(adapters.places, 'searchPlaces').mockResolvedValue([BUSAN_STATION]);
    const { getByLabelText, queryByRole } = render(<SearchBar />);

    fireEvent.change(getByLabelText('출발지'), { target: { value: '부산역' } });
    await finishDebounce();
    expect(queryByRole('option')).toBeTruthy();

    fireEvent.pointerDown(document.body);
    expect(queryByRole('option')).toBeNull();
  });
});
