"""공유 데이터셋(저장소 루트 data/) 로더. 프론트엔드와 동일한 JSON 을 단일 소스로 사용한다."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# backend/app/data/_loader.py → parents[3] = 저장소 루트(KT-10)
DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def load(name: str) -> Any:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)
