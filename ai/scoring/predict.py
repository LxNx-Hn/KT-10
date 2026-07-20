"""프로필별 학습 모델 추론과 후보 내 상대 선택 확률 계산."""
import numpy as np
import pandas as pd

from scoring.train import FEATURE_COLS

def _softmax(logits: np.ndarray) -> np.ndarray:
    """수치 안정 Softmax."""
    e = np.exp(logits - logits.max())
    return e / e.sum()


def predict_and_rank(
    rankers: dict,
    route_features_list: list[dict],
    profile: str,
    top_k: int = 3,
) -> list[dict]:
    """
    경로 후보 리스트를 받아 프로필별 추천 순위를 반환한다.

    Parameters
    ----------
    rankers : dict
        train_rankers()가 반환한 {profile: XGBRanker} 딕셔너리.
    route_features_list : list of dict
        경로 후보별 피처 딕셔너리 리스트.
        없는 피처 키는 NaN(미확인)으로 전달하여 실제 0과 구분한다.
    profile : str
        사용자 프로필 ("general" / "elderly" / "child" / "disabled").
    top_k : int
        반환할 상위 경로 수 (기본 3).

    Returns
    -------
    list of dict
        순위별 결과 리스트.
        각 dict: {"rank", "route_index", "xgb_score", "adjusted_score", "probability"}
    """
    ranker = rankers.get(profile)
    if ranker is None:
        raise ValueError(f"프로필 '{profile}'에 대한 모델이 없습니다.")

    # XGBoost는 NaN을 자체 결측 분기로 처리한다.
    X = pd.DataFrame([
        {col: np.nan if feat.get(col) is None else feat.get(col) for col in FEATURE_COLS}
        for feat in route_features_list
    ])

    # ① XGBoost 베이스 점수
    xgb_scores = ranker.predict(X)

    # 별도 규칙 가중치를 덧씌우지 않는다. 프로필별 모델의 출력만 사용한다.
    adjusted = xgb_scores.astype(float).copy()

    # 후보 집합 내 상대 선택 확률이며 절대 품질 점수가 아니다.
    probs      = _softmax(adjusted)
    ranked_idx = np.argsort(probs)[::-1][:top_k]

    return [
        {
            "rank":           rank + 1,
            "route_index":    int(idx),
            "xgb_score":      round(float(xgb_scores[idx]), 4),
            "adjusted_score": round(float(adjusted[idx]), 4),
            "probability":    round(float(probs[idx]), 4),
        }
        for rank, idx in enumerate(ranked_idx)
    ]
