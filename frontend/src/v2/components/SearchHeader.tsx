import type { RefObject } from 'react';
import type { Place } from '@/types';
import type { ToggleableScoringOption } from '@/store/appStore';
import RouteSearchPanel, { SEARCH_PANEL_ID } from './RouteSearchPanel';

export type SearchHeaderMode = 'collapsed' | 'expanded' | 'summary';

type QuickCondition = {
  key: ToggleableScoringOption;
  label: string;
};

export type SearchHeaderProps = {
  mode: SearchHeaderMode;
  origin: Place | null;
  destination: Place | null;
  originInputRef?: RefObject<HTMLInputElement>;
  destinationInputRef?: RefObject<HTMLInputElement>;
  loading: boolean;
  searchHint: string | null;
  error: string | null;
  profileLabel: string;
  profileDrawerOpen: boolean;
  settingsDrawerOpen: boolean;
  situationConditions: QuickCondition[];
  routeOptionConditions: QuickCondition[];
  optionState: Partial<Record<ToggleableScoringOption, boolean | undefined>>;
  largeUi: boolean;
  activeConditionCount: number;
  summaryConditionCount: number;
  conditionsDrawerOpen: boolean;
  onExpand: () => void;
  onCollapse: () => void;
  onSelectOrigin: (place: Place) => void;
  onClearOrigin: () => void;
  onSelectDestination: (place: Place) => void;
  onClearDestination: () => void;
  onSwap: () => void;
  onSearch: () => void;
  onEditSearch: () => void;
  onOpenProfile: () => void;
  onOpenSettings: () => void;
  onToggleOption: (key: ToggleableScoringOption, enabled: boolean) => void;
  onToggleLargeUi: () => void;
  onOpenConditions: () => void;
};

function SearchIcon() {
  return (
    <svg
      className="map-first__search-collapsed-icon"
      viewBox="0 0 24 24"
      width="22"
      height="22"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      aria-hidden="true"
    >
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
    </svg>
  );
}

/**
 * 검색 헤더: collapsed 한 줄 / expanded 전체 패널 / summary OD 요약.
 * 검색 로직·store는 MapFirstApp에서 props로만 받는다.
 */
export default function SearchHeader({
  mode,
  onExpand,
  onCollapse,
  ...panelProps
}: SearchHeaderProps) {
  // KakaoMap overlay padding은 `.map-first__top` 실측을 사용한다.
  const panelModeAttr = mode === 'summary' ? 'compact' : mode;

  return (
    <div
      className="map-first__search-header map-first__top"
      data-search-header={mode}
      data-search-panel={panelModeAttr}
    >
      {mode === 'collapsed' ? (
        <button
          type="button"
          className="map-first__search-collapsed"
          aria-expanded={false}
          aria-controls={SEARCH_PANEL_ID}
          aria-label="어디로 갈까요?"
          onClick={onExpand}
        >
          <SearchIcon />
          <span className="map-first__search-collapsed-copy">
            <span className="map-first__search-collapsed-title">
              어디로 갈까요?
            </span>
            <span className="map-first__search-collapsed-hint">
              목적지를 검색해 보세요
            </span>
          </span>
        </button>
      ) : (
        <div
          id={SEARCH_PANEL_ID}
          className="map-first__search-header-body"
        >
          <RouteSearchPanel
            {...panelProps}
            mode={mode === 'summary' ? 'compact' : 'expanded'}
            onCollapse={mode === 'expanded' ? onCollapse : undefined}
          />
        </div>
      )}
    </div>
  );
}
