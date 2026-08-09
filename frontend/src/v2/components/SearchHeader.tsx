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
  showMobileHome?: boolean;
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
  showMobileHome = false,
  onExpand,
  onCollapse,
  ...panelProps
}: SearchHeaderProps) {
  // KakaoMap overlay padding은 `.map-first__top` 실측을 사용한다.
  const panelModeAttr = mode === 'summary' ? 'compact' : mode;
  const activeQuickConditions = [
    ...panelProps.situationConditions,
    ...panelProps.routeOptionConditions,
  ]
    .filter(({ key }) => Boolean(panelProps.optionState[key]))
    .map(({ label }) => label);
  const visibleConditionLabels = activeQuickConditions.slice(0, 2);
  let representedConditionCount = visibleConditionLabels.length;
  if (
    visibleConditionLabels.length < 2
    && panelProps.activeConditionCount > 0
  ) {
    visibleConditionLabels.push(`세부 조건 ${panelProps.activeConditionCount}개`);
    representedConditionCount += panelProps.activeConditionCount;
  }
  const totalConditionCount =
    activeQuickConditions.length + panelProps.activeConditionCount;
  const extraConditionCount = Math.max(
    0,
    totalConditionCount - representedConditionCount,
  );
  const conditionSummaryLabels = [
    ...activeQuickConditions,
    ...(panelProps.activeConditionCount > 0
      ? [`세부 조건 ${panelProps.activeConditionCount}개`]
      : []),
  ];
  const conditionSummary = conditionSummaryLabels.length > 0
    ? conditionSummaryLabels.join(', ')
    : '이동 조건 없음';

  return (
    <div
      className="map-first__search-header map-first__top"
      data-search-header={mode}
      data-search-panel={panelModeAttr}
      data-mobile-home={showMobileHome ? 'true' : undefined}
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

      {showMobileHome && mode !== 'expanded' && (
        <div
          className="map-first__mobile-home-summary"
          role="group"
          aria-label="현재 이동 설정"
        >
          <button
            type="button"
            className="map-first__mobile-home-profile"
            aria-label={`현재 프로필 ${panelProps.profileLabel}, 내 설정에서 변경`}
            onClick={panelProps.onOpenSettings}
          >
            <span className="map-first__mobile-home-kicker">현재 프로필</span>
            <strong>{panelProps.profileLabel}</strong>
          </button>
          <button
            type="button"
            className="map-first__mobile-home-conditions"
            aria-label={`현재 이동 조건: ${conditionSummary}, 내 설정에서 변경`}
            onClick={panelProps.onOpenSettings}
          >
            {visibleConditionLabels.length > 0 ? (
              <span className="map-first__mobile-home-condition-list">
                {visibleConditionLabels.map((label) => (
                  <span key={label} className="map-first__mobile-home-condition">
                    {label}
                  </span>
                ))}
                {extraConditionCount > 0 && (
                  <span className="map-first__mobile-home-condition map-first__mobile-home-condition--more">
                    +{extraConditionCount}
                  </span>
                )}
              </span>
            ) : (
              <span className="map-first__mobile-home-empty">이동 조건 없음</span>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
