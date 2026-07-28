"""요청 단위 correlation ID. 사용자 요청 하나의 하위 호출을 추적한다.

값은 비식별 문자열이며 좌표·토큰·키를 담지 않는다.
"""
from __future__ import annotations

import re
from contextvars import ContextVar
from uuid import uuid4

CORRELATION_HEADER = "X-Correlation-ID"
#: 로그 injection·과도한 길이를 막기 위한 허용 문자와 길이
_ALLOWED = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def normalize(value: str | None) -> str:
    """전달받은 ID가 형식에 맞으면 그대로 쓰고, 아니면 새로 만든다."""
    if value is not None and _ALLOWED.match(value):
        return value
    return uuid4().hex[:16]


def current() -> str:
    return correlation_id.get() or ""
