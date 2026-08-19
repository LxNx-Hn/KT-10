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
      note: '휠체어 이동 조건 포함',
    },
  },

  apiRoles: {
    odsay: {
      name: 'ODsay',
      role: '대중교통 후보',
    },
    tmap: {
      name: 'TMAP',
      role: '도보 · 일반 이동 후보',
    },
    ors: {
      name: 'ORS',
      role: '이동지원 후보 보완',
      note: 'wheelchair profile 지원',
    },
  },

  scoringPipeline:
    'ODsay·TMAP·ORS 후보 경로 수집 → 공공데이터·실시간 데이터 결합 → 이동·접근성·환경 피처 생성 → 프로필별 0–100점 계산 → AI Ranker 재정렬 → 추천 이유 제공',

  scoringPrinciple:
    'API가 제공한 후보 경로와 이동 데이터를 바탕으로 DongNet이 사용자별 경로 점수를 계산합니다.',

  evaluationStandard: 'KT 믿음 K 2.0 기반 프로필 평가 기준',
} as const;
