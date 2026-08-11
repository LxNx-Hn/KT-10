# 경사 오버레이가 건물을 가로지르던 문제 수정

- 작업일: 2026-08-11
- 범위: 지도에서 경사 표시를 켰을 때 그려지는 선의 **위치**만 수정
- 변경하지 않은 것: 경사 계산 로직, 90m 표본 간격, 점수·순위·모델·학습 계약

---

## 1. 증상

지도에서 경사 표시를 끄면 경로선이 도로를 따라 정상적으로 꺾인다.
경사 표시를 켜면 색이 입혀진 선이 **코너를 잘라먹고 건물을 관통**한다.

같은 경로인데 표시를 켜고 끌 때마다 선이 지나가는 자리가 달라졌다.

## 2. 원인

경사 표시를 켰을 때와 껐을 때 **서로 다른 geometry**를 그리고 있었다.

| 상태 | 그리던 데이터 | 결과 |
| --- | --- | --- |
| 경사 OFF | `route.path` (공급자 원본 polyline) | 도로를 따라감 |
| 경사 ON | `terrain.slopeSegments`의 `start`→`end` **2점 직선** | 코너가 잘림 |

`slopeSegments`는 원래 **경사 계산용 표본**이다. `ai/features/elevation.py`가
경로를 누적거리 90m 간격으로 재표본화하고, 이웃한 두 표본의 고도차로 경사를
구한다. 90m는 GLO-90 DEM의 해상도에 맞춘 값이므로 **경사 계산 자체는 옳다.**

문제는 이 "계산용 표본점"을 그대로 "화면에 그릴 선"으로 재사용한 것이다.
표본 두 점을 직선으로 이으면 그 사이 90m 안에 있던 코너가 전부 사라진다.
실제 보행로가 건물을 돌아가는 구간에서는 그 직선이 건물을 통과한다.

```
실제 보행로   ┌────────┐        표본 직선   ●
              │        │                     ＼
    ●─────────┘        └──●                   ＼
    표본                  표본                   ●   ← 건물 관통
```

## 3. 해결 방법

경사 구간마다 **표본 사이를 원본 polyline 정점으로 채운 표시용 경로(`path`)**
를 서버가 함께 내려주고, 지도는 그것을 그린다.

- 경사 값은 지금까지처럼 표본 간 직선 기준으로 계산한다.
- `path`는 **화면 렌더링 전용**이며 어떤 수치에도 관여하지 않는다.
- 색이 바뀌는 경계 위치는 이전과 동일하다. 선이 지나가는 자리만 실제 길 위로
  옮겨진다.

### 대안과 선택 이유

프론트엔드에서 `slopeSegments` 좌표를 원본 polyline에 투영해 구간을 되찾는
방법도 검토했다. 서버를 안 건드려도 되지만, `slopeSegments`가 보행 part 구분이
없는 평탄한 목록이라 왕복·자기교차 경로에서 잘못된 구간에 매칭될 여지가 있다.
서버는 어느 part의 어느 위치인지 이미 알고 있으므로 서버가 주는 쪽을 택했다.

## 4. 변경 파일

| 파일 | 변경 내용 |
| --- | --- |
| `ai/features/elevation.py:378` | `_sample_anchors()` — 표본 좌표와 함께 그 표본이 원본 polyline의 어느 정점 사이 어느 비율에 있는지 반환 |
| `ai/features/elevation.py:434` | `_sample()` — 기존 시그니처 그대로 유지하는 얇은 wrapper로 축소 |
| `ai/features/elevation.py:450` | `_anchor_subpath()` — 표본 두 개 사이를 원본 정점으로 채운 부분경로 생성 |
| `ai/features/elevation.py:491` | `calculate_slope_features_for_parts()` — 선택 인자 `display_path_parts`를 받아 각 경사 구간에 `path` 부착. 인자가 없으면 이전과 완전히 동일하게 동작 |
| `ai/features/elevation.py:40` | 고도 캐시 스키마 v3 → v4 |
| `backend/app/models.py:89` | `TerrainSlopeSegment.path` 추가 (기본 빈 목록) |
| `frontend/src/types/index.ts:148` | `slopeSegments[].path?: LatLng[]` 추가 |
| `frontend/src/v2/KakaoMap.tsx:216` | `segment.path`를 우선 사용, 없으면 기존 `start`/`end` 직선으로 폴백 |
| `ai/tests/test_elevation.py` | 회귀 테스트 2개 |
| `frontend/src/v2/KakaoMap.test.tsx` | 회귀 테스트 1개 |

