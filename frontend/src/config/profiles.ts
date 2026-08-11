import type { ProfileId, ProfileMeta } from '@/types';

/** 프로필 메타데이터. 세부 장애 유형이 아닌 "이동 특성" 중심. */
export const PROFILES: Record<ProfileId, ProfileMeta> = {
  general: {
    id: 'general',
    label: '일반',
    description: '특별한 이동 제약이 없어요. 빠른 길·보행 부담·날씨를 균형 있게.',
    keywords: ['빠른 이동', '균형 고려'],
    prefersLargeUi: false,
  },
  elderly: {
    id: 'elderly',
    label: '고령자',
    description: '계단·긴 도보·혼잡·대기에 취약해요. 승강기·짧은 도보 우선.',
    keywords: ['계단 회피', '짧은 도보'],
    prefersLargeUi: true,
  },
  child: {
    id: 'child',
    label: '아동',
    description: '안전한 횡단과 단순한 환승을 우선해요.',
    keywords: ['안전 횡단', '단순 환승'],
    prefersLargeUi: true,
  },
  youth: {
    id: 'youth',
    label: '청소년',
    description: '빠른 이동과 단순한 환승을 중심으로 안전성을 함께 봐요.',
    keywords: ['빠른 이동', '단순 환승'],
    prefersLargeUi: false,
  },
  disabled: {
    id: 'disabled',
    label: '장애인',
    description: '계단 회피·승강기·저상버스·접근성 정보를 강하게 반영해요.',
    keywords: ['계단 회피', '승강기·저상버스'],
    prefersLargeUi: false,
  },
  pregnant: {
    id: 'pregnant',
    label: '임산부',
    description: '긴 도보·급경사·계단·복잡한 환승의 부담을 줄여요.',
    keywords: ['짧은 도보', '급경사 회피'],
    prefersLargeUi: false,
  },
};

export const PROFILE_LIST: ProfileMeta[] = Object.values(PROFILES);
