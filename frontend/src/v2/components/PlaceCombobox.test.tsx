// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { useRef, useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { adapters } from '@/adapters';
import type { Place } from '@/types';
import PlaceCombobox from './PlaceCombobox';

const GIJANG: Place = {
  id: 'gijang',
  name: '기장군청',
  lat: 35.2445,
  lng: 129.2223,
  category: '공공기관',
  address: '부산 기장군',
};

const SEOMYEON: Place = {
  id: 'seomyeon',
  name: '서면역',
  lat: 35.1576,
  lng: 129.0591,
  category: '지하철역',
  address: '부산 부산진구',
};

function DualSearchHarness() {
  const [origin, setOrigin] = useState<Place | null>(null);
  const [destination, setDestination] = useState<Place | null>(null);
  const destinationInputRef = useRef<HTMLInputElement>(null);

  return (
    <div>
      <PlaceCombobox
        fieldId="map-first-origin"
        label="출발지"
        place={origin}
        onSelectPlace={setOrigin}
        onClearPlace={() => setOrigin(null)}
        onSelected={() => destinationInputRef.current?.focus()}
      />
      <PlaceCombobox
        fieldId="map-first-destination"
        label="도착지"
        place={destination}
        onSelectPlace={setDestination}
        onClearPlace={() => setDestination(null)}
        inputRef={destinationInputRef}
      />
      <output data-testid="origin-id">{origin?.id ?? ''}</output>
      <output data-testid="destination-id">{destination?.id ?? ''}</output>
    </div>
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
  vi.spyOn(adapters.places, 'searchPlaces').mockResolvedValue([GIJANG]);
});

async function searchAndWait(input: HTMLElement, value: string) {
  fireEvent.change(input, { target: { value } });
  await screen.findByRole('option', { name: new RegExp(value.slice(0, 2)) });
}

