"""
강화학습 환경.

State  : 경로 후보들의 피처 벡터 (flatten)
Action : 경로 후보 중 하나 선택 (0, 1, 2, ...)
Reward : 선택한 경로의 XGBoost 점수 (0~1 정규화)

XGBoost가 경로마다 점수를 매기고,
RL 에이전트가 그 점수를 보상으로 받아 최적 선택 정책을 학습한다.
"""
import numpy as np
import pandas as pd

from scoring.train import FEATURE_COLS


class RouteSelectionEnv:

    def __init__(self, rankers: dict, profile: str):
        self.rankers = rankers
        self.profile = profile
        self.routes = []

    @property
    def n_actions(self):
        return len(self.routes)

    @property
    def state_dim(self):
        return len(FEATURE_COLS) * max(self.n_actions, 1)

    def reset(self, route_features_list: list) -> np.ndarray:
        self.routes = route_features_list
        return self._state()

    def step(self, action: int) -> tuple:
        """선택한 경로의 XGBoost 점수를 Reward로 반환."""
        selected = self.routes[action]
        X = pd.DataFrame([{col: selected.get(col, 0) for col in FEATURE_COLS}])
        xgb_score = float(self.rankers[self.profile].predict(X)[0])
        reward = np.clip(xgb_score, 0.0, 1.0)
        return self._state(), reward, True  # done=True (1스텝 종료)

    def _state(self) -> np.ndarray:
        vecs = [[f.get(col, 0) for col in FEATURE_COLS] for f in self.routes]
        return np.array(vecs, dtype=np.float32).flatten()
