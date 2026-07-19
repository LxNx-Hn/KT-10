# 초기 경로 순위 라벨링과 학습

초기 모델의 정답은 가상 데이터가 아니라 9명 검토자가 실제 경로 후보를 비교해 만든다.

## 라벨링 단위

한 `task_id`는 동일한 출발지·도착지·날씨·프로필에서 생성된 두 후보(A/B)다.

- `preferred`: `left`, `right`, `tie`, `skip` 중 하나
- `skip`: 두 후보의 접근성 정보가 부족하거나 실제 비교가 불가능한 경우
- `reason_codes`: `stairs`, `elevator`, `low_floor_bus`, `walk_distance`, `safety`, `weather`, `other` 중 쉼표 구분
- 경로와 데이터 스냅샷은 반드시 함께 보관한다. 나중에 데이터가 갱신되어도 학습 근거를 재현할 수 있어야 한다.

## 파일

- `pairwise_labels.csv`: 검토 결과. 팀원이 직접 채운다.
- `route_features.jsonl`: 후보마다 8개 점수 피처와 경로/데이터 버전이 담긴 스냅샷이다.
- `train_pairwise.py`: 두 파일을 읽어 프로필별 선형 pairwise ranker JSON을 만든다.

학습 전에는 최소 9명의 서로 다른 `reviewer_id`가 있어야 하며, 같은 `task_id`의 다수결만 사용한다. `skip`과 동률은 학습에서 제외한다.
