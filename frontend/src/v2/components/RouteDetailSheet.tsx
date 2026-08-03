import {
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react';
import BusArrivalCard from '@/components/BusArrivalCard';
import WeatherWarning from '@/components/WeatherWarning';
import type { ProfileId, ScoredRoute } from '@/types';
import BottomDrawer from './BottomDrawer';
import FeedbackTabPanel from './FeedbackTabPanel';
import RouteDetails from './RouteDetails';

export type DetailTab = 'route' | 'environment' | 'feedback';

const DETAIL_TABS: Array<[DetailTab, string]> = [
  ['route', '경로'],
  ['environment', '날씨·버스'],
  ['feedback', '후기·신고'],
];

export type RouteDetailSheetProps = {
  open: boolean;
  detailTab: DetailTab;
  selectedItem: ScoredRoute | undefined;
  selectedIndex: number;
  selectedRouteId: string | null;
  profile: ProfileId;
  peers: ScoredRoute[];
  onClose: () => void;
  onDetailTabChange: (tab: DetailTab) => void;
};

function renderDetailContent(
  tab: DetailTab,
  {
    selectedItem,
    selectedIndex,
    selectedRouteId,
    profile,
    peers,
  }: Pick<
    RouteDetailSheetProps,
    'selectedItem' | 'selectedIndex' | 'selectedRouteId' | 'profile' | 'peers'
  >,
): ReactNode {
  if (tab === 'route') {
    return selectedItem ? (
      <RouteDetails
        item={selectedItem}
        rank={selectedIndex + 1}
        profile={profile}
        peers={peers}
      />
    ) : (
      <p>먼저 경로를 검색해 주세요.</p>
    );
  }
  if (tab === 'environment') {
    return (
      <>
        <WeatherWarning />
        <BusArrivalCard />
      </>
    );
  }
  if (tab === 'feedback') {
    return selectedItem ? (
      <FeedbackTabPanel selectedRouteId={selectedRouteId} />
    ) : (
      <p>경로를 선택하면 이용 후기를 남길 수 있습니다.</p>
    );
  }
  return null;
}

export default function RouteDetailSheet({
  open,
  detailTab,
  selectedItem,
  selectedIndex,
  selectedRouteId,
  profile,
  peers,
  onClose,
  onDetailTabChange,
}: RouteDetailSheetProps) {
  if (!open) return null;

  const handleDetailTabKeyDown = (
    event: ReactKeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight') {
      nextIndex = (index + 1) % DETAIL_TABS.length;
    } else if (event.key === 'ArrowLeft') {
      nextIndex = (index - 1 + DETAIL_TABS.length) % DETAIL_TABS.length;
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = DETAIL_TABS.length - 1;
    }
    if (nextIndex === null) return;
    event.preventDefault();
    const nextTab = DETAIL_TABS[nextIndex][0];
    onDetailTabChange(nextTab);
    window.requestAnimationFrame(() => {
      document.getElementById(`detail-tab-${nextTab}`)?.focus();
    });
  };

  return (
    <div className="map-first__detail-sheet">
      <BottomDrawer
        drawerId="details-drawer"
        title="경로 상세 정보"
        onClose={onClose}
        panelClassName="map-first__drawer-panel--details"
      >
        <div className="map-first__details-layout">
          <div className="map-first__tabs" role="tablist" aria-label="상세 정보 종류">
            {DETAIL_TABS.map(([id, label], index) => (
              <button
                key={id}
                id={`detail-tab-${id}`}
                type="button"
                role="tab"
                aria-selected={detailTab === id}
                aria-controls={`detail-panel-${id}`}
                tabIndex={detailTab === id ? 0 : -1}
                className={detailTab === id ? 'map-first__tab--active' : ''}
                onClick={() => onDetailTabChange(id)}
                onKeyDown={(event) => handleDetailTabKeyDown(event, index)}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="map-first__details-panels">
            {DETAIL_TABS.map(([id]) => (
              <div
                key={id}
                id={`detail-panel-${id}`}
                className="map-first__tab-panel"
                role="tabpanel"
                aria-labelledby={`detail-tab-${id}`}
                hidden={detailTab !== id}
              >
                {detailTab === id
                  ? renderDetailContent(id, {
                      selectedItem,
                      selectedIndex,
                      selectedRouteId,
                      profile,
                      peers,
                    })
                  : null}
              </div>
            ))}
          </div>
        </div>
      </BottomDrawer>
    </div>
  );
}
