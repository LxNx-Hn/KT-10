# Map-first UI v2 프론트엔드 인계

## 1. 상태

- 최신 main 기반의 독립 UI 프로토타입입니다.
- 현재 `App.tsx`에는 연결하지 않습니다.
- 기존 프론트 동작을 교체하지 않습니다.
- 통합 담당자가 필요한 UI만 선별 적용하기 위한 인계 코드입니다.

## 2. 파일 구성

| 파일 | 역할 |
|------|------|
| `MapFirstPrototype.tsx` | 지도 중심 검색, 프로필 패널, 추천 경로, 바텀시트 UI |
| `KakaoMap.tsx` | 카카오맵, 경로선, 시설 마커, 현재 위치 표시 |
| `mapDemoData.ts` | 화면 시연용 좌표와 시설 데이터 |
| `map-first.css` | v2 전용 스타일 |
| `README.md` | 통합 및 데이터 계약 설명 |

## 3. 기존 main에서 재사용하는 단일 기준

- `frontend/src/types/index.ts` — `ProfileId`, `Place`, `RouteCandidate`, `ScoredRoute` 등 도메인 타입
- `frontend/src/store/appStore.ts` — 검색·프로필·추천 경로·선택 상태
- `frontend/src/adapters/types.ts` — 프론트 데이터 어댑터 계약
- `frontend/src/adapters/mock.ts` — mock 모드
- `frontend/src/adapters/live.ts` — live API 모드
- `frontend/src/map/kakaoLoader.ts` — 카카오맵 SDK 로더
- `data/ai/places.json`
- `data/ai/routes.demo.json`
- `data/ai/weather.json`
- `data/ai/bus_arrivals.json`

예전 `data/places.json`, `data/routes.demo.json`, `data/weather.json`, `data/bus_arrivals.json`은 중복이므로 추가하지 않습니다. 데이터 소스는 `data/ai/`를 단일 기준으로 사용합니다.

## 4. 데이터 흐름

1. 장소 입력 → `adapters.places.searchPlaces`
2. 검색 실행 → `appStore.search`
3. 경로 추천 → `adapters.routes.recommend`
4. 추천 결과 → `ScoredRoute[]`
5. 선택 경로의 `route.path`를 지도에 표시

좌표 규칙:

- 도메인 좌표는 `{ lat, lng }`
- KakaoMap 경계에서만 `[longitude, latitude]` 튜플로 변환

## 5. 지원 프로필

| ProfileId | 표시명 |
|-----------|--------|
| `general` | 일반 |
| `elderly` | 고령자 |
| `child` | 아동 |
| `youth` | 청소년 |
| `disabled` | 장애인 |
| `pregnant` | 임산부 |

## 6. live API 계약

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/api/places/search?q=` | 장소 검색 |
| `POST` | `/api/routes/candidates` | 경로 후보 생성 |
| `POST` | `/api/routes/recommend` | 프로필·날씨·옵션 기반 추천 |
| `GET` | `/api/bus/arrivals/:stopId` | 정류장 도착 정보 |
| `GET` | `/api/bus/stops?q=` | 정류장 검색 |
| `GET` | `/api/weather?scenario=` | 날씨 조회 |

정확한 요청·응답 타입은 `frontend/src/types/index.ts`와 `frontend/src/adapters/types.ts`를 단일 기준으로 사용합니다.

## 7. 환경 변수

실제 키 값은 저장소에 넣지 않습니다. 변수 이름만 참고하세요.

| 변수 | 설명 |
|------|------|
| `VITE_KAKAO_MAP_KEY` | 카카오맵 JavaScript SDK 앱 키 |
| `VITE_DATA_SOURCE` | `mock` 또는 `live` |
| `VITE_API_BASE` | live API 베이스 URL |

## 8. 통합 주의사항

- 기존 `App.tsx`를 v2로 교체하지 않습니다.
- 기존 `frontend/src/components/MapView.tsx`를 `v2/KakaoMap.tsx`로 통째로 교체하지 않습니다.
- 프로필 패널, 검색 UI, 바텀시트, 지도 상호작용 등 필요한 부분만 선별 통합합니다.
- `mapDemoData.ts` 데이터는 화면 시연용이며 실제 길찾기 결과가 아닙니다.
- 실제 추천 결과가 있으면 `route.path`를 우선 사용합니다.

## 9. 검증 결과

- TypeScript typecheck 통과
- Vitest 8개 파일, 63개 테스트 통과
- Vite production/PWA build 통과

## 10. 제외 항목

- MapLibre 및 `maplibre-gl`
- 예전 루트 `data/*.json` 중복 파일
- `data/da/raw` 원본 CSV
- `.env`와 실제 API 키
- `node_modules`와 `dist`
