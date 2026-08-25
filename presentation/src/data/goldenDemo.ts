export const goldenDemo = {
  meta: {
    verifiedAt: '2026-08-25',
    source: 'dongnet.kr 사전 검증',
  },

  od: {
    origin: '부산대학교 부산캠퍼스',
    destination: '서면역 부산1호선',
  },

  general: {
    profile: '일반',
    routes: [
      {
        id: 'A',
        rank: 1,
        name: '버스 49번 · 지하철 1호선',
        timeMin: 33,
        walkM: 832,
        transfers: 1,
        score: 68,
        slopePct: 3.14,
        shadePct: 20,
      },
      {
        id: 'B',
        rank: 2,
        name: '지하철 1호선',
        timeMin: 34,
        walkM: 1165,
        transfers: 0,
        score: 68,
        shadePct: 21,
      },
      {
        id: 'C',
        rank: 3,
        name: '버스 77번',
        timeMin: 47,
        walkM: 697,
        transfers: 0,
        score: 61,
        slopePct: 2.88,
        shadePct: 10,
      },
    ],
  },

  mobility: {
    profile: '이동지원',
    routes: [
      {
        id: 'C',
        rank: 1,
        name: '버스 77번',
        timeMin: 47,
        walkM: 697,
        transfers: 0,
        score: 59,
        slopePct: 2.88,
        shadePct: 10,
      },
      {
        id: 'D',
        rank: 2,
        name: '버스 29번',
        timeMin: 56,
        walkM: 785,
        transfers: 0,
        score: 59,
        shadePct: 27,
      },
      {
        id: 'A',
        rank: 3,
        name: '버스 49번 · 지하철 1호선',
        timeMin: 33,
        walkM: 832,
        transfers: 1,
        score: 55,
        slopePct: 3.14,
        shadePct: 20,
      },
    ],
  },

  comparison: {
    generalWinner: 'A',
    mobilityWinner: 'C',

    promotedRoute: 'C',
    generalRank: 3,
    mobilityRank: 1,

    timeDeltaMin: 14,
    walkReductionM: 135,
    slopeReductionPp: 0.26,
  },
} as const;
