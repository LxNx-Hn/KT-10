# LLM judge baseline

## 목적과 경계

LLM judge는 실제 사용자 평가가 쌓이기 전 프로필별 순위화 파이프라인을
검증하는 초기 baseline이다. 실제 경로 후보에서 고정한 피처만 평가하며,
LLM이 경로·시설·그늘 값을 새로 만들거나 결측을 0으로 추정해서는 안
된다.

- 관리자 검토 전 사람 모델: `ai/data/rankers.human-candidate.zip`
- 승인된 운영 모델: `ai/data/rankers.human-validated.zip`
- LLM judge 모델: `ai/data/rankers.judge-baseline.zip`
- 동의 후기 혼합 후보: `ai/data/rankers.review-mixed-candidate.zip`
- 운영 모델 tier: `human_validated`
- LLM judge tier: `judge_baseline`
- LLM judge 모델은 운영 경로에서 자동 로드·승격되지 않는다.
- 후기 혼합 후보도 `human_reviewers` 전용 승격 절차를 통과할 수 없다.
- 실제 사용자 모델은 기존과 동일하게 모든 OD·경로·프로필에 최소 9명의
  서로 다른 평가자가 필요하다.

모델 artifact는 pickle이 아니다. ZIP 내부의 manifest와 프로필별
XGBoost JSON만 허용하고 파일 경로·크기·SHA-256을 검증한 뒤 로드한다.

현재 실제 후보 스냅샷과 LLM 평가 결과가 없으므로
`rankers.judge-baseline.zip`은 생성되지 않았다. 저장소는 빈 평가표
생성기와 검증·학습기만 제공하며 실제 LLM 평가 실행은 외부 입력이다.

## 두 단계의 AI 역할

1. **경로 특성 표현:** 계산되거나 확인된 사실을 구조화한다. 프로필 선호나
   추천 점수를 섞지 않는다.
2. **프로필 적합도 평가:** 고정된 동일 피처 스냅샷을 보고 6개 프로필별
   relevance 0~4와 근거를 기록한다. 이 라벨로 별도 baseline을 학습한다.

지원 프로필은 `general`, `elderly`, `child`, `youth`, `disabled`,
`pregnant` 6개다. `짐 많음`, `유아차`, `그늘 우선`, `환승 최소` 등은
프로필이 아니라 해당 이동의 상황 조건이다.

## 피처 계약

건물 그늘 사실:

- `shade_ratio`: 전체 실외 도보 중 건물 그늘 비율, 0~1 또는 `null`
- `shaded_walk_m`: 건물 그늘 도보 거리 또는 `null`
- `shade_building_height_coverage`: 높이가 확인된 주변 건물의 비율 또는 `null`

상황 상호작용:

- `stroller_walk_burden`
- `stroller_stair_burden`
- `stroller_elevator_gap`
- `shade_priority_unshaded_walk_m`
- `minimize_transfers_burden`

상황 옵션이 꺼졌으면 상호작용 값은 0이다. 상황 옵션이 켜졌지만 원천
피처가 미확인이면 `null`을 유지한다. 그늘은 건물 그늘만 의미하며 나무
그늘이나 지형 그림자를 포함한다고 주장하지 않는다.

## 실제 후보 스냅샷

`labeling.generate_batch`는 토큰으로 보호된 백엔드
`POST /api/routes/labeling-candidates`의 응답만 기록한다. 백엔드는 공개
추천과 동일한 다음 순서를 사용한다.

1. AI `/labeling/candidates`로 실제 후보와 기본 피처를 수집한다.
2. 출발시각의 태양 위치와 건물 높이로 건물 그늘을 계산한다.
3. AI `/labeling/enriched-snapshots`에서 최종 피처 해시와 사실 특성을 만든다.

AI의 직접 `/recommend`는 이 그늘 보강을 우회할 수 있으므로 409로
비활성화되어 있다. 순위화는 enriched snapshot만 AI
`/rank/candidates`에 전달한다.

각 스냅샷에는 다음 provenance가 포함된다.

- `snapshot_schema_version=route-feature-snapshot-v2`
- `snapshot_kind=live_route_candidate`
- `captured_at`: 실제 후보·원천 피처를 수집한 시각
- `shade_evaluated_at`: 태양·건물 그늘을 계산한 출발시각
- `holdout_group_id`: 시간·상황이 달라도 같은 방향의 OD를 묶는 분할 키
- `sources`
- `geometry_quality`
- 전체 피처와 `feature_snapshot_hash`

Judge 라벨은 반드시 이 해시를 포함한다. 평가 후 피처나 provenance가
변경되면 학습기가 stale 라벨을 거부한다. `evaluated_at`은 실제 평가
완료시각이며 `captured_at` 이후여야 한다. 미래 출발시각일 수 있는
`shade_evaluated_at`과 비교하지 않는다.

## relevance rubric v1

- `4`: 해당 프로필·상황에 가장 적합한 후보
- `3`: 부담이 작고 사용할 만한 대안
- `2`: 장점과 부담이 함께 있는 중립적 후보
- `1`: 확인된 부담이 커서 우선 추천하기 어려운 후보
- `0`: 확인된 필수조건과 양립하지 않는 후보