describe('PlaceCombobox 한글 IME', () => {
  it('출발지에서 기장군청 확정 후 도착지는 빈 문자열이다', async () => {
    render(<DualSearchHarness />);
    const origin = screen.getByLabelText('출발지');
    const destination = screen.getByLabelText('도착지') as HTMLInputElement;

    await searchAndWait(origin, '기장군청');
    fireEvent.keyDown(origin, { key: 'Enter', keyCode: 13, isComposing: false });

    await waitFor(() => {
      expect(screen.getByTestId('origin-id').textContent).toBe('gijang');
    });
    await waitFor(() => {
      expect(destination.value).toBe('');
    });
    expect(screen.getByTestId('destination-id').textContent).toBe('');
  });

  it('조합 중 Enter는 검색 결과 확정·필드 전환을 하지 않는다', async () => {
    render(<DualSearchHarness />);
    const origin = screen.getByLabelText('출발지');
    const destination = screen.getByLabelText('도착지') as HTMLInputElement;

    await searchAndWait(origin, '기장군청');
    fireEvent.compositionStart(origin);

    // native isComposing / keyCode 229
    fireEvent.keyDown(origin, {
      key: 'Enter',
      keyCode: 229,
      isComposing: true,
    });
    expect(screen.getByTestId('origin-id').textContent).toBe('');

    // composingRef만 true인 경우(이벤트 플래그가 이미 false)에도 확정하지 않는다.
    fireEvent.keyDown(origin, {
      key: 'Enter',
      keyCode: 13,
      isComposing: false,
    });

    expect(screen.getByTestId('origin-id').textContent).toBe('');
    expect(document.activeElement).not.toBe(destination);
    expect(destination.value).toBe('');
    expect(screen.getByRole('option', { name: /기장군청/ })).toBeTruthy();
  });

  it('조합 완료 후 Enter 검색 확정은 정상 작동한다', async () => {
    render(<DualSearchHarness />);
    const origin = screen.getByLabelText('출발지');

    fireEvent.compositionStart(origin);
    fireEvent.change(origin, { target: { value: '기장군ㅊ' } });
    fireEvent.compositionEnd(origin, { target: { value: '기장군청' } });
    fireEvent.change(origin, { target: { value: '기장군청' } });

    await screen.findByRole('option', { name: /기장군청/ });
    fireEvent.keyDown(origin, { key: 'Enter', keyCode: 13, isComposing: false });

    await waitFor(() => {
      expect(screen.getByTestId('origin-id').textContent).toBe('gijang');
    });
    expect((screen.getByLabelText('출발지') as HTMLInputElement).value).toBe(
      '기장군청',
    );
  });

  it('확정 직후 출발지 compositionend는 도착지 값을 바꾸지 않는다', async () => {
    render(<DualSearchHarness />);
    const origin = screen.getByLabelText('출발지');
    const destination = screen.getByLabelText('도착지') as HTMLInputElement;

    await searchAndWait(origin, '기장군청');
    fireEvent.keyDown(origin, { key: 'Enter', keyCode: 13, isComposing: false });

    await waitFor(() => {
      expect(destination.value).toBe('');
      expect(screen.getByTestId('origin-id').textContent).toBe('gijang');
    });

    fireEvent.compositionEnd(origin, { data: '청', target: { value: '기장군청' } });
    expect((origin as HTMLInputElement).value).toBe('기장군청');
    expect(destination.value).toBe('');
    expect(screen.getByTestId('destination-id').textContent).toBe('');
  });

  it('도착지에 입력한 첫 글자가 유실되지 않는다', async () => {
    vi.spyOn(adapters.places, 'searchPlaces').mockImplementation(async (query) => {
      if (query.includes('서')) return [SEOMYEON];
      return [GIJANG];
    });

    render(<DualSearchHarness />);
    const origin = screen.getByLabelText('출발지');
    const destination = screen.getByLabelText('도착지') as HTMLInputElement;

    await searchAndWait(origin, '기장군청');
    fireEvent.keyDown(origin, { key: 'Enter', keyCode: 13, isComposing: false });
    await waitFor(() => {
      expect(screen.getByTestId('origin-id').textContent).toBe('gijang');
    });

    fireEvent.compositionStart(destination);
    fireEvent.change(destination, { target: { value: 'ㅅ' } });
    fireEvent.compositionEnd(destination, { target: { value: '서' } });
    fireEvent.change(destination, { target: { value: '서' } });
    expect(destination.value).toBe('서');

    fireEvent.change(destination, { target: { value: '서면' } });
    expect(destination.value).toBe('서면');
  });

  it('마우스 선택 후에도 출발지·도착지 검색어 상태가 섞이지 않는다', async () => {
    render(<DualSearchHarness />);
    const origin = screen.getByLabelText('출발지');
    const destination = screen.getByLabelText('도착지') as HTMLInputElement;

    await searchAndWait(origin, '기장군청');
    fireEvent.click(screen.getByRole('option', { name: /기장군청/ }));

    await waitFor(() => {
      expect(screen.getByTestId('origin-id').textContent).toBe('gijang');
    });
    expect((origin as HTMLInputElement).value).toBe('기장군청');
    expect(destination.value).toBe('');
  });

  it('영문 입력 Enter 선택은 기존처럼 동작한다', async () => {
    const english: Place = {
      ...GIJANG,
      id: 'busan-city-hall',
      name: 'Busan City Hall',
    };
    vi.spyOn(adapters.places, 'searchPlaces').mockResolvedValue([english]);

    render(<DualSearchHarness />);
    const origin = screen.getByLabelText('출발지');
    fireEvent.change(origin, { target: { value: 'Busan' } });
    await screen.findByRole('option', { name: /Busan City Hall/ });
    fireEvent.keyDown(origin, { key: 'Enter', keyCode: 13, isComposing: false });

    await waitFor(() => {
      expect(screen.getByTestId('origin-id').textContent).toBe('busan-city-hall');
    });
    expect((screen.getByLabelText('도착지') as HTMLInputElement).value).toBe('');
  });
});

describe('PlaceCombobox 단일 필드', () => {
  it('검색 결과가 도착지 필드 상태를 건드리지 않는다', async () => {
    const onSelect = vi.fn();
    render(
      <PlaceCombobox
        fieldId="map-first-origin"
        label="출발지"
        place={null}
        onSelectPlace={onSelect}
        onClearPlace={vi.fn()}
      />,
    );

    const origin = screen.getByLabelText('출발지');
    fireEvent.change(origin, { target: { value: '기장군청' } });
    await waitFor(() => {
      expect(adapters.places.searchPlaces).toHaveBeenCalledWith('기장군청');
    });
    expect(onSelect).not.toHaveBeenCalled();
  });
});
