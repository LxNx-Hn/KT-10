# Map-first UI v2

## 현재 상태

지도 중심 UI/UX와 프로덕션 기능을 연결한 프론트 단일 진입점입니다.

- `App.tsx`는 `MapFirstApp`을 렌더링합니다.
- `MapFirstPrototype.tsx`는 `MapFirstApp` 호환 별칭입니다.
- 초기 가짜 경로·고정 좌표·자동 데모 검색은 실행하지 않습니다.
- `components/MapView.tsx`와 데이터 계약은 호환 경로로 유지합니다.
- 검색 카드, 프로필·짐·계단·쉬운 화면 칩, 우측 지도 조작부와 하단 시트는
  인계본의 정보 위계와 조작 위치를 기준으로 유지합니다.
- API 연결 여부나 내부 데이터 모드는 사용자 화면에 표시하지 않습니다.

## 파일 역할

| 파일 | 역할 |
| --- | --- |
| `MapFirstApp.tsx` | 장소 검색, 프로필·이동 조건, 추천 카드, 상세 drawer, 음성 진입점 |
| `KakaoMap.tsx` | Kakao 지도, 출·도착 마커, 선택·대안 경로, 편의시설·건물 그늘 오버레이 |
| `routeViewModel.ts` | 서버 응답을 사실 배지와 점수 설명으로 변환 |
| `map-first.css` | 모바일 우선 지도·바텀시트·drawer 디자인 |
| `MapFirstPrototype.tsx` | `MapFirstApp` 호환 re-export |
| `mapDemoData.ts` | 인계본 시각 참고 데이터; 프로덕션 v2에서는 import하지 않음 |

## 사용자 흐름

1. 출발지·도착지를 Kakao Places에서 검색하고 결과 항목을 선택합니다.
2. `appStore.search`가 백엔드 추천 API를 호출합니다.
3. 서버가 정렬한 `ScoredRoute[]` 순서를 하단 결과 시트의 세로 경로
   목록에 그대로 표시합니다. 시트는 collapsed / medium / expanded
   3단계 snap을 지원하고, 목록 내부 세로 스크롤을 시트 드래그보다
   우선하며 시트 제스처는 배경 지도로 전파되지 않습니다.
4. 목록 항목 클릭·키보드·스크린리더 또는 지도 경로를 선택하면
   카드와 지도가 같은 `selectedRouteId`를 사용합니다.
5. 상세 drawer에서 경로 사실, 날씨·버스, 후기·신고, 내 설정을 확인합니다.
6. 그늘 계산 시각 변경은 서버가 보관한 같은 후보군의 그늘과 순위만
   갱신하며 장소검색·경로 공급자를 다시 호출하지 않습니다.

로그인과 큰 글씨 설정은 검색 카드에 별도 상태 줄로 노출하지 않고
`내 설정`에 둡니다. 그늘·편의시설은 원본 지도 조작부를 대체하지 않으며,
해당 경로에 확인된 데이터가 있을 때만 추가 레이어로 표시합니다.

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
- 편의시설은 경로 구간 좌표와 함께 승강기 또는 저상버스가 확인된 경우만
  표시하며, 미확인 시설의 위치를 임의로 생성하지 않습니다.

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
| `VITE_DATA_SOURCE` | `mock` 또는 `live`; 미지정 기본값은 `live` |
| `VITE_API_BASE` | live 백엔드 API 기준 URL |
| `VITE_DEV_PROXY_TARGET` | Vite 개발 서버의 `/api` 전달 대상; 기본 `http://localhost:8080` |

mock은 명시적으로 `VITE_DATA_SOURCE=mock`을 지정한 테스트에서만
사용합니다. 일반 개발은 환경값이 없어도 live입니다.
JavaScript 키가 있으면 브라우저 Places SDK를 우선 사용하고, 키가 없거나
SDK가 허용 도메인·네트워크 문제로 실패하면 백엔드 검색을 사용합니다.
이 경우 응답의
`X-Place-Search-Source: kakao-rest`가 확인되지 않으면 데모 응답을 실제
검색처럼 표시하지 않고 실패시킵니다.
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

검증 명령은 Vitest, Playwright 접근성·Kakao Places E2E, PWA production
build와 npm audit을 포함합니다.

`test:e2e:places`는 실행 중인 live 백엔드, 유효한 Kakao JavaScript 키,
`E2E_BASE_URL`과 정확히 일치하는 Kakao JavaScript SDK 허용 도메인이
없으면 실패하도록 되어 있습니다. 로컬 프로덕션 검증 기본값은
`http://localhost:8080`입니다.
