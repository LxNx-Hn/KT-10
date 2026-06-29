# 구현 명세 (Implementation Spec)

> README.md = 기획서. 이 문서 = 구현된 코드의 기능·함수·데이터·검증 명세 (기획서 §14 산출물 요구 대응).
> 스택: **React + Vite + TypeScript (PWA)** · 대상: **부산 부산진구(서면 일대)** · 데이터: **mock 우선 + 어댑터 분리**

---

## 1. 실행 방법

```bash
cd KT-10
npm install
npm run dev        # http://localhost:5173 (PWA dev)
npm test           # 점수/음성 단위 검증 (21 tests)
npm run validate   # 점수 검증 표 출력 (기획서 §8)
npm run build      # 타입체크 + 프로덕션 빌드
npm run preview    # 빌드 결과 미리보기
```

Kakao 실제 지도는 `.env` 에 `VITE_KAKAO_MAP_KEY` 설정 시 표시됩니다. 키가 없으면 약도(스키매틱) 패널로 자동 폴백합니다. (`.env.example` 참고)

---

## 2. 파일 구조

```
KT-10/
├─ index.html, vite.config.ts, tsconfig.json   # PWA/번들 설정 (vite-plugin-pwa)
├─ public/                                      # favicon, PWA 아이콘
├─ src/
│  ├─ types/index.ts          # 도메인 타입(SSOT): Profile/Route/Weather/Score 등
│  ├─ config/
│  │  ├─ profiles.ts          # 4개 프로필 메타데이터
│  │  ├─ weights.ts           # 프로필별 가중치 표(합=1) + 옵션 보정
│  │  └─ district.ts          # 부산진구 좌표/범위
│  ├─ scoring/                # ★ 점수화 엔진(순수 함수)
│  │  ├─ components.ts        # 8개 하위 점수 함수
│  │  ├─ explain.ts           # 이유/주의/음성요약/저상상태 생성
│  │  ├─ engine.ts            # 가중합·정렬·상위3 추천 오케스트레이터
│  │  ├─ utils.ts             # clamp/avg/round
│  │  └─ validation/validation.test.ts  # 점수 검증 + 표 출력
│  ├─ data/                   # 부산진구 mock 데이터
│  │  ├─ places.ts, routes.ts, busArrivals.ts, weather.ts
│  ├─ adapters/               # 외부 API 어댑터(인터페이스 + mock 구현 + 팩토리)
│  ├─ map/kakaoLoader.ts      # Kakao SDK 동적 로더
│  ├─ voice/                  # 음성: synthesis(TTS) / commandParser / useVoiceControl(STT)
│  ├─ store/appStore.ts       # zustand 전역 상태
│  ├─ components/             # MapView, SearchBar, ProfileSelector, RouteCard, RouteList,
│  │                          #  WeatherPanel, BusArrivalCard, VoiceButton, ui(배지/막대)
│  ├─ App.tsx, main.tsx, index.css
```

---

## 3. 핵심 기능 명세 (§14: 기능/입력/출력/함수/데이터/예외/검증/UI)

### 3.1 점수화 엔진 (기획서 §6·§7 — 서비스의 심장)

- **기능**: 경로 후보를 8개 항목으로 채점하고 프로필 가중치를 적용해 최종 추천 점수와 순위를 산출.
- **입력**: `RouteCandidate[]`, `WeatherCondition`, `ProfileId`, `ScoringOptions{lowFloorPriority, weatherAvoid}`
- **출력**: `ScoredRoute[]` (상위 3개) — 각 `RouteScore{components, display, finalScore, lowFloorStatus, reasons[], cautions[], voiceSummary}`
- **주요 함수**:
  - `scoreAccessibility / scoreWalkComfort / scoreElevator / scoreLowFloorBus / scoreWeatherSafety / scoreSafety / scoreDataReliability / scoreTimeEfficiency` → 각 0~100 "좋음 점수"
  - `weightedFinal(components, weights)` → 가중합
  - `recommendRoutes(candidates, weather, profile, opts, topN=3)` → 채점·정렬·상위 N
- **데이터 구조**: `ScoreComponents`(8필드), `ProfileWeights`(프로필별 가중치, 합=1)
- **점수 규약**: 모든 하위 점수는 "높을수록 이상적"으로 통일. 화면 표시용 보행부담/날씨위험은 `100 - 좋음점수`.
- **예외 처리**: 후보 0개 → `[]`; 수직이동/버스 없는 경로 → 승강기/저상 점수는 감점 대신 중립값; 정보 미확인(`undefined`)은 "없음(false)"과 구분해 중간 점수 + 데이터신뢰도 감점.
- **검증**: `src/scoring/validation/validation.test.ts` (아래 §4).
- **UI 반영**: `RouteCard` 의 점수막대/배지/이유/주의, 정렬 순서.

