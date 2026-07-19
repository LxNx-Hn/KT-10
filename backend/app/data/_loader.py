"""공유 앱 데이터셋(저장소 루트 data/ai/) 로더.

``data/ai`` 는 프론트엔드와 백엔드가 함께 읽는 검증된 앱 입력이고,
``data/da`` 는 원시·분석 데이터다. 두 영역을 섞지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# backend/app/data/_loader.py → parents[3] = 저장소 루트(KT-10)
DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "ai"


def load(name: str) -> Any:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)
