import { useState } from 'react';

function localDateTimeAt(hour: number): string {
  const date = new Date();
  date.setHours(hour, 0, 0, 0);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}T${String(hour).padStart(2, '0')}:00`;
}

function localDateTimeNow(): string {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hour = String(date.getHours()).padStart(2, '0');
  const minute = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

const PRESETS: Array<{ label: string; value: () => string; isNow?: boolean }> = [
  { label: '지금', value: localDateTimeNow, isNow: true },
  { label: '오전 9시', value: () => localDateTimeAt(9) },
  { label: '오후 2시', value: () => localDateTimeAt(14) },
  { label: '오후 6시', value: () => localDateTimeAt(18) },
];

type DepartureTimePickerProps = {
  initialValue?: string;
  initialIsNow?: boolean;
  loading?: boolean;
  onApply: (value: string, isNow: boolean) => void;
  onCancel: () => void;
};

/** 출발 시각 초안만 다루고, 적용 시에만 상위로 확정값을 넘긴다. */
export default function DepartureTimePicker({
  initialValue,
  initialIsNow = true,
  loading = false,
  onApply,
  onCancel,
}: DepartureTimePickerProps) {
  const [draft, setDraft] = useState(initialValue || localDateTimeNow());
  const [draftIsNow, setDraftIsNow] = useState(initialIsNow);

  return (
    <section className="departure-time-picker" aria-label="출발 시간 설정 내용">
      <label className="departure-time-picker__field">
        <span>출발 시각</span>
        <input
          type="datetime-local"
          value={draft}
          disabled={loading}
          onChange={(event) => {
            setDraft(event.target.value);
            setDraftIsNow(false);
          }}
        />
      </label>

      <div
        className="departure-time-picker__presets"
        aria-label="출발 시간 바로 선택"
      >
        {PRESETS.map(({ label, value, isNow }) => (
          <button
            key={label}
            type="button"
            disabled={loading}
            onClick={() => {
              setDraft(value());
              setDraftIsNow(Boolean(isNow));
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <p className="departure-time-picker__hint">
        선택한 시간의 태양 위치를 기준으로 건물 그늘을 다시 계산해요.
      </p>

      <div className="departure-time-picker__actions">
        <button
          type="button"
          className="departure-time-picker__cancel"
          onClick={onCancel}
          disabled={loading}
        >
          취소
        </button>
        <button
          type="button"
          className="departure-time-picker__apply"
          disabled={loading || !draft}
          onClick={() => onApply(draft, draftIsNow)}
        >
          적용
        </button>
      </div>
    </section>
  );
}

/** 결과 시트 출발 시간 버튼에 쓰는 짧은 한국어 표시. */
export function formatDepartureButtonLabel(
  departureAt: string | undefined,
  isNow: boolean,
): string {
  if (!departureAt || isNow) return '지금 출발';
  const date = new Date(departureAt);
  if (Number.isNaN(date.getTime())) return '지금 출발';
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const period = hours < 12 ? '오전' : '오후';
  const hour12 = hours % 12 === 0 ? 12 : hours % 12;
  const mm = String(minutes).padStart(2, '0');
  return `출발 ${period} ${hour12}:${mm}`;
}
