# 작업 보고서 — 대중교통 도착 임박 표시와 초 단위 제거

- 작성일: 2026-08-23
- 상태: **작업 완료 · 검증 완료**
- 기준 커밋: `3d3981c`
- 대상: 버스·지하철 도착정보 표시 계층과 지하철 분 환산 규칙

---

## 1. 요구사항

1. 버스·지하철 모두 도착 예정이 **1분 미만이면 시간 대신 "도착" 또는 "출발"** 로 표시한다.
2. **시간 단위 초는 화면에 보여주지 않는다.**

착수 전 확인 과정에서 아래 조건이 추가로 확정됐다.

- 1분 미만 문구는 "도착"이 아니라 **"곧 도착"** 을 쓴다.
- 지하철은 **시발역이면 "곧 출발", 중간역이면 "곧 도착"** 으로 나눈다.
- 지하철에 **"출발"(완료형)은 쓰지 않는다.** 시간표는 실제 출발 여부를 알려주지 않는다.
- **"시간표 기준이며 실시간 열차 위치 정보는 아닙니다" 문구는 절대 변경하지 않는다.**

---

## 2. 착수 전 확인한 데이터 정밀도

| 대상 | 원천 | 정밀도 |
| --- | --- | --- |
| 버스 | BIMS `min1`/`min2` | **분 단위만.** 초 없음. 숫자가 아니면 원문이 `arrivalMessage`로 감 |
| 지하철 | 부산교통공사 시간표 `arrtime` | **`HH:MM:SS` — 초까지 있음** |

초 단위 계산이 가능한 쪽은 지하철뿐이다. 따라서 분 환산 규칙 변경은 지하철에만 적용되고,
버스는 BIMS가 준 분을 그대로 쓴다.

또한 착수 전 조사에서 **`departureTime`이 `HH:MM:SS` 원문 그대로 화면에 노출**되고
있었음을 확인했다(`(10:05:00)`). 요구사항 2에 해당하므로 함께 처리했다.

---

## 3. 확정한 표시 규칙

### 3.1 분 환산 (지하철)

```
남은 초 < 60   → 0   (표시 계층이 "곧 도착/출발"로 렌더)
남은 초 >= 60  → floor(초 / 60 + 0.5)   반올림
```

**1분 미만을 반올림 대상에서 제외한 이유.** 순수 반올림이면 59초가 `1분`이 되어
"1분 미만이면 곧 도착"이라는 1번 요구사항을 만족할 수 없다. 요구사항 1이 반올림보다
우선이라고 판단해 두 규칙을 분리했다. 근거는 `_minutes_until()` docstring에 남겼다.

출발시각이 지난 경우(음수)도 0으로 수렴하므로 음수 분이 생기지 않는다.

### 3.2 문구

| 대상 | 1분 이상 | 1분 미만 |
| --- | --- | --- |
| 버스 (live) | `N분 후 도착` | `곧 도착` |
| 지하철 중간역 (scheduled) | `N분 후 도착 (HH:MM)` | `곧 도착` |
| 지하철 시발역 (scheduled) | `N분 후 출발 예정 (HH:MM)` | `곧 출발` |

지하철은 상태와 무관하게 **`시간표 기준이며 실시간 열차 위치 정보는 아닙니다.`** 고지를
항상 함께 노출한다. 중간역 표기가 "출발 예정"에서 "도착"으로 바뀌면서 실시간처럼 보일
여지가 생기므로, 이 고지가 사실성 계약을 지탱하는 핵심 장치가 됐다.

### 3.3 시발역 판별

기존 `busan_subway_stations.py`의 정적 역 순서(`LINE_STATIONS`)를 재사용한다.

```
direction "1"(역 index 증가) → 시발역 = LINE_STATIONS[line][0]
direction "0"(역 index 감소) → 시발역 = LINE_STATIONS[line][-1]
승차역 == 시발역  →  origin,  그 외  →  intermediate
```

기존 `journey_terminal()`(종착역)의 대칭 구현이다. 해당하는 역은 노선 양 끝 8개다.

| 노선 | 시발역 |
| --- | --- |
| 1호선 | 다대포해수욕장 · 노포 |
| 2호선 | 장산 · 양산 |
| 3호선 | 수영 · 대저 |
| 4호선 | 미남 · 안평 |

