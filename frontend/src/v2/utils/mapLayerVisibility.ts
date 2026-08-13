export type MapLayerVisibility = {
  showShade: boolean;
  showSlope: boolean;
};

export type MapDataLayer = 'shade' | 'slope';

export const INITIAL_MAP_LAYER_VISIBILITY: MapLayerVisibility = {
  showShade: false,
  showSlope: false,
};

/** 지도 데이터 레이어는 서로 독립적으로 켜고 끈다. */
export function toggleMapDataLayer(
  current: MapLayerVisibility,
  layer: MapDataLayer,
): MapLayerVisibility {
  return layer === 'shade'
    ? { ...current, showShade: !current.showShade }
    : { ...current, showSlope: !current.showSlope };
}
