import type { LowFloorStatus } from '@/types';

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
      return <Badge tone="good">저상버스</Badge>;
    case 'regular':
      return <Badge tone="bad">일반버스(저상 아님)</Badge>;
    case 'unknown':
    case 'none':
      return null;
  }
}