버스는 BIMS 응답에 기점·종점 정보가 없어 판별할 수 없으므로 `boarding_kind`를
`None`으로 두고 항상 "도착" 문구를 쓴다.

---

## 4. 변경 내역

### 백엔드

| 파일 | 변경 |
| --- | --- |
| `backend/app/providers/busan_subway_stations.py` | `journey_origin_terminal()`, `boards_at_origin_terminal()` 추가 |
| `backend/app/providers/transit_arrivals.py` | `ceil` → `_minutes_until()`, `_subway_boarding_kind()` 추가 및 응답에 결합 |
| `backend/app/models.py` | `TransitLegArrival.boarding_kind: "origin" \| "intermediate" \| None` 추가 |

### 프론트엔드

| 파일 | 변경 |
| --- | --- |
| `frontend/src/types/index.ts` | `TransitLegArrival.boardingKind` 추가 (백엔드 모델과 동기화) |
| `frontend/src/v2/components/TransitArrivalPanel.tsx` | `arrivalLabel()` 재작성, `clockSuffix()`로 `HH:MM:SS` → `HH:MM` |
| `frontend/src/components/BusArrivalCard.tsx` | `0분 후` → `곧 도착`, 음성 안내 `0분 뒤 도착하는` → `곧 도착하는` |

### 테스트

| 파일 | 추가 |
| --- | --- |
| `backend/tests/test_transit_arrivals.py` | 반올림 경계 9케이스 파라미터화, 시발역/중간역 판별, **시간표 고지 보존 회귀**, 버스 `boarding_kind` 부재 |
| `frontend/src/v2/components/TransitArrivalPanel.test.tsx` | `곧 도착`/`곧 출발`, 시발역 대 중간역, 초 제거, **시간표 고지 보존 회귀** |
| `frontend/src/components/BusArrivalCard.test.tsx` | `0분` 미노출과 `곧 도착` 표시 |

기존 테스트 중 `5분 후 출발 예정 (10:05:00)`을 기대하던 단언은 새 계약인
`5분 후 도착 (10:05)`으로 갱신했다.

---

## 5. 검증

### 5.1 테스트·빌드·정적분석

```
백엔드   541 passed, 1 skipped
프론트   535 passed (52 files)
빌드     tsc + vite build 성공
정적분석 ruff (E4,E7,E9,F) All checks passed / compileall OK
```

### 5.2 실제 provider 실행 결과

외부 시간표 API만 대체하고 실제 `transit_arrivals` 코드를 호출해 얻은 값이다.

**분 환산 — 부산역 → 서면역 (1호선 중간역)**

| 남은 시간 | `arrival_min` |
| --- | --- |
| 2분 30초 | 3 |
| 1분 59초 | 2 |
| 1분 30초 | 2 |
| 1분 01초 | 1 |
| 1분 00초 | 1 |
| 0분 59초 | **0** |
| 0분 20초 | **0** |
| 0분 00초 | **0** |
| −0분 30초 | **0** |

**시발역 판별 — 1~4호선**

| 승차역 → 하차역 | 노선 | `boarding_kind` |
| --- | --- | --- |
| 다대포해수욕장 → 서면 | 1호선 | `origin` |
| 노포 → 서면 | 1호선 | `origin` |
| 부산 → 서면 | 1호선 | `intermediate` |
| 서면 → 동래 | 1호선 | `intermediate` |
| 장산 → 서면 | 2호선 | `origin` |
| 양산 → 서면 | 2호선 | `origin` |
| 수영 → 서면 | 2호선 | `intermediate` |
| 수영 → 미남 | 3호선 | `origin` |
| 대저 → 미남 | 3호선 | `origin` |
| 연산 → 미남 | 3호선 | `intermediate` |
| 미남 → 안평 | 4호선 | `origin` |
| 안평 → 미남 | 4호선 | `origin` |
| 수안 → 안평 | 4호선 | `intermediate` |

**버스**

| BIMS `min` | `arrival_min` | `status` | `boarding_kind` |
| --- | --- | --- | --- |
| 4 | 4 | `live` | `None` |
| 1 | 1 | `live` | `None` |
| 0 | 0 | `live` | `None` |

