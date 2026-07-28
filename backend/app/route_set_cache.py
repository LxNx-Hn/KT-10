"""시간·조건 변경 시 공급자를 다시 호출하지 않기 위한 후보 경로 캐시."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
import secrets
from threading import Lock
import time

from .models import RouteCandidate, WeatherCondition

# v2: 후보 수 metadata·revision·대중교통 지연 정밀화 상태 추가.
ROUTE_SET_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class CachedRouteSet:
    candidates: list[RouteCandidate]
    weather: WeatherCondition
    # originalRequestedTopN / effectiveTopN / collectedCandidateCount /
    # aiMaxCandidates / schemaVersion 등 생성 시점 후보 수 권위 기록.
    metadata: dict = field(default_factory=dict)
    revision: int = 0


class StaleRouteSetRevision(RuntimeError):
    """이전 revision 기반 저장 시도가 최신 상태를 덮는 것을 차단했다."""


class RouteSetCache:
    """프로세스 안에서 짧게 유지하는 bounded TTL 캐시.

    응답에는 임의 토큰만 노출하고, 모델 피처·geometry가 포함된 원본 후보는
    서버 안에 보관한다. 클라이언트가 경로를 다시 보내 모델 입력을 바꾸는
    구조를 피하기 위한 캐시다.

    동시 갱신 보호:
    - ``locked(token)``: refinement·그늘 갱신 같은 read-modify-write 작업이
      토큰 단위로 직렬화되는 asyncio 잠금.
    - ``replace(..., expected_revision=...)``: 전체 교체 시 revision CAS로
      오래된 후보 배열이 최신 geometry를 덮지 않게 한다.
    - ``update_candidate``: 특정 route ID 하나의 필드만 원자적으로 수정한다.
    """

    def __init__(self, *, ttl_seconds: int = 30 * 60, max_entries: int = 256):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, CachedRouteSet]] = OrderedDict()
        self._lock = Lock()
        self._token_locks: dict[str, asyncio.Lock] = {}
        self._token_lock_waiters: dict[str, int] = {}
        self._token_locks_guard = Lock()

    @staticmethod
    def _copy(entry: CachedRouteSet) -> CachedRouteSet:
        return CachedRouteSet(
            candidates=[
                candidate.model_copy(deep=True)
                for candidate in entry.candidates
            ],
            weather=entry.weather.model_copy(deep=True),
            metadata=dict(entry.metadata),
            revision=entry.revision,
        )

    def _remove_expired(self, now: float) -> None:
        expired = [
            token
            for token, (created_at, _) in self._entries.items()
            if now - created_at > self.ttl_seconds
        ]
        for token in expired:
            self._entries.pop(token, None)
        # 잠금 항목은 대기자 수가 0이 될 때 _release_token_lock이 정리한다.
        # 여기서 먼저 제거하면 이미 대기 중인 코루틴과 다른 잠금 객체가
        # 만들어져 같은 임계 구역에 둘이 동시에 들어갈 수 있다.
        self._discard_unused_token_locks()

    def _discard_unused_token_locks(self) -> None:
        with self._token_locks_guard:
            for token in [
                token
                for token in self._token_locks
                if self._token_lock_waiters.get(token, 0) <= 0
                and token not in self._entries
            ]:
                self._token_locks.pop(token, None)
                self._token_lock_waiters.pop(token, None)

    def _claim_token_lock(self, token: str) -> asyncio.Lock | None:
        """존재하는 route-set에 대해서만 잠금을 만들고 대기자를 등록한다.

        존재하지 않는 token은 잠금을 만들지 않으므로, 임의 token 요청이
        서버 메모리의 잠금 맵을 늘릴 수 없다.

        잠금 순서는 항상 entries guard → token locks guard이며 모든
        호출부가 이 순서를 지킨다.
        """
        now = time.monotonic()
        with self._lock:
            self._remove_expired(now)
            if token not in self._entries:
                return None
            with self._token_locks_guard:
                lock = self._token_locks.get(token)
                if lock is None:
                    lock = asyncio.Lock()
                    self._token_locks[token] = lock
                self._token_lock_waiters[token] = (
                    self._token_lock_waiters.get(token, 0) + 1
                )
                return lock

    def _release_token_lock(self, token: str) -> None:
        """마지막 사용자가 떠나면 잠금 항목 자체를 정리한다."""
        with self._token_locks_guard:
            waiters = self._token_lock_waiters.get(token, 0) - 1
            if waiters > 0:
                self._token_lock_waiters[token] = waiters
                return
            self._token_lock_waiters.pop(token, None)
            self._token_locks.pop(token, None)

    @asynccontextmanager
    async def lock_existing(self, token: str):
        """존재하는 route-set을 잠그고 최신 사본을 제공한다.

        token이 없거나 잠금 대기 중 만료되면 ``None``을 넘겨준다.
        외부 공급자 호출 전체를 이 잠금 안에서 기다리지 않는다.
        """
        lock = self._claim_token_lock(token)
        if lock is None:
            yield None
            return
        try:
            async with lock:
                # 잠금을 기다리는 동안 만료·삭제됐을 수 있다.
                yield self.get(token)
        finally:
            self._release_token_lock(token)

    def put(
        self,
        candidates: list[RouteCandidate],
        weather: WeatherCondition,
        *,
        metadata: dict | None = None,
    ) -> str:
        entry = CachedRouteSet(
            candidates=candidates,
            weather=weather,
            metadata={
                "schemaVersion": ROUTE_SET_SCHEMA_VERSION,
                "createdAt": datetime.now(UTC).isoformat(),
                **(metadata or {}),
            },
            revision=1,
        )
        token = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self._lock:
            self._remove_expired(now)
            self._entries[token] = (now, self._copy(entry))
            self._entries.move_to_end(token)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            self._discard_unused_token_locks()
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
        *,
        expected_revision: int | None = None,
    ) -> bool:
        now = time.monotonic()
        with self._lock:
            self._remove_expired(now)
            existing = self._entries.get(token)
            if existing is None:
                return False
            current = existing[1]
            if (
                expected_revision is not None
                and current.revision != expected_revision
            ):
                raise StaleRouteSetRevision(
                    "route-set이 이미 더 새로운 revision으로 갱신되었습니다."
                )
            entry = CachedRouteSet(
                candidates=candidates,
                weather=weather,
                metadata=dict(current.metadata),
                revision=current.revision + 1,
            )
            self._entries[token] = (now, self._copy(entry))
            self._entries.move_to_end(token)
            return True

    def update_candidate(
        self,
        token: str,
        route_id: str,
        mutate: Callable[[RouteCandidate], None],
    ) -> CachedRouteSet | None:
        """특정 route ID 후보만 원자적으로 수정한다.

        후보 순서·다른 후보·weather·metadata는 변경하지 않는다.
        """
        now = time.monotonic()
        with self._lock:
            self._remove_expired(now)
            existing = self._entries.get(token)
            if existing is None:
                return None
            current = existing[1]
            target = next(
                (
                    candidate
                    for candidate in current.candidates
                    if candidate.id == route_id
                ),
                None,
            )
            if target is None:
                return None
            mutate(target)
            updated = CachedRouteSet(
                candidates=current.candidates,
                weather=current.weather,
                metadata=current.metadata,
                revision=current.revision + 1,
            )
            self._entries[token] = (existing[0], updated)
            self._entries.move_to_end(token)
            return self._copy(updated)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
        with self._token_locks_guard:
            self._token_locks.clear()
            self._token_lock_waiters.clear()


route_set_cache = RouteSetCache()
