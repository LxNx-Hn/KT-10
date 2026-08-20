"""ODsay 호출 계측·single-flight·동시성 상한·일일 예산 카운터.

키·원본 좌표·전체 mapObj·토큰은 기록하지 않는다. 식별에는 비식별
SHA-256 해시 접두어만 사용한다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from threading import Lock
from uuid import uuid4
from weakref import WeakKeyDictionary
from zoneinfo import ZoneInfo

from config import settings

log = logging.getLogger("collectors.odsay.metrics")

KST = ZoneInfo("Asia/Seoul")
_BUDGET_WARN_RATIOS = (0.7, 0.8, 0.9, 1.0)

correlation_id: ContextVar[str] = ContextVar("odsay_correlation_id", default="")
route_id_hash: ContextVar[str] = ContextVar("odsay_route_id_hash", default="")
provider_candidate_index: ContextVar[int | None] = ContextVar(
    "odsay_provider_candidate_index",
    default=None,
)


_ALLOWED_CORRELATION_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def adopt_correlation_id(value: str | None) -> str:
    """Backend가 전달한 correlation ID를 그대로 이어받는다.

    형식이 맞지 않거나 없으면 독립 실행으로 보고 새 ID를 만든다.
    """
    if value is not None and _ALLOWED_CORRELATION_ID.match(value):
        correlation_id.set(value)
        return value
    return new_correlation_id()


def ensure_correlation_id() -> str:
    """이미 설정된 ID가 있으면 유지하고, 없을 때만 새로 만든다."""
    existing = correlation_id.get()
    if existing:
        return existing
    return new_correlation_id()


def new_correlation_id() -> str:
    value = uuid4().hex[:12]
    correlation_id.set(value)
    return value


def anonymized_hash(material: str) -> str:
    """OD·mapObj 식별용 비식별 해시 접두어."""
    return sha256(material.encode("utf-8")).hexdigest()[:12]


class OdsayCallCounters:
    """프로세스 내 논리 호출·network 호출·절감 계측."""

    def __init__(self) -> None:
        self._guard = Lock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_guard", Lock()):
            self.logical_calls: dict[str, int] = {}
            self.network_calls: dict[str, int] = {}
            self.cache_hits: dict[str, int] = {}
            self.single_flight_followers: dict[str, int] = {}
            self.retries: dict[str, int] = {}
            # 실제 transport 기준 집계. cache hit·single-flight follower·
            # semaphore 대기 중 취소는 attempted에 포함되지 않는다.
            self.network_attempted: dict[str, int] = {}
            self.network_completed: dict[str, int] = {}
            self.network_failed: dict[str, int] = {}
            self.semaphore_wait_seconds: float = 0.0

    def record(
        self,
        endpoint: str,
        *,
        network: bool,
        cache_hit: bool,
        follower: bool,
        retry_count: int = 0,
        semaphore_wait: float = 0.0,
    ) -> None:
        with self._guard:
            self.logical_calls[endpoint] = self.logical_calls.get(endpoint, 0) + 1
            if network:
                self.network_calls[endpoint] = (
                    self.network_calls.get(endpoint, 0) + 1
                )
            if cache_hit:
                self.cache_hits[endpoint] = self.cache_hits.get(endpoint, 0) + 1
            if follower:
                self.single_flight_followers[endpoint] = (
                    self.single_flight_followers.get(endpoint, 0) + 1
                )
            if retry_count:
                self.retries[endpoint] = (
                    self.retries.get(endpoint, 0) + retry_count
                )
            self.semaphore_wait_seconds += semaphore_wait

    def record_network_attempt(self, endpoint: str) -> None:
        """실제 HTTP 전송 직전에 호출한다."""
        with self._guard:
            self.network_attempted[endpoint] = (
                self.network_attempted.get(endpoint, 0) + 1
            )

    def record_network_result(self, endpoint: str, *, completed: bool) -> None:
        with self._guard:
            target = (
                self.network_completed if completed else self.network_failed
            )
            target[endpoint] = target.get(endpoint, 0) + 1

    def snapshot(self) -> dict:
        with self._guard:
            return {
                "logical_calls": dict(self.logical_calls),
                "network_calls": dict(self.network_calls),
                "cache_hits": dict(self.cache_hits),
                "single_flight_followers": dict(self.single_flight_followers),
                "retries": dict(self.retries),
                "network_attempted": dict(self.network_attempted),
                "network_completed": dict(self.network_completed),
                "network_failed": dict(self.network_failed),
                "semaphore_wait_seconds": round(self.semaphore_wait_seconds, 4),
            }


counters = OdsayCallCounters()


def log_call(
    endpoint: str,
    *,
    identity_hash: str,
    cache_hit: bool,
    network: bool,
    follower: bool,
    duration_ms: float,
    outcome: str,
    call_site: str,
    retry_number: int = 0,
    http_status: int | None = None,
    semaphore_wait: float = 0.0,
) -> None:
    """단일 논리 호출의 구조화 로그. 키·좌표·mapObj 원문은 남기지 않는다."""
    log.info(
        "odsay_call corr=%s endpoint=%s site=%s route_id_hash=%s "
        "candidate_index=%s map_bounds_hash=%s cache=%s single_flight=%s "
        "semaphore_wait_ms=%.1f network_started=%s retry=%d status=%s "
        "duration_ms=%.1f outcome=%s",
        correlation_id.get() or "-",
        endpoint,
        call_site,
        route_id_hash.get() or "-",
        (
            provider_candidate_index.get()
            if provider_candidate_index.get() is not None
            else "-"
        ),
        identity_hash,
        "hit" if cache_hit else "miss",
        "follower" if follower else "leader",
        semaphore_wait * 1000,
        "yes" if network else "no",
        retry_number,
        http_status if http_status is not None else "-",
        duration_ms,
        outcome,
    )


def log_rank(route_id: str, final_rank: int) -> None:
    """순위 결정 로그. route ID 원문은 기록하지 않는다."""
    log.info(
        "odsay_route_rank corr=%s route_id_hash=%s final_rank=%d outcome=ranked",
        correlation_id.get() or "-",
        anonymized_hash(route_id),
        final_rank,
    )


# ── 일일 network 호출 hard cap (영속 cache 디렉터리에 날짜별 파일) ──

_budget_file_guard = Lock()
_warned_ratios: set[tuple[str, float]] = set()
_memory_budget_calls: dict[tuple[str, str], dict[str, int]] = {}
_provider_quota_blocks: set[tuple[str, str]] = set()


def _budget_path(today: str) -> Path | None:
    cache_dir = settings.ODSAY_CACHE_DIR.strip()
    if not cache_dir:
        return None
    return Path(cache_dir) / f"odsay-daily-counter-{today}.json"


def _budget_state_key(today: str) -> tuple[str, str]:
    return (settings.ODSAY_CACHE_DIR.strip(), today)


def _valid_calls(data: object) -> dict[str, int]:
    raw_calls = (
        data.get("observed_service_calls_today")
        if isinstance(data, dict)
        else None
    )
    return {
        str(name): int(value)
        for name, value in (
            raw_calls.items() if isinstance(raw_calls, dict) else []
        )
        if isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    }


def _read_budget_file(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _combined_budget_state(
    today: str,
    path: Path | None,
) -> tuple[dict[str, int], bool]:
    key = _budget_state_key(today)
    data = _read_budget_file(path)
    disk_calls = _valid_calls(data)
    memory_calls = _memory_budget_calls.get(key, {})
    calls = {
        name: max(disk_calls.get(name, 0), memory_calls.get(name, 0))
        for name in set(disk_calls) | set(memory_calls)
    }
    provider_blocked = bool(data.get("provider_quota_blocked")) or key in (
        _provider_quota_blocks
    )
    return calls, provider_blocked


def _budget_payload(
    today: str,
    calls: dict[str, int],
    *,
    provider_blocked: bool,
) -> dict:
    total = sum(calls.values())
    budget = settings.ODSAY_DAILY_BUDGET
    budget_blocked = total >= budget
    blocked_reason = (
        "provider_quota"
        if provider_blocked
        else "daily_budget"
        if budget_blocked
        else None
    )
    return {
        "date": today,
        "observed_service_calls_today": calls,
        "observed_total_today": total,
        "warning_only": False,
        "hard_limit": True,
        "budget": budget,
        "estimated_remaining_service_budget": max(0, budget - total),
        "network_calls_blocked": provider_blocked or budget_blocked,
        "blocked_reason": blocked_reason,
        "provider_quota_blocked": provider_blocked,
        "note": (
            "캐시 조회는 허용하지만 새 ODsay network 호출은 일일 hard cap 또는 "
            "공급자 quota 응답 이후 차단한다. 카운터는 이 AI 인스턴스가 관측한 "
            "호출만 포함한다."
        ),
    }


def _write_budget_file(path: Path | None, data: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def record_network_call(endpoint: str) -> bool:
    """ODsay network 호출 슬롯을 날짜별 hard cap 안에서 원자적으로 예약한다.

    ``True``일 때만 실제 HTTP transport를 시작한다. 캐시 디렉터리가 없거나
    파일 저장이 실패해도 프로세스 메모리 카운터로 29회 상한을 유지한다.
    """
    today = datetime.now(KST).strftime("%Y%m%d")
    path = _budget_path(today)
    allowed = False
    total = 0
    try:
        with _budget_file_guard:
            calls, provider_blocked = _combined_budget_state(today, path)
            total = sum(calls.values())
            if not provider_blocked and total < settings.ODSAY_DAILY_BUDGET:
                calls[endpoint] = calls.get(endpoint, 0) + 1
                total += 1
                allowed = True
            key = _budget_state_key(today)
            _memory_budget_calls[key] = dict(calls)
            data = _budget_payload(
                today,
                calls,
                provider_blocked=provider_blocked,
            )
            try:
                _write_budget_file(path, data)
            except (OSError, ValueError, TypeError, OverflowError) as exc:
                log.warning(
                    "ODsay 일일 hard-cap 파일 저장 실패 (%s)",
                    type(exc).__name__,
                )
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        # 메모리 상태도 갱신하지 못했다면 안전하게 새 호출을 차단한다.
        log.error("ODsay 일일 hard-cap 예약 실패 (%s)", type(exc).__name__)
        return False
    for ratio in _BUDGET_WARN_RATIOS:
        threshold = settings.ODSAY_DAILY_BUDGET * ratio
        key = (today, ratio)
        if total >= threshold and key not in _warned_ratios:
            _warned_ratios.add(key)
            log.warning(
                "ODsay 일일 관측 호출이 경고 기준의 %d%%에 도달 "
                "(observed=%d hard_limit=%d, limit 도달 시 신규 호출 차단)",
                int(ratio * 100),
                total,
                settings.ODSAY_DAILY_BUDGET,
            )
    return allowed


def block_network_calls_for_provider_quota() -> None:
    """ODsay가 quota 초과를 반환하면 KST 날짜가 바뀔 때까지 신규 호출을 막는다."""
    today = datetime.now(KST).strftime("%Y%m%d")
    path = _budget_path(today)
    with _budget_file_guard:
        calls, _ = _combined_budget_state(today, path)
        key = _budget_state_key(today)
        _memory_budget_calls[key] = dict(calls)
        _provider_quota_blocks.add(key)
        data = _budget_payload(today, calls, provider_blocked=True)
        try:
            _write_budget_file(path, data)
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            log.warning(
                "ODsay provider quota 차단 파일 저장 실패 (%s)",
                type(exc).__name__,
            )


def read_daily_counter() -> dict | None:
    today = datetime.now(KST).strftime("%Y%m%d")
    path = _budget_path(today)
    with _budget_file_guard:
        calls, provider_blocked = _combined_budget_state(today, path)
        if not calls and not provider_blocked and (path is None or not path.is_file()):
            return None
        return _budget_payload(
            today,
            calls,
            provider_blocked=provider_blocked,
        )


def reset_daily_budget_state_for_tests() -> None:
    """테스트 간 프로세스 메모리 hard-cap 상태가 섞이지 않게 초기화한다."""
    with _budget_file_guard:
        _memory_budget_calls.clear()
        _provider_quota_blocks.clear()
        _warned_ratios.clear()


# ── 이벤트 루프별 semaphore와 single-flight ──

_loop_semaphores: WeakKeyDictionary = WeakKeyDictionary()
_loop_semaphores_guard = Lock()
_loop_flights: WeakKeyDictionary = WeakKeyDictionary()
_loop_flights_guard = Lock()


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    with _loop_semaphores_guard:
        semaphore = _loop_semaphores.get(loop)
        if semaphore is None:
            semaphore = asyncio.Semaphore(
                settings.ODSAY_MAX_CONCURRENT_REQUESTS
            )
            _loop_semaphores[loop] = semaphore
        return semaphore


async def with_concurrency_limit(
    factory: Callable[[], Awaitable],
):
    """ODsay HTTP 요청 전역 동시성 상한을 적용하고 대기시간을 계측한다."""
    semaphore = _semaphore()
    waited_from = time.monotonic()
    async with semaphore:
        wait_seconds = time.monotonic() - waited_from
        return await factory(), wait_seconds


def _flights() -> dict:
    loop = asyncio.get_running_loop()
    with _loop_flights_guard:
        flights = _loop_flights.get(loop)
        if flights is None:
            flights = {}
            _loop_flights[loop] = flights
        return flights


class _Flight:
    """진행 중인 단일 실행과 그 결과를 기다리는 대기자 수."""

    __slots__ = ("task", "waiters")

    def __init__(self, task: asyncio.Task):
        self.task = task
        self.waiters = 0


async def single_flight(
    key: str,
    factory: Callable[[], Awaitable],
) -> tuple[object, bool]:
    """같은 key의 동시 요청을 leader 한 번의 실행으로 합친다.

    leader 실행은 독립 Task로 수행하므로 follower 하나가 취소돼도 남은
    대기자를 위해 계속 진행한다. 반대로 마지막 대기자까지 취소되면 결과를
    쓸 곳이 없으므로 실행을 취소해 불필요한 공급자 호출을 만들지 않는다.
    leader 오류는 모든 대기자에게 그대로 전달되고 in-flight 상태는 완료
    즉시 제거된다.
    """
    flights = _flights()
    entry = flights.get(key)
    follower = entry is not None
    if entry is None:
        loop = asyncio.get_running_loop()
        entry = _Flight(loop.create_task(factory()))
        flights[key] = entry
        entry.task.add_done_callback(
            lambda finished, flight_key=key, flight=entry: (
                flights.pop(flight_key, None)
                if flights.get(flight_key) is flight
                else None
            )
        )
    entry.waiters += 1
    try:
        return await asyncio.shield(entry.task), follower
    except asyncio.CancelledError:
        if entry.waiters <= 1 and not entry.task.done():
            entry.task.cancel()
        raise
    finally:
        entry.waiters -= 1