**시간표 고지 보존**

```
부산역 (intermediate) → 시간표 기준이며 실시간 열차 위치는 아닙니다.
노포역 (origin)       → 시간표 기준이며 실시간 열차 위치는 아닙니다.
```

### 5.3 실제 컴포넌트 렌더링 결과

`TransitArrivalPanel`을 실제로 렌더링해 얻은 화면 문구다.

| 입력 | 화면 문구 | 시간표 고지 |
| --- | --- | --- |
| 지하철 중간역, `arrivalMin=3`, `10:05:00` | `3분 후 도착 (10:05)` | O |
| 지하철 중간역, `arrivalMin=1`, `10:05:00` | `1분 후 도착 (10:05)` | O |
| 지하철 중간역, `arrivalMin=0`, `10:05:00` | `곧 도착` | O |
| 지하철 시발역, `arrivalMin=3`, `10:05:00` | `3분 후 출발 예정 (10:05)` | O |
| 지하철 시발역, `arrivalMin=1`, `10:05:00` | `1분 후 출발 예정 (10:05)` | O |
| 지하철 시발역, `arrivalMin=0`, `10:05:00` | `곧 출발` | O |
| 버스, `arrivalMin=4` | `4분 후 도착` | — |
| 버스, `arrivalMin=1` | `1분 후 도착` | — |
| 버스, `arrivalMin=0` | `곧 도착` | — |
| 지하철, `arrivalMin` 없음 | `시간표 출발 예정 (10:05)` | O |
| `unavailable` | 공급자 실패 문구 그대로 | — |

**초는 모든 경로에서 노출되지 않는다.** `0분`, `10:05:00` 형태가 화면에 남지 않음을
회귀 테스트로 고정했다.

---

## 6. 알려진 한계

### 6.1 중간역 착발 열차를 구분하지 못한다

신평 착발처럼 노선 중간역에서 시작하는 열차가 실제로 운행된다. 정적 역 순서만으로는
알 수 없어 `intermediate`로 분류되고 "도착"으로 표시된다.

시간표 고지가 항상 함께 노출되므로 사실성 위험은 없다고 판단해 이번 범위에서 제외했다.
근거는 `boards_at_origin_terminal()` docstring에 명시했다. 정확히 구분하려면 시간표
응답의 `endcode`를 열차별로 해석해야 하므로 별건이다.

### 6.2 버스에는 "도착"(완료) 상태가 없다

BIMS가 분 단위만 제공해 `min=0`이 "지금 도착"인지 "40초 뒤"인지 구분할 수 없다.
모르는 것을 확정된 사실로 표시하지 않는다는 원칙에 따라 `곧 도착`까지만 쓴다.

### 6.3 지하철에 "출발"(완료형)을 쓰지 않는다

시간표는 실제 출발 여부를 알려주지 않는다. 또한 백엔드가 출발시각이 1분 이상 지난
열차를 이미 걸러내므로, 완료형이 필요한 구간은 최대 1분에 불과해 실익이 없다.

---

## 7. 이번 작업에서 하지 않은 것

- 지하철 실시간 열차 위치·도착 API 도입 (별도 작업)
- ODsay 잔여 코드·환경변수·문서 정리 (별도 작업)
- `TransitLegArrival.status`에 `estimated` 추가 — 실시간 공급원 확보 전에는 쓰이지 않음
- `destinationArrivalTime` 표시 — 현재 화면에 노출되지 않음. 노출하게 되면 동일한
  초 제거 처리가 필요하다
- `BusArrivalCard.speakArrival`의 저상 여부 3값 처리 — 별건의 기존 결함으로, 이번
  변경 범위 밖이라 건드리지 않았다

---

## 8. 재현 명령

```bash
PYTHONPATH=backend python -m pytest backend/tests/test_transit_arrivals.py -q
```

```bash
cd frontend && npm test -- --run src/v2/components/TransitArrivalPanel.test.tsx src/components/BusArrivalCard.test.tsx
```

```bash
PYTHONPATH=backend python -m pytest backend/tests -q
cd frontend && npm test -- --run && npm run build
python -m ruff check backend --select E4,E7,E9,F
```
