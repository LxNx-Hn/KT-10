export const goldenDemo = {
  meta: {
    verifiedAt: '2026-08-11',
    source: 'dongnet.kr 사전 검증',
  },

  od: {
    origin: '개금벚꽃길',
    destination: '롯데월드 어드벤처 부산',
  },

  general: {
    profile: '일반',
    routes: [
      {
        id: 'A',
        rank: 1,
        name: '도보 + 168 + 도시철도',
        timeMin: 69,
        walkM: 1252,
        transfers: 1,
        score: 55,
        slopePct: 6.82,
        shadePct: 5,
      },
      {
        id: 'B',
        rank: 2,
        name: '도보 + 31 + 도시철도',
        timeMin: 71,
        walkM: 1154,
        transfers: 1,
        score: 55,
        slopePct: 7.92,
        shadePct: 7,
      },
      {
        id: 'C',
        rank: 3,
        name: '도보 + 도시철도 + 1001',
        timeMin: 77,
        walkM: 1068,
        transfers: 1,
        score: 51,
        slopePct: 6.55,
        shadePct: 12,
      },
    ],
  },

  elderly: {
    profile: '고령자',
    routes: [
      {
        id: 'C',
        rank: 1,
        name: '도보 + 도시철도 + 1001',
        timeMin: 77,
        walkM: 1068,
        transfers: 1,
        score: 36,
        slopePct: 6.55,
        shadePct: 12,
      },
      {
        id: 'B',
        rank: 2,
        name: '도보 + 31 + 도시철도',
        timeMin: 71,
        walkM: 1154,
        transfers: 1,
        score: 35,
        slopePct: 7.92,
        shadePct: 7,
      },
    ],
  },

  comparison: {
    generalWinner: 'A',
    elderlyWinner: 'C',

    promotedRoute: 'C',
    generalRank: 3,
    elderlyRank: 1,

    timeDeltaMin: 8,
    walkReductionM: 184,
    slopeReductionPp: 0.27,
    shadeIncreasePp: 7,
  },
} as const;
