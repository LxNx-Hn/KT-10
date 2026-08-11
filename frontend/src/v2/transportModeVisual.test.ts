import { describe, expect, it } from 'vitest';
import {
  SUBWAY_LINE_COLOR,
  TRANSPORT_MODE_COLOR,
  resolveSubwayLine,
  subwayStrokeColor,
  transportModeStrokeColor,
  transportModeStrokeStyle,
} from './transportModeVisual';

describe('transportModeVisual', () => {
  it('이동수단 stroke 색은 그늘 초록(#00b84a)과 겹치지 않는다', () => {
    const shadeGreen = '#00b84a';
    expect(TRANSPORT_MODE_COLOR.walk.toLowerCase()).not.toBe(shadeGreen);
    expect(TRANSPORT_MODE_COLOR.bus.toLowerCase()).not.toBe(shadeGreen);
    expect(TRANSPORT_MODE_COLOR.subway.toLowerCase()).not.toBe(shadeGreen);
  });

  it('도보는 차콜색 + 점선, 버스는 파랑 실선(exact)으로 구분한다', () => {
    expect(transportModeStrokeColor('walk')).toBe(TRANSPORT_MODE_COLOR.walk);
    expect(transportModeStrokeStyle('walk', 'exact')).toBe('shortdash');
    expect(transportModeStrokeColor('bus')).toBe(TRANSPORT_MODE_COLOR.bus);
    expect(transportModeStrokeStyle('bus', 'exact')).toBe('solid');
  });

  it('도보 경사값이 있으면 점선 대신 solid를 쓰고 slopeColorFn 결과를 쓴다', () => {
    expect(
      transportModeStrokeColor('walk', {
        slopePercent: 12,
        slopeColorFn: () => '#E3362D',
      }),
    ).toBe('#E3362D');
    expect(
      transportModeStrokeStyle('walk', 'exact', { slopePercent: 12 }),
    ).toBe('solid');
  });

  it('지하철은 카드와 같은 부산 호선색을 쓰고, 미확인은 fallback 보라를 쓴다', () => {
    expect(
      resolveSubwayLine({ description: '부산1호선', transitRouteId: undefined }),
    ).toEqual({ id: 'busan-1', label: '1호선' });
    expect(subwayStrokeColor('busan-1')).toBe(SUBWAY_LINE_COLOR['busan-1']);
    expect(subwayStrokeColor('busan-1')).toBe('#f06a00');
    expect(
      transportModeStrokeColor('subway', { subwayLineId: 'busan-2' }),
    ).toBe('#81bf48');
    expect(transportModeStrokeColor('subway')).toBe(TRANSPORT_MODE_COLOR.subway);
  });
});
