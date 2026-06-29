import type { ProfileId, ProfileMeta } from '@/types';

/** 프로필 메타데이터. 세부 장애 유형이 아닌 "이동 특성" 중심. */
export const PROFILES: Record<ProfileId, ProfileMeta> = {
  general: {
    id: 'general',
    label: '일반',
    description: '특별한 이동 제약이 없어요. 빠른 길·보행 부담·날씨를 균형 있게.',
    prefersLargeUi: false,
  },
  elderly: {
    id: 'elderly',
    label: '고령자',
    description: '계단·긴 도보·혼잡·대기에 취약해요. 승강기·짧은 도보 우선.',
    prefersLargeUi: true,
  },
  child: {
    id: 'child',
    label: '아동',
    description: '안전한 횡단·사고위험 회피·복잡한 환승 회피를 우선해요.',
    prefersLargeUi: true,
  },
  disabled: {
    id: 'disabled',
    label: '장애인',
    description: '계단 회피·승강기·저상버스·접근성 정보를 강하게 반영해요.',
    prefersLargeUi: false,
  },
};

export const PROFILE_LIST: ProfileMeta[] = Object.values(PROFILES);