합계 6개 파일, +320 / -23 줄.

### 하위 호환

`path`는 모든 계층에서 선택 필드다.

- 서버가 안 보내면 백엔드 모델은 빈 목록으로 받고, 지도는 예전처럼
  `start`/`end` 직선을 그린다.
- 프론트엔드만 먼저 배포돼도 깨지지 않는다.

## 5. 고도 캐시를 무효화한 이유

`ELEVATION_CACHE_DIR`의 캐시는 고도 원본값이 아니라 **경사 계산이 끝난 결과
전체**를 저장한다. `slope_segments` 배열까지 통째로 들어 있다.

캐시가 히트하면 `extract_elevation_features_for_parts()`는 저장된 결과를 그대로
반환하고 끝낸다. `path`를 붙이는 코드는 그 아래에 있으므로 아예 실행되지 않는다.

```python
cached = await asyncio.to_thread(_read_cache, sampled_parts)
if cached is not None:
    return cached          # ← 여기서 종료. path 없는 v3 결과가 그대로 나간다
```

버전을 올리지 않았다면 이렇게 됐을 것이다.

- 처음 검색되는 경로 → 정상 (길 따라감)
- 전에 검색된 적 있는 경로 → **여전히 건물 관통**

프로덕션 TTL이 30일(`ELEVATION_CACHE_TTL_SECONDS=2592000`)이므로, 자주
검색되는 인기 경로일수록 오래 남는다. 가장 많이 보게 될 경로에서 버그가 최장
한 달 살아남고 재현도 들쭉날쭉해진다.

`CACHE_SCHEMA_VERSION`을 4로 올리면 v3 항목이 전부 읽기 단계에서 걸러지고
재계산 후 v4로 덮어써진다. 파일명이 좌표 해시라 같은 경로는 같은 파일을
덮어쓰므로 찌꺼기가 쌓이지 않는다.

**비용:** 배포 직후 경로당 재계산 1회, 로컬 DEM 기준 약 0.5 ms. DEM은 이미
메모리에 적재돼 있어 파일 I/O도 없다. live 기본값이
`ELEVATION_NETWORK_FALLBACK_ENABLED=false`라 외부 고도 API를 다시 부르지도
않는다.

## 6. 성능 측정

### 측정 조건과 한계

로컬 ODsay 키가 이 개발 머신 IP에서 `[ApiKeyAuthFailed]`를 반환해 **실제
공급자를 포함한 전체 왕복 시간은 측정하지 못했다.** 대신 후보 수집 이후 서버가
계산하는 전 구간(이번 변경이 닿는 범위 전부)을 실제 코드로 측정했다. 네트워크
지터가 빠지므로 변경 자체의 delta는 오히려 더 정확하게 보인다.

- 경로: 부산 서면~전포 도보 코리더, 58 정점 / 906 m / 보행 part 2개
- 방식: 변경 전·후 모듈을 **한 프로세스에서 A/B 교차**, 12 라운드 × 100 반복

### 계산 시간

| 구간 | 변경 전 | 변경 후 | 차이 |
| --- | --- | --- | --- |
| 경사 피처 계산 (mean) | 0.4812 ms | 0.5050 ms | **+0.024 ms (+4.9%)** |
| 경사 피처 계산 (median) | 0.4791 ms | 0.5055 ms | +0.026 ms |
| 병합 + 공간피처 + 경사 전체 (p50) | 7.10~8.36 ms | 7.15~7.43 ms | **노이즈 이내, 구분 불가** |

### 응답 크기 (경사 구간 데이터, 경로 1개)

