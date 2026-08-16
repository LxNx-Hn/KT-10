import { describe, expect, it } from 'vitest';
import {
  ALTERNATIVE_ROUTE_COLOR,
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

  it('도보는 차콜색 점선이고, 버스는 파랑 실선이다', () => {
    expect(transportModeStrokeColor('walk')).toBe(TRANSPORT_MODE_COLOR.walk);
    expect(transportModeStrokeStyle('walk', 'exact')).toBe('shortdash');
    expect(transportModeStrokeStyle('walk', 'estimated')).toBe('shortdash');
    expect(transportModeStrokeColor('bus')).toBe(TRANSPORT_MODE_COLOR.bus);
    expect(transportModeStrokeStyle('bus', 'exact')).toBe('solid');
  });

  it('버스·지하철은 geometryQuality와 무관하게 실선이다', () => {
    for (const quality of ['exact', 'mixed', 'estimated'] as const) {
      expect(transportModeStrokeStyle('bus', quality)).toBe('solid');
      expect(transportModeStrokeStyle('subway', quality)).toBe('solid');
    }
  });

  it('일반 도보는 품질과 무관하게 점선이고, 경사값이 있으면 실선이다', () => {
    expect(transportModeStrokeStyle('walk', 'exact')).toBe('shortdash');
    expect(transportModeStrokeStyle('walk', 'estimated')).toBe('shortdash');
    expect(
      transportModeStrokeStyle('walk', 'estimated', { slopePercent: 8 }),
    ).toBe('solid');
    expect(
      transportModeStrokeStyle('walk', 'exact', { slopePercent: 8 }),
    ).toBe('solid');
  });

  it('도보 경사값이 있으면 slopeColorFn 결과를 쓴다', () => {
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

  it('환승은 geometryQuality에 따라 실선/점선을 유지한다', () => {
    expect(transportModeStrokeStyle('transfer', 'exact')).toBe('solid');
    expect(transportModeStrokeStyle('transfer', 'estimated')).toBe('shortdash');
    expect(transportModeStrokeStyle('transfer', 'mixed')).toBe('shortdash');
  });

  it('예비 경로 색은 건물 그늘 회색과 겹치지 않는다', () => {
    const shadowStroke = '#64748b';
    const shadowFill = '#8290a8';
    expect(ALTERNATIVE_ROUTE_COLOR.toLowerCase()).not.toBe(shadowStroke);
    expect(ALTERNATIVE_ROUTE_COLOR.toLowerCase()).not.toBe(shadowFill);
    expect(ALTERNATIVE_ROUTE_COLOR.toLowerCase()).not.toBe(
      TRANSPORT_MODE_COLOR.bus.toLowerCase(),
    );
    expect(ALTERNATIVE_ROUTE_COLOR.toLowerCase()).not.toBe(
      TRANSPORT_MODE_COLOR.walk.toLowerCase(),
    );
  });
});
