// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { adapters } from '@/adapters';
import BusArrivalCard from '@/components/BusArrivalCard';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
  vi.spyOn(adapters.bus, 'listStops').mockResolvedValue([]);
  vi.spyOn(adapters.bus, 'getArrivals').mockResolvedValue(undefined);
});

describe('저상버스 도착 상태', () => {
  it('검색 전에는 초기 안내만 보이고 빈 결과 문구를 쓰지 않는다', () => {
    render(<BusArrivalCard />);
    expect(screen.getByText('정류장을 검색하면 도착 정보가 표시돼요.')).toBeTruthy();
    expect(screen.queryByText('도착 정보가 없습니다.')).toBeNull();
    expect(screen.queryByText('현재 확인되는 도착 정보가 없어요.')).toBeNull();
    expect(adapters.bus.getArrivals).not.toHaveBeenCalled();
  });

  it('검색 후 도착이 없으면 빈 결과 안내를 구분한다', async () => {
    vi.spyOn(adapters.bus, 'listStops').mockResolvedValue([
      { stopId: 'stop-1', stopName: '서면역', arrivals: [] },
    ]);
    vi.spyOn(adapters.bus, 'getArrivals').mockResolvedValue({
      stopId: 'stop-1',
      stopName: '서면역',
      arrivals: [],
    });

    render(<BusArrivalCard />);
    fireEvent.change(screen.getByLabelText('버스 정류장 검색'), {
      target: { value: '서면' },
    });
    fireEvent.click(screen.getByRole('button', { name: '검색' }));

    await waitFor(() => {
      expect(screen.getByText('현재 확인되는 도착 정보가 없어요.')).toBeTruthy();
    });
    expect(screen.queryByText('정류장을 검색하면 도착 정보가 표시돼요.')).toBeNull();
    expect(screen.queryByText('도착 정보가 없습니다.')).toBeNull();
  });

  it('오류 시 원인 안내와 재시도를 제공한다', async () => {
    vi.spyOn(adapters.bus, 'listStops').mockRejectedValue(new Error('network'));

    render(<BusArrivalCard />);
    fireEvent.change(screen.getByLabelText('버스 정류장 검색'), {
      target: { value: '서면' },
    });
    fireEvent.click(screen.getByRole('button', { name: '검색' }));

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('정류장 검색에 실패');
    });
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy();
  });

  it('도착까지 1분 미만이면 0분 대신 곧 도착으로 표시한다', async () => {
    vi.spyOn(adapters.bus, 'listStops').mockResolvedValue([
      { stopId: 'stop-1', stopName: '서면역', arrivals: [] },
    ]);
    vi.spyOn(adapters.bus, 'getArrivals').mockResolvedValue({
      stopId: 'stop-1',
      stopName: '서면역',
      arrivals: [
        { routeName: '100', vehicleNo: '1234', arrivalMin: 0, isLowFloor: true },
        { routeName: '200', vehicleNo: '5678', arrivalMin: 4, isLowFloor: false },
      ],
    });

    render(<BusArrivalCard />);
    fireEvent.change(screen.getByLabelText('버스 정류장 검색'), {
      target: { value: '서면' },
    });
    fireEvent.click(screen.getByRole('button', { name: '검색' }));

    await waitFor(() => {
      expect(screen.getByText('곧 도착')).toBeTruthy();
    });
    expect(screen.getByText('4분 후')).toBeTruthy();
    expect(screen.queryByText('0분 후')).toBeNull();
  });
});