| | 변경 전 | 변경 후 | 차이 |
| --- | --- | --- | --- |
| 원본 | 1,547 B | 5,063 B | +3,516 B |
| gzip | 371 B | 876 B | +505 B |

후보 5개 응답 기준 **gzip 후 약 +2.5 KB**.

### 결론

길찾기 응답 시간은 사실상 변하지 않는다. 계산은 경로당 +0.024 ms, 전송은
gzip +2.5 KB다. 체감 시간을 지배하는 ODsay·TMAP·VWorld 왕복(수백 ms ~ 수 초)에
비하면 측정 오차 수준이다.

## 7. 계약 검증

### 경사 수치 불변

`avg` / `max` / `min_slope_percent`, `slope_iqr`, `elevation_gain_m`,
`elevation_loss_m`, `uphill` / `downhill_distance_m`, 구간 수, 각 구간의
`start` / `end` / `slope_percent` / `distance_m` — 전부 변경 전과 일치함을
벤치마크와 전용 회귀 테스트 양쪽에서 확인했다.

### 기존 계약 유지

- **모델·학습 무영향**: `_slope_segments`는 언더스코어 키라
  `ai/api/router.py`의 스냅샷·모델 피처 구성에서 제외된다.
  `feature_snapshot_hash`, XGBoost ranker, 학습 데이터에 영향이 없다.
- **끊어진 part를 잇지 않음**: 표시용 경로는 각 보행 part 안에서만 만들어진다.
  회귀 테스트가 모든 정점이 하나의 원본 part 안에 있는지 검증한다.
- **미확인을 0으로 대체하지 않음**: 1 m 미만이라 경사 구간으로 잡히지 않는
  자리는 이전처럼 색 없이 남는다.
- **추정 geometry 표시 정책 유지**: `estimated` 구간 점선 처리 그대로.

### 추가한 회귀 테스트

| 테스트 | 검증 내용 |
| --- | --- |
| `test_slope_segment_path_follows_original_walk_geometry` | 표시 경로의 양 끝이 표본과 일치하고, 모든 정점이 하나의 원본 보행 part 안에 있으며, 코너 정점이 실제로 살아 있는지 |
| `test_slope_segment_path_does_not_change_slope_metrics` | 표시 경로 유무와 무관하게 경사·고도 수치와 구간 경계가 동일한지 |
| `KakaoMap.test.tsx` — 경사 구간 표시 경로 | 지도가 표본 직선이 아니라 `path`의 코너 정점까지 그리는지 |

기존 테스트 `'90m 지형 표본 사이 경사를 구간별 색상으로 표시한다'`는 `path`가
없는 응답을 사용하므로 폴백 동작의 회귀 테스트 역할을 그대로 한다.

## 8. 검증 결과

| 검사 | 결과 |
| --- | --- |
| `PYTHONPATH=ai pytest ai/tests -q` | 235 passed, 2 skipped |
| `pytest backend/tests -q` | 283 passed, 1 skipped |
| `npx vitest run` (frontend) | 342 passed (34 files) |
| `tsc --noEmit` | 통과 |
| `npm run build` (PWA 포함) | 통과 |
| `ruff check ai --select E4,E7,E9,F` | 통과 |
| `ruff check backend scripts --select E4,E7,E9,F` | 통과 |
| `compileall ai backend` | 통과 |

## 9. 후속 확인이 필요한 별건

작업 중 발견했으나 **이번 범위 밖이라 손대지 않은 사항**이다.

증상이 보고된 오시리아역~롯데월드 어드벤처 부산 구간은 번들 DEM
(`ai/data/precomputed/busan_dem_clipped_90m.tif`)에서 bilinear 보간 이웃 4칸 중
바다 nodata에 걸려 로컬에서는 경사가 `unavailable`로 나온다. 실제 화면에는
경사색이 표시됐으므로 운영 환경의 DEM 커버리지 또는 설정이 로컬과 다른 것으로
보인다. 확인이 필요하다.

이 때문에 성능 측정은 경사가 실제로 계산되는 내륙 구간(서면~전포)으로
진행했다.
