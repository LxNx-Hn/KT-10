import { useEffect, useRef, useState } from 'react';
import { useAppStore } from '@/store/appStore';
import { adapters } from '@/adapters';
import type { Place } from '@/types';
import { toUserMessage } from '@/api/http';

/** 장소 검색 입력 + 자동완성 드롭다운 */
function PlaceInput({
  label,
  value,
  onSelect,
}: {
  label: string;
  value: Place | null;
  onSelect: (p: Place) => void;
}) {
  const [text, setText] = useState(value?.name ?? '');
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [searchError, setSearchError] = useState('');
  const timer = useRef<number | undefined>(undefined);
  const requestId = useRef(0);

  useEffect(() => {
    setText(value?.name ?? '');
  }, [value]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const onChange = (q: string) => {
    setText(q);
    setSearchError('');
    window.clearTimeout(timer.current);
    const currentRequest = ++requestId.current;
    if (q.trim().length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }
    timer.current = window.setTimeout(async () => {
      try {
        const r = await adapters.places.searchPlaces(q.trim());
        if (currentRequest !== requestId.current) return;
        setResults(r);
        setOpen(r.length > 0);
        setSearchError(r.length ? '' : '검색 결과가 없습니다.');
      } catch (error) {
        if (currentRequest !== requestId.current) return;
        setResults([]);
        setOpen(false);
        setSearchError(toUserMessage(error, '장소를 검색하지 못했습니다.'));
      }
    }, 200);
  };

  return (
    <div className="place-input">
      <label className="place-input__label">{label}</label>
      <input
        className="place-input__field"
        type="text"
        value={text}
        placeholder="장소 이름 입력 (예: 서면역)"
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
        aria-label={label}
        aria-describedby={searchError ? `${label}-search-status` : undefined}
        autoComplete="off"
      />
      {searchError && (
        <span className="place-input__status" id={`${label}-search-status`} role="status">
          {searchError}
        </span>
      )}
      {open && (
        <ul className="place-input__list" role="listbox">
          {results.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className="place-input__option"
                onClick={() => {
                  onSelect(p);
                  setText(p.name);
                  setOpen(false);
                }}
              >
                <strong>{p.name}</strong>
                <span>{p.category ?? ''} · {p.address ?? ''}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function SearchBar() {
  const { origin, destination, setOrigin, setDestination, search, loadDemoOd, loading } =
    useAppStore();
  const useCurrentLocation = useAppStore((s) => s.useCurrentLocation);
  const isDemo = import.meta.env.VITE_DATA_SOURCE !== 'live';

  return (
    <section className="searchbar" aria-label="출발지 도착지 검색">
      <PlaceInput label="출발지" value={origin} onSelect={setOrigin} />
      <button
        type="button"
        className="searchbar__swap"
        aria-label="출발지와 도착지 바꾸기"
        onClick={() => {
          setOrigin(destination);
          setDestination(origin);
        }}
      >
        ⇅
      </button>
      <PlaceInput label="도착지" value={destination} onSelect={setDestination} />

      <div className="searchbar__actions">
        <button type="button" className="btn btn--ghost" onClick={useCurrentLocation}>
          📍 현재 위치 사용
        </button>
        {isDemo && (
          <button type="button" className="btn btn--ghost" onClick={loadDemoOd}>
            데모 경로 채우기
          </button>
        )}
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => void search()}
          disabled={loading}
        >
          {loading ? '경로 찾는 중…' : '경로 찾기'}
        </button>
      </div>
    </section>
  );
}
