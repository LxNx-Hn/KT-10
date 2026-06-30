import type { LowFloorStatus } from '@/types';

/** 점수 막대(0~100). 접근성 점수 등 표시용. */
export function ScoreBar({ label, value }: { label: string; value: number }) {
  const tone = value >= 80 ? 'good' : value >= 60 ? 'warn' : 'bad';
  return (
    <div className="scorebar">
      <div className="scorebar__head">
        <span>{label}</span>
        <span className="scorebar__num">{Math.round(value)}</span>
      </div>
      <div className="scorebar__track">
        <div className={`scorebar__fill scorebar__fill--${tone}`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

/** 색상 + 텍스트를 함께 제공하는 상태 배지(기획서 §12). */
export function Badge({
  tone,
  children,
}: {
  tone: 'good' | 'warn' | 'bad' | 'neutral';
  children: React.ReactNode;
}) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

export function lowFloorBadge(status: LowFloorStatus) {
  switch (status) {
    case 'confirmed':
      return <Badge tone="good">저상버스 확인됨</Badge>;
    case 'regular':
      return <Badge tone="bad">일반버스(저상 아님)</Badge>;
    case 'unknown':
      return <Badge tone="warn">저상 여부 미확인</Badge>;
    case 'none':
      return <Badge tone="neutral">버스 미이용</Badge>;
  }
}

/** 날씨 위험도(0~100, 높을수록 위험) → 텍스트+색상 */
export function weatherRiskBadge(risk: number) {
  if (risk >= 40) return <Badge tone="bad">날씨 위험 높음</Badge>;
  if (risk >= 20) return <Badge tone="warn">날씨 위험 보통</Badge>;
  return <Badge tone="good">날씨 위험 낮음</Badge>;
}

export function elevatorBadge(score: number) {
  if (score >= 80) return <Badge tone="good">승강기 양호</Badge>;
  if (score >= 50) return <Badge tone="warn">승강기 미확인</Badge>;
  return <Badge tone="bad">승강기 없음/계단</Badge>;
}
