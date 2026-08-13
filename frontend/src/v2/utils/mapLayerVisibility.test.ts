import { describe, expect, it } from 'vitest';
import {
  INITIAL_MAP_LAYER_VISIBILITY,
  toggleMapDataLayer,
} from './mapLayerVisibility';

describe('map data layer visibility', () => {
  it('건물 그늘과 도보 경사를 동시에 켤 수 있다', () => {
    const shadeOn = toggleMapDataLayer(
      INITIAL_MAP_LAYER_VISIBILITY,
      'shade',
    );
    const bothOn = toggleMapDataLayer(shadeOn, 'slope');

    expect(bothOn).toEqual({ showShade: true, showSlope: true });
  });

  it('한 레이어를 꺼도 다른 레이어 상태를 유지한다', () => {
    const bothOn = { showShade: true, showSlope: true };

    expect(toggleMapDataLayer(bothOn, 'shade')).toEqual({
      showShade: false,
      showSlope: true,
    });
    expect(toggleMapDataLayer(bothOn, 'slope')).toEqual({
      showShade: true,
      showSlope: false,
    });
  });
});