미확인 값만으로 0점을 주지 않는다. Judge는 후보 공급자 이름과 기존
순위를 선호 근거로 사용하지 않고, 각 점수의 근거를 `rationale`에 남긴다.

한 `judge_run_id`에서는 judge source, rubric version, prompt hash가
동일해야 하며, 모든 실제 후보와 6개 프로필을 빠짐없이 평가해야 한다.
여러 run이 있으면 경로·프로필별 중앙값을 사용한다.

## 라벨 provenance

`ai/schemas/judge_label.schema.json` 계약의 주요 필드는 다음과 같다.

```json
{
  "schema_version": "judge-label-v1",
  "label_kind": "llm_judge",
  "judge_run_id": "judge-20260724-a",
  "judge_source": "openai:model-name",
  "rubric_version": "route-profile-rubric-v1",
  "prompt_hash": "64자리 sha256 hex",
  "evaluated_at": "2026-07-24T12:00:00+09:00",
  "group_id": "고정 OD 및 상황 식별자",
  "route_id": "고정 후보 식별자",
  "feature_snapshot_hash": "64자리 sha256 hex",
  "profile": "elderly",
  "relevance": 3,
  "rationale": "확인된 피처에 근거한 평가 이유"
}
```

## 경로 특성 라벨 계약

백엔드와 UI가 사용할 사실 라벨의 JSON Schema는
`ai/schemas/route_traits.schema.json`이다. 이 라벨은 추천 점수가 아니며
항상 피처 근거와 상태를 함께 전달한다.

```json
{
  "schema_version": "route-traits-v1",
  "group_id": "g1",
  "route_id": "r1",
  "feature_snapshot_hash": "64자리 sha256 hex",
  "labels": [
    {
      "label_id": "most_shade",
      "display_label": "그늘 많은 길",
      "evidence_status": "derived",
      "evidence": [
        {
          "feature": "shade_ratio",
          "value": 0.62,
          "unit": "ratio",
          "source": "building_shade"
        }
      ]
    }
  ],
  "provenance": {
    "labeler_kind": "deterministic_factual",
    "rubric_version": "route-traits-v1",
    "generated_at": "2026-07-24T12:00:00+09:00"
  }
}
```

`evidence_status`는 schema상 `observed`, `derived`, `unavailable` 중
하나다. 현재 결정적 생성기는 근거가 없는 긍정 라벨을 만들지 않고 해당
라벨을 생략한다. 결측을 0으로 바꾸거나 `그늘 많은 길`로 표시하지
않는다.

## 실행

먼저 AI 서버와 백엔드를 실행한다. 백엔드는 `ROUTE_MODE=ai`,
`AI_SERVER_URL`, 실제 경로·건물 공급자 설정과 32자 이상의
`LABELING_API_TOKEN`이 필요하다. 배치 실행 환경에도 같은 토큰을 넣되
값을 로그·채팅·Git에 남기지 않는다.

실제 경로 후보와 출발시각별 건물 그늘을 수집한다.

```powershell
$env:LABELING_API_TOKEN='<backend/.env와 같은 32자 이상 내부 토큰>'
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m labeling.generate_batch `
  --od-file ai\data\training\od_template.csv `
  --output-dir ai\data\training\judge_baseline
```

평가 prompt 파일의 SHA-256을 고정한 빈 judge 평가표를 만든다.

```powershell
.\.venv\Scripts\python.exe -m labeling.prepare_judge_baseline `
  --features ai\data\training\judge_baseline\route_features.jsonl `
  --output ai\data\training\judge_baseline\judge_labels.jsonl `
  --judge-run-id judge-20260724-a `
  --judge-source openai:model-name `
  --rubric-version route-profile-rubric-v1 `
  --prompt-file ai\data\training\judge_prompt.txt
```

이 명령은 평가를 실행하지 않고 `ready_for_training=false`인 빈 JSONL을
만든다. 외부 LLM 평가 절차가 모든 실제 후보와 6개 프로필에 대해
`evaluated_at`, `relevance`, `rationale`를 명시적으로 채워야 한다.
저장소에는 이 외부 평가 실행기가 없으며, 누락·stale 해시·불완전한
후보군·프롬프트 provenance가 섞인 입력은 학습기가 거부한다.

평가가 끝난 뒤 별도 baseline을 학습한다.

```powershell
.\.venv\Scripts\python.exe -m scoring.judge_baseline
```

학습기는 프로필별 최소 3개 OD를 요구하고, OD 전체를 단위로 결정적
holdout을 만들어 NDCG@3와 pairwise accuracy를 기록한다.
`rankers.judge-baseline.zip`의 manifest와 같은 위치의
`rankers.judge-baseline.metadata.json`에는 model tier, judge source,
rubric version, prompt hash, 평가 시각, 검증 지표가 남는다. 이 결과는
기술 baseline이며 실제 사용자 검증 모델로 표현하거나
`rankers.human-validated.zip`으로 자동 승격하지 않는다.