### 3.2 저상버스 (기획서 §9) — 핵심 기능
- **기능**: 정류장 도착 조회, 저상 여부 3값 표시(확정/일반/미확인), 저상버스 우선 정렬·가중.
- **입력**: `stopId`, `options.lowFloorPriority` / **출력**: 정렬된 `BusArrival[]`, 음성 안내 문구.
- **함수**: `adapters.bus.getArrivals/listStops`, `sortLowFloorFirst`, `deriveLowFloorStatus`, 가중치 `applyOptionWeights`.
- **데이터**: `BusArrival{routeName, arrivalMin, isLowFloor:Tristate}`.
- **예외**: 도착 정보 없음 → "도착 정보 없음", `isLowFloor===undefined` → "미확인" 배지/안내.
- **UI**: `BusArrivalCard` — 정류장 선택, 저상 우선 토글(♿), 행별 🔊 음성.
- **음성 예시**: "5분 뒤 도착하는 81번 버스는 저상버스입니다." / "…저상버스 여부가 확인되지 않았습니다."

### 3.3 날씨 반영 (기획서 §10)
- **기능**: 기온/체감/강수/폭염/한파/풍속/미세먼지 × 노출(실외보행·대기·계단) → 위험 점수·안내.
- **함수**: `scoreWeatherSafety(route, weather)`; 시나리오 `WEATHER_SCENARIOS`(평상/폭염/한파/비/미세먼지).
- **규칙**: 폭염+긴 실외보행 / 한파+긴 대기 / 비+계단·경사 / 미세먼지+긴 실외 → 감점 + 안내.
- **UI**: `WeatherPanel`(시나리오 토글로 점수 변화 시연), 카드 날씨위험 배지(텍스트+색), 주의사항.

### 3.4 음성 (기획서 §11)
- **기능**: 음성명령(STT)으로 목적지검색/프로필변경/조건변경/저상우선/날씨회피/경로설명/선택/반복, 음성안내(TTS).
- **함수**: `parseCommand(text): VoiceAction[]`(규칙기반, 다중의도), `useVoiceControl()`(SpeechRecognition + 실행 + TTS), `speak/stopSpeaking`.
- **예외**: 미지원 브라우저 → 버튼 비활성("음성 미지원"); 미인식 → "이해하지 못했어요"; 장소 미발견 안내.
- **검증**: `commandParser.test.ts` — 기획서 예시 명령 8종.
- **UI**: 하단 고정 `VoiceButton`(🎤 음성명령 / 🔁 다시 듣기 / ⏹ 정지).

### 3.5 지도·검색·프로필·UI
- `MapView`: Kakao SDK 로드(키 있을 때) / 약도 폴백(SVG). `SearchBar`: 장소 자동완성. `ProfileSelector`: 4개 큰 칩.
- 큰 UI: 고령자/아동 선택 시 자동 확대 + 상단 "큰 글씨" 토글(`--fs-base`, `--tap` 변수).

---

## 4. 점수 검증 결과 (기획서 §8 — 표 형태, `npm run validate`)

### 표1. 프로필 × 경로 최종점수 (평상 날씨)

| 프로필 | 도보 최단(육교) | 지하철(승강기) | 저상버스 81 | 일반버스 210 |
|---|---|---|---|---|
| 일반 | 81.5 | **92.0** | 87.0 | 87.1 |
| 고령자 | 70.2 | **92.1** | 87.6 | 85.1 |
| 아동 | 81.4 | **93.0** | 88.8 | 84.7 |
| 장애인 | 69.6 | **91.8** | 90.0 | 78.1 |

### 표2. 날씨 시나리오별 날씨위험 점수 (일반 프로필, 높을수록 위험)

| 날씨 | 도보(육교) | 지하철 | 저상버스 | 일반버스 |
|---|---|---|---|---|
| 평상 | 0 | 0 | 0 | 0 |
| 폭염 | 25 | 16 | 19 | 16 |
| 한파 | 5 | 2 | 13 | 8 |
| 비 | 30 | 12 | 28 | 12 |
| 미세먼지 | 20 | 14 | 16 | 14 |

### 검증 항목 통과 (21 tests)
- ✅ 계단(육교) 경로가 장애인 프로필에서 감점 → 상위 3개에서 제외 (69.6, 최하위)
- ✅ 승강기 경로가 고령자·장애인에서 일반버스 대비 가점
- ✅ 저상버스 경로가 장애인에서 일반버스보다 높음 + 저상 우선 옵션 시 순위 상승
- ✅ 폭염·비·미세먼지 변경 시 동일 경로 날씨 점수 하락
- ✅ 횡단·사고위험 많은 일반버스 경로가 아동 프로필에서 추가 감점 (87.1→84.7)
- ✅ `lowFloorStatus` 판정(확정/일반/버스없음) 정확
- ✅ 음성명령 예시 8종 파싱 정확

---

## 5. 실제 API 전환 가이드

`src/adapters/` 의 인터페이스(`PlacesAdapter/RouteAdapter/BusAdapter/WeatherAdapter`)는 mock 과 동일 시그니처. 실 연동 시:
1. `src/adapters/live.ts` 작성 — Kakao 키워드/길찾기, 공공데이터 버스도착(저상 차량유형), 기상청/에어코리아.
2. `getAdapters()` 에서 `VITE_DATA_SOURCE=live` 분기 연결.
3. `data/*` mock 은 발표 데모/테스트 픽스처로 유지.
