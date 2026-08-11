export const presentationData = {
  demo: {
    origin: '개금벚꽃길',
    destination: '롯데월드 어드벤처 부산',
  },

  brand: {
    name: 'DONGNET',
    koreanName: '동넷',
    tagline: '누구에게나 같은 길이, 좋은 길일까요?',
  },

  profiles: {
    general: {
      english: 'GENERAL',
      label: '일반',
      description: '빠르고 효율적으로 이동하고 싶어요.',
      criteria: ['소요 시간', '환승', '도보 거리'],
    },

    elderly: {
      english: 'ELDERLY',
      label: '고령자',
      description: '걷는 부담과 경사를 줄이고 싶어요.',
      criteria: ['경사', '계단', '보행 부담'],
    },

    mobility: {
      english: 'MOBILITY SUPPORT',
      label: '이동지원',
      description: '접근 가능한 이동 환경이 중요해요.',
      criteria: ['승강기', '저상버스', '접근성'],
    },
  },
} as const;
