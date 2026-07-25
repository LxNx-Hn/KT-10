"""시간·조건 변경 시 공급자를 다시 호출하지 않기 위한 후보 경로 캐시."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import secrets
from threading import Lock
import time

from .models import RouteCandidate, WeatherCondition


@dataclass(frozen=True)
class CachedRouteSet:
    candidates: list[RouteCandidate]
    weather: WeatherCondition


class RouteSetCache:
    """프로세스 안에서 짧게 유지하는 bounded TTL 캐시.

    응답에는 임의 토큰만 노출하고, 모델 피처·geometry가 포함된 원본 후보는
    서버 안에 보관한다. 클라이언트가 경로를 다시 보내 모델 입력을 바꾸는
    구조를 피하기 위한 캐시다.
    """

    def __init__(self, *, ttl_seconds: int = 30 * 60, max_entries: int = 256):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, CachedRouteSet]] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def _copy(entry: CachedRouteSet) -> CachedRouteSet:
        return CachedRouteSet(
            candidates=[
                candidate.model_copy(deep=True)
                for candidate in entry.candidates
            ],
            weather=entry.weather.model_copy(deep=True),
        )

    def _remove_expired(self, now: float) -> None:
        expired = [
            token
            for token, (created_at, _) in self._entries.items()
            if now - created_at > self.ttl_seconds
        ]
        for token in expired:
            self._entries.pop(token, None)

    def put(
        self,
        candidates: list[RouteCandidate],
        weather: WeatherCondition,
    ) -> str:
        entry = CachedRouteSet(candidates=candidates, weather=weather)
        token = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self._lock:
            self._remove_expired(now)
            self._entries[token] = (now, self._copy(entry))
            self._entries.move_to_end(token)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return token

    def get(self, token: str) -> CachedRouteSet | None:
        now = time.monotonic()
        with self._lock:
            self._remove_expired(now)
            cached = self._entries.get(token)
            if cached is None:
                return None
            self._entries.move_to_end(token)
            return self._copy(cached[1])

    def replace(
        self,
        token: str,
        candidates: list[RouteCandidate],
        weather: WeatherCondition,
    ) -> bool:
        now = time.monotonic()
        entry = CachedRouteSet(candidates=candidates, weather=weather)
        with self._lock:
            self._remove_expired(now)
            if token not in self._entries:
                return False
            self._entries[token] = (now, self._copy(entry))
            self._entries.move_to_end(token)
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


route_set_cache = RouteSetCache()
