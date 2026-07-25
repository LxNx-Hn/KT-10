"""건물 높이 원본값의 공통 검증 계약."""
from __future__ import annotations

import math
from typing import Any

# 현재 완공된 건축물 범위를 넉넉히 포함하는 물리 안전 상한이다. 이보다 큰
# 공공데이터 값은 별도 검증 전까지 높이 미확인으로 유지해 행성 규모 그림자를
# 만들지 않는다.
MAX_PLAUSIBLE_BUILDING_HEIGHT_M = 1_000.0


def validated_building_height(value: Any) -> float | None:
    """양의 유한 실수이며 물리 안전 범위인 높이만 미터값으로 반환한다."""
    if value is None or isinstance(value, bool):
        return None
    try:
        height = float(value)
    except (TypeError, ValueError):
        return None
    if (
        not math.isfinite(height)
        or height <= 0
        or height > MAX_PLAUSIBLE_BUILDING_HEIGHT_M
    ):
        return None
    return height
