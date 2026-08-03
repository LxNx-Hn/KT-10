import {
  useEffect,
  useRef,
  useState,
  type CompositionEvent as ReactCompositionEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
} from 'react';
import { adapters } from '@/adapters';
import { toUserMessage } from '@/api/http';
import type { Place } from '@/types';

function placeSubtitle(place: Place): string {
  return [place.category, place.address]
    .filter((part): part is string => Boolean(part?.trim()))
    .join(' · ');
}

type PlaceComboboxProps = {
  fieldId: string;
  label: string;
  place: Place | null;
  onSelectPlace: (place: Place) => void;
  onClearPlace: () => void;
  inputRef?: RefObject<HTMLInputElement>;
  onSelected?: () => void;
};

/**
 * 카카오 장소 검색 어댑터를 사용하는 접근 가능한 자동완성 입력.
 * 입력 문자열과 실제로 선택된 Place를 분리해 좌표 없는 검색을 보내지 않는다.
 */
export default function PlaceCombobox({
  fieldId,
  label,
  place,
  onSelectPlace,
  onClearPlace,
  inputRef,
  onSelected,
}: PlaceComboboxProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const localInputRef = useRef<HTMLInputElement | null>(null);
  const timeoutRef = useRef<number>();
  const focusTransferTimeoutRef = useRef<number>();
  const requestIdRef = useRef(0);
  const mountedRef = useRef(true);
  const locallyClearingSelectionRef = useRef(false);
  /** 한글 IME 조합 중 여부 (event.isComposing과 함께 사용) */
  const composingRef = useRef(false);
  /** compositionstart를 발생시킨 이 콤보박스 fieldId */
  const compositionOwnerFieldIdRef = useRef<string | null>(null);
  /** 조합이 끝난 뒤에만 다음 필드로 포커스를 옮기기 위한 대기 플래그 */
  const pendingFocusAfterCompositionRef = useRef(false);
  const selectedNameRef = useRef<string | null>(place?.name ?? null);
  const [text, setText] = useState(place?.name ?? '');
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [searching, setSearching] = useState(false);
  const [empty, setEmpty] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const listboxId = `${fieldId}-listbox`;

  const assignInputRef = (node: HTMLInputElement | null) => {
    localInputRef.current = node;
    if (inputRef) {
      (inputRef as { current: HTMLInputElement | null }).current = node;
    }
  };

  const isImeKeyEvent = (event: ReactKeyboardEvent<HTMLInputElement>): boolean => (
    composingRef.current
    || event.nativeEvent.isComposing
    || event.keyCode === 229
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
      pendingFocusAfterCompositionRef.current = false;
      window.clearTimeout(timeoutRef.current);
      window.clearTimeout(focusTransferTimeoutRef.current);
    };
  }, []);

  useEffect(() => {
    if (locallyClearingSelectionRef.current && place === null) {
      locallyClearingSelectionRef.current = false;
      return;
    }
    requestIdRef.current += 1;
    window.clearTimeout(timeoutRef.current);
    selectedNameRef.current = place?.name ?? null;
    setText(place?.name ?? '');
    setResults([]);
    setOpen(false);
    setActiveIndex(-1);
    setSearching(false);
    setEmpty(false);
    setLocalError(null);
  }, [place]);

  useEffect(() => {
    const closeFromOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setActiveIndex(-1);
      }
    };
    document.addEventListener('pointerdown', closeFromOutside);
    return () => document.removeEventListener('pointerdown', closeFromOutside);
  }, []);

  const closeList = () => {
    setOpen(false);
    setActiveIndex(-1);
  };

  const focusNextField = () => {
    if (!onSelected || !mountedRef.current) return;
    window.clearTimeout(focusTransferTimeoutRef.current);
    focusTransferTimeoutRef.current = window.setTimeout(() => {
      if (!mountedRef.current) return;
      onSelected();
    }, 0);
  };

  /**
   * 선택 후 포커스 이동: 현재 입력창을 먼저 blur하고,
   * IME 조합이 남아 있으면 compositionend 이후에만 다음 필드로 옮긴다.
   */
  const notifySelectedAfterImeSafe = () => {
    if (!onSelected) return;
    localInputRef.current?.blur();

    if (composingRef.current || compositionOwnerFieldIdRef.current === fieldId) {
      pendingFocusAfterCompositionRef.current = true;
      // compositionend가 오지 않는 환경 대비 짧은 폴백 (강제 삭제가 아님)
      window.clearTimeout(focusTransferTimeoutRef.current);
      focusTransferTimeoutRef.current = window.setTimeout(() => {
        if (!mountedRef.current || !pendingFocusAfterCompositionRef.current) return;
        pendingFocusAfterCompositionRef.current = false;
        composingRef.current = false;
        compositionOwnerFieldIdRef.current = null;
        focusNextField();
      }, 50);
      return;
    }

    focusNextField();
  };

  const applyPlace = (next: Place) => {
    requestIdRef.current += 1;
    window.clearTimeout(timeoutRef.current);
    selectedNameRef.current = next.name;
    onSelectPlace(next);
    setText(next.name);
    setResults([]);
    setSearching(false);
    setEmpty(false);
    setLocalError(null);
    closeList();
    notifySelectedAfterImeSafe();
  };

  const searchPlaces = async (query: string, requestId: number) => {
    setSearching(true);
    setLocalError(null);
    try {
      const found = await adapters.places.searchPlaces(query);
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setResults(found);
      setEmpty(found.length === 0);
      setActiveIndex(found.length > 0 ? 0 : -1);
      setOpen(true);
    } catch (error) {
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setResults([]);
      setEmpty(false);
      setActiveIndex(-1);
      setLocalError(toUserMessage(error, '장소 검색에 실패했습니다.'));
      setOpen(true);
    } finally {
      if (mountedRef.current && requestId === requestIdRef.current) {
        setSearching(false);
      }
    }
  };

  const onChange = (value: string, source: EventTarget | null) => {
    // 이 콤보박스 input에서 온 이벤트만 반영한다 (공유 query/activeField 없음).
    if (source && source !== localInputRef.current) return;

    const selectedName = selectedNameRef.current;
    if (selectedName !== null && value === selectedName) {
      setText(value);
      return;
    }

    const requestId = ++requestIdRef.current;
    window.clearTimeout(timeoutRef.current);
    selectedNameRef.current = null;
    setText(value);
    setSearching(false);
    setLocalError(null);
    setResults([]);
    setActiveIndex(-1);

    if (place && value !== place.name) {
      locallyClearingSelectionRef.current = true;
      onClearPlace();
    }

    const query = value.trim();
    if (query.length < 2) {
      setOpen(false);
      setEmpty(false);
      return;
    }

    setEmpty(false);
    timeoutRef.current = window.setTimeout(() => {
      void searchPlaces(query, requestId);
    }, 200);
  };

  const onCompositionStart = (event: ReactCompositionEvent<HTMLInputElement>) => {
    composingRef.current = true;
    // 조합을 시작한 입력창을 기록한다.
    compositionOwnerFieldIdRef.current = fieldId;
    void event.currentTarget;
  };

  const onCompositionEnd = (event: ReactCompositionEvent<HTMLInputElement>) => {
    const ownerFieldId = compositionOwnerFieldIdRef.current;
    composingRef.current = false;

    // 최종 입력값은 조합을 시작한 원래 입력창에만 반영한다.
    if (ownerFieldId !== null && ownerFieldId !== fieldId) {
      return;
    }
    if (event.currentTarget !== localInputRef.current) {
      return;
    }

    compositionOwnerFieldIdRef.current = null;
    const value = event.currentTarget.value;

    // 이미 장소를 확정한 뒤에는 IME 잔여 값으로 선택/검색어를 덮지 않는다.
    if (selectedNameRef.current !== null) {
      setText(selectedNameRef.current);
    } else {
      onChange(value, event.currentTarget);
    }

    if (pendingFocusAfterCompositionRef.current) {
      pendingFocusAfterCompositionRef.current = false;
      window.clearTimeout(focusTransferTimeoutRef.current);
      focusNextField();
    }
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    // 한글 조합 중 Enter는 결과 확정·필드 전환으로 쓰지 않는다.
    if (isImeKeyEvent(event)) {
      return;
    }

    if (event.key === 'Escape') {
      if (open) event.preventDefault();
      closeList();
      return;
    }
    if (!open || results.length === 0) return;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((index) => (index + 1) % results.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((index) => (index <= 0 ? results.length - 1 : index - 1));
    } else if (event.key === 'Enter' && activeIndex >= 0) {
      event.preventDefault();
      applyPlace(results[activeIndex]);
    }
  };

  const showList =
    open && (searching || results.length > 0 || empty || localError !== null);

  return (
    <div className="map-first__combobox" ref={rootRef}>
      <div className="map-first__search-row">
        <span
          className={`map-first__search-dot map-first__search-dot--${
            fieldId.includes('origin') ? 'origin' : 'dest'
          }`}
          aria-hidden="true"
        />
        <label className="map-first__sr-only" htmlFor={fieldId}>
          {label}
        </label>
        <input
          ref={assignInputRef}
          id={fieldId}
          className="map-first__search-input"
          type="search"
          role="combobox"
          value={text}
          placeholder={`${label} 검색`}
          onChange={(event) => onChange(event.target.value, event.target)}
          onCompositionStart={onCompositionStart}
          onCompositionEnd={onCompositionEnd}
          onKeyDown={onKeyDown}
          onFocus={() => {
            if (results.length > 0 || empty || localError) setOpen(true);
          }}
          aria-label={label}
          aria-expanded={showList}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-busy={searching}
          aria-activedescendant={
            activeIndex >= 0 ? `${fieldId}-option-${activeIndex}` : undefined
          }
          autoComplete="off"
        />
      </div>

      {showList && (
        <div
          className="map-first__suggest"
          id={listboxId}
          role="listbox"
          aria-label={`${label} 검색 결과`}
        >
          {searching && (
            <p className="map-first__suggest-status" role="status">
              카카오 장소를 검색하는 중…
            </p>
          )}
          {localError && (
            <p className="map-first__suggest-status" role="alert">
              {localError}
            </p>
          )}
          {!searching && !localError && empty && (
            <p className="map-first__suggest-status" role="status">
              검색 결과가 없습니다. 다른 장소명이나 주소를 입력해 주세요.
            </p>
          )}
          {!searching &&
            results.map((item, index) => {
              const subtitle = placeSubtitle(item);
              const active = index === activeIndex;
              return (
                <button
                  key={`${item.id}-${index}`}
                  id={`${fieldId}-option-${index}`}
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={`map-first__suggest-option${
                    active ? ' map-first__suggest-option--active' : ''
                  }`}
                  onPointerDown={(event) => event.preventDefault()}
                  onPointerEnter={() => setActiveIndex(index)}
                  onClick={() => applyPlace(item)}
                >
                  <span className="map-first__suggest-name">{item.name}</span>
                  {subtitle && (
                    <span className="map-first__suggest-sub">{subtitle}</span>
                  )}
                </button>
              );
            })}
        </div>
      )}
    </div>
  );
}
