# Map-first UI v2

## 현재 상태

`feature/frontend-map-first-v2`의 지도 중심 UI/UX를 최신 `main`의
프로덕션 기능과 연결한 현재 프론트 단일 진입점입니다.

- `App.tsx`는 `MapFirstApp`을 렌더링합니다.
- `MapFirstPrototype.tsx`는 예전 import를 깨지 않기 위한 호환 별칭입니다.
- 초기 가짜 경로·고정 좌표·자동 데모 검색은 실행하지 않습니다.
- 기존 `components/MapView.tsx`와 기존 데이터 계약은 삭제하지 않았습니다.

## 파일 역할

| 파일 | 역할 |
| --- | --- |
| `MapFirstApp.tsx` | 장소 검색, 프로필·이동 조건, 추천 카드, 상세 drawer, 음성 진입점 |
| `KakaoMap.tsx` | Kakao 지도, 출·도착 마커, 선택·대안 경로, 건물 그늘 오버레이 |
| `routeViewModel.ts` | 서버 응답을 사실 배지와 점수 설명으로 변환 |
| `map-first.css` | 모바일 우선 지도·바텀시트·drawer 디자인 |
| `MapFirstPrototype.tsx` | `MapFirstApp` 호환 re-export |
| `mapDemoData.ts` | 인계본 시각 참고 데이터; 프로덕션 v2에서는 import하지 않음 |

## 사용자 흐름

1. 출발지·도착지를 Kakao Places에서 검색하고 결과 항목을 선택합니다.
2. `appStore.search`가 백엔드 추천 API를 호출합니다.
3. 서버가 정렬한 `ScoredRoute[]` 순서를 그대로 카드에 표시합니다.
4. 스와이프·점·화살표·키보드 또는 지도 경로를 선택하면 카드와 지도가
   같은 `selectedRouteId`를 사용합니다.
5. 상세 drawer에서 경로 사실, 날씨·버스, 후기·신고, 내 설정을 확인합니다.

장소 이름을 입력만 하고 검색 결과를 선택하지 않은 상태에서는 경로를
요청하지 않습니다. 출발지나 도착지를 수정하면 이전 OD의 경로·선택을
즉시 폐기합니다.

## 사실성 표시 계약

- `unknown`, `null`, 미확인 값을 0·없음·정확함으로 바꾸지 않습니다.
- 경사, 계단, 수직 이동, 건물 그늘은 확인된 데이터만 사실 배지로
  표시하고 나머지는 `미확인` 또는 `정보 없음`으로 표시합니다.
- 내부 점수 종류와 무관하게 화면에는 `프로필 적합 점수`로 표시합니다.
- 적합 점수는 후보 간 비교값이며 안전도·성공확률이 아님을 항상
  명시합니다.
- `route.path` 전체를 기본 경로선으로 유지하고, 확인된 구간별 geometry를
  교통수단 스타일로 덧그립니다.
- 건물 그늘은 `estimated_demo` 또는 `estimated_public`이고 실제 폴리곤이나
  경로 구간이 있을 때만 오버레이 토글을 활성화합니다.

## 프로필과 이동 조건

기본 프로필은 `general`, `elderly`, `child`, `youth`, `disabled`,
`pregnant` 6개입니다. 이번 이동 조건은 짐 많음, 유아차, 계단 회피,
그늘 우선, 저상버스 우선, 환승 최소이며 서버 재채점 옵션으로 전달합니다.

## 데이터와 환경 변수

프론트 도메인 타입은 `frontend/src/types/index.ts`, 어댑터 계약은
`frontend/src/adapters/types.ts`, 추천 상태는
`frontend/src/store/appStore.ts`가 단일 기준입니다.

| 변수 | 설명 |
| --- | --- |
| `VITE_KAKAO_MAP_KEY` | Kakao 지도·브라우저 Places JavaScript 키 |
| `VITE_DATA_SOURCE` | `mock` 또는 `live` |
| `VITE_API_BASE` | live 백엔드 API 기준 URL |

`VITE_DATA_SOURCE=live`이며 JavaScript 키가 있으면 브라우저 Places SDK를
우선 사용합니다. 키가 없을 때만 백엔드 검색을 사용하며, 이 경우 응답의
`X-Place-Search-Source: kakao-rest`가 확인되지 않으면 데모 응답을 실제
검색처럼 표시하지 않고 실패시킵니다. 이 때문에 백엔드 `/api/health`의
REST 장소 공급자가 mock이어도 브라우저 장소 검색은 live일 수 있습니다.
운영 배포 도메인은 Kakao Developers의 JavaScript SDK 허용 도메인에
별도로 등록해야 합니다.

서버 측 장소 검색과 로그인, 실제 날씨, 실제 공공 건물 그늘에는 각각
`KAKAO_REST_API_KEY`, Kakao OAuth 설정, `OPENWEATHER_API_KEY`,
`VWORLD_API_KEY`가 추가로 필요합니다.

## 검증

```powershell
cd frontend
npm test
npm run build
npm run test:e2e:a11y
npm run test:e2e:places
npm audit --audit-level=moderate
```

2026-07-25 현재 통합 작업본에서 Vitest 15개 파일 92개 테스트,
Playwright 접근성 5개 통과·데스크톱 전용 1개 의도적 제외, Kakao Places
live E2E 1개 통과, PWA production build와 npm audit 0건을 확인했습니다.

`test:e2e:places`는 실행 중인 live 백엔드, 유효한 Kakao JavaScript 키,
등록된 `http://localhost:5173` 도메인이 없으면 실패하도록 되어 있습니다.
