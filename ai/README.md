# AI 피처 추출 및 스코어링 파이프라인

부산 교통약자 맞춤형 경로 추천 서비스의 AI 파이프라인입니다.

## 설치

```bash
pip install -r requirements.txt
```

## 실행 순서

### 1. 가상 데이터로 파이프라인 검증 (데이터 없이 바로 실행 가능)

```python
from preprocessing.load_layers import load_all_layers
from features.extractor import extract_route_features
from scoring.train import train_rankers
from scoring.predict import predict_and_rank
from scoring.explain import generate_reasons
import pandas as pd

# 레이어 로딩
layers = load_all_layers()

# 경로 피처 추출 (실제 API 경로 좌표로 교체)
route_coords = [(35.1626, 129.0530), (35.1578, 129.0594)]
spatial_feats = extract_route_features(route_coords, layers)

# 모델 학습 (가상 데이터 기반)
rankers = train_rankers()

# 추론
route_features_list = [spatial_feats]   # 실제로는 경로 후보 3개
result = predict_and_rank(rankers, route_features_list, profile="elderly")
print(result)

# 추천 이유 생성
X_route = pd.DataFrame([{col: spatial_feats.get(col, 0) for col in rankers["elderly"].feature_names_in_}])
reasons = generate_reasons(rankers["elderly"], X_route)
print(reasons)
```

### 2. 실데이터 연동 후 교체 방법

`scoring/train.py` 의 `generate_synthetic_data()` 함수를 실제 데이터 로딩으로 교체합니다.
함수 반환 타입(pandas DataFrame, 컬럼 구조)은 유지해야 합니다.

### 3. 테스트 실행

```bash
pytest tests/ -v
```

## 레이어 캐시 초기화

데이터 파일이 변경되면 캐시를 재생성합니다.

```python
from preprocessing.load_layers import load_all_layers
layers = load_all_layers(use_cache=False)
```

## 주의사항

- `bus_stop_national_csv_processed.xlsx` 는 전국 데이터. 부산 필터링은 `load_bus_stop()` 내부에서 자동 처리
- CCTV 두 파일은 데이터팀 통합 파일 수신 전까지 임시 병합 사용
- `generate_synthetic_data()` 는 실데이터 수신 후 반드시 교체할 것
