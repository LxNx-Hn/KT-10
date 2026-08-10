import type { RefObject } from 'react';
import type { Place } from '@/types';
import type { ToggleableScoringOption } from '@/store/appStore';
import PlaceCombobox from './PlaceCombobox';

export type SearchPanelMode = 'expanded' | 'compact';

/** SearchHeader collapsed/summary 트리거와 expanded 패널을 연결한다. */
export const SEARCH_PANEL_ID = 'map-first-search-panel';

type QuickCondition = {
  key: ToggleableScoringOption;
  label: string;
};

type RouteSearchPanelProps = {
  mode: SearchPanelMode;
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
  onCollapse?: () => void;
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

function SwapIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <path
        d="M7 7h11M7 7l3-3M7 7l3 3M17 17H6M17 17l-3-3M17 17l-3 3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="3" />
      <path
        d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ChipCheck({ active }: { active: boolean }) {
  return (
    <span
      className={`map-first__chip-check${active ? '' : ' map-first__chip-check--idle'}`}
      aria-hidden="true"
    >
      ✓
    </span>
  );
}

export default function RouteSearchPanel({
  mode,
  origin,
  destination,
  originInputRef,
  destinationInputRef,
  loading,
  searchHint,
  error,
  profileLabel,
  profileDrawerOpen,
  settingsDrawerOpen,
  situationConditions,
  routeOptionConditions,
  optionState,
  largeUi,
  activeConditionCount,
  summaryConditionCount,
  conditionsDrawerOpen,
  onCollapse,
  onSelectOrigin,
  onClearOrigin,
  onSelectDestination,
  onClearDestination,
  onSwap,
  onSearch,
  onEditSearch,
  onOpenProfile,
  onOpenSettings,
  onToggleOption,
  onToggleLargeUi,
  onOpenConditions,
}: RouteSearchPanelProps) {
  const compact = mode === 'compact';
  const summaryLabel = `${origin?.name ?? '출발지'}에서 ${
    destination?.name ?? '도착지'
  }까지, 검색 조건 수정`;

  return (
    <>
      {compact ? (
        <div className="map-first__search map-first__search--compact">
          <button
            type="button"
            className="map-first__search-summary"
            aria-expanded={false}
            aria-controls={SEARCH_PANEL_ID}
            aria-label={summaryLabel}
            onClick={onEditSearch}
          >
            <span className="map-first__summary-od">
              <span
                className="map-first__summary-place map-first__summary-place--origin"
                title={origin?.name ?? '출발지'}
              >
                {origin?.name ?? '출발지'}
              </span>
              <span className="map-first__summary-arrow" aria-hidden="true">
                →
              </span>
              <span
                className="map-first__summary-place map-first__summary-place--destination"
                title={destination?.name ?? '도착지'}
              >
                {destination?.name ?? '도착지'}
              </span>
            </span>
            <span className="map-first__summary-actions">
              {summaryConditionCount > 0 && (
                <span className="map-first__summary-conditions">
                  조건 {summaryConditionCount}개
                </span>
              )}
              <span className="map-first__search-edit">검색 조건 수정</span>
            </span>
          </button>
        </div>
      ) : (
        <div className="map-first__search">
          {onCollapse && (
            <div className="map-first__search-toolbar">
              <button
                type="button"
                className="map-first__search-collapse"
                aria-label="검색창 접기"
                aria-expanded={true}
                aria-controls={SEARCH_PANEL_ID}
                onClick={onCollapse}
              >
                <span aria-hidden="true">⌃</span>
                <span className="map-first__search-collapse-label">
                  검색창 접기
                </span>
              </button>
            </div>
          )}
          <div className="map-first__search-body">
            <PlaceCombobox
              fieldId="map-first-origin"
              label="출발지"
              place={origin}
              onSelectPlace={onSelectOrigin}
              onClearPlace={onClearOrigin}
              inputRef={originInputRef}
              onSelected={() => destinationInputRef?.current?.focus()}
            />
            <div className="map-first__search-divider" />
            <PlaceCombobox
              fieldId="map-first-destination"
              label="도착지"
              place={destination}
              onSelectPlace={onSelectDestination}
              onClearPlace={onClearDestination}
              inputRef={destinationInputRef}
            />
            <button
              type="button"
              className="map-first__search-swap"
              aria-label="출발지와 도착지 바꾸기"
              onClick={onSwap}
            >
              <SwapIcon />
            </button>
          </div>

          <button
            type="button"
            className="map-first__search-submit"
            onClick={onSearch}
            disabled={
              loading
              || !origin
              || !destination
              || origin.id === destination.id
            }
            aria-label="경로 찾기"
          >
            {loading ? '경로 찾는 중…' : '경로 찾기'}
          </button>

          {(searchHint || error) && (
            <p
              className={`map-first__search-message${
                error ? ' map-first__search-message--error' : ''
              }`}
              role={error ? 'alert' : 'status'}
            >
              {searchHint ?? error}
            </p>
          )}
        </div>
      )}

      <div
        className="map-first__account-row"
        role="group"
        aria-label="프로필과 설정"
      >
        <button
          type="button"
          className="map-first__profile"
          aria-haspopup="dialog"
          aria-expanded={profileDrawerOpen}
          aria-label={`프로필 선택, 현재 ${profileLabel}`}
          onClick={onOpenProfile}
        >
          <span className="map-first__profile-label">{profileLabel}</span>
          <span className="map-first__profile-chevron" aria-hidden="true">
            ▾
          </span>
        </button>
        <button
          type="button"
          className="map-first__settings-entry"
          aria-haspopup="dialog"
          aria-expanded={settingsDrawerOpen}
          aria-label="내 설정"
          onClick={onOpenSettings}
        >
          <SettingsIcon />
          <span className="map-first__settings-entry-label">내 설정</span>
        </button>
      </div>

      {!compact && (
        <div className="map-first__context">
          <div className="map-first__context-bar">
            <div
              className="map-first__chip-scroll"
              role="group"
              aria-label="이동 조건"
            >
              {situationConditions.map(({ key, label }) => {
                const active = Boolean(optionState[key]);
                return (
                  <button
                    key={key}
                    type="button"
                    className={`map-first__chip${
                      active ? ' map-first__chip--active' : ''
                    }`}
                    aria-pressed={active}
                    onClick={() => onToggleOption(key, !active)}
                  >
                    <ChipCheck active={active} />
                    <span className="map-first__chip-text">{label}</span>
                  </button>
                );
              })}
              <button
                type="button"
                className={`map-first__chip map-first__chip--easy${
                  largeUi ? ' map-first__chip--active' : ''
                }`}
                aria-label="쉬운 화면"
                aria-pressed={largeUi}
                onClick={onToggleLargeUi}
              >
                <ChipCheck active={largeUi} />
                <span className="map-first__chip-text">쉬운 화면</span>
              </button>
              {routeOptionConditions.map(({ key, label }) => {
                const active = Boolean(optionState[key]);
                return (
                  <button
                    key={key}
                    type="button"
                    className={`map-first__chip${
                      active ? ' map-first__chip--active' : ''
                    }`}
                    aria-pressed={active}
                    onClick={() => onToggleOption(key, !active)}
                  >
                    <ChipCheck active={active} />
                    <span className="map-first__chip-text">{label}</span>
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              className="map-first__chip map-first__chip--conditions"
              aria-haspopup="dialog"
              aria-expanded={conditionsDrawerOpen}
              aria-label={
                activeConditionCount > 0
                  ? `조건, 활성 ${activeConditionCount}개`
                  : '조건'
              }
              onClick={onOpenConditions}
            >
              <span className="map-first__chip-label">조건</span>
              <span
                className={`map-first__condition-count${
                  activeConditionCount > 0
                    ? ''
                    : ' map-first__condition-count--empty'
                }`}
                aria-hidden="true"
              >
                {activeConditionCount > 0 ? activeConditionCount : 0}
              </span>
            </button>
          </div>
        </div>
      )}

      {!compact && largeUi && (
        <p className="map-first__easy-hint" role="status">
          큰 글씨와 큰 버튼을 사용해요
        </p>
      )}
    </>
  );
}
