"""점수 계산 보조 함수. TS 구현(Math.round 반올림)과 동일하게 동작하도록 구현."""
import math


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return min(hi, max(lo, v))


def avg(nums: list[float], fallback: float = 0.0) -> float:
    return sum(nums) / len(nums) if nums else fallback


def round1(v: float) -> float:
    """소수 1자리 반올림(0.5는 올림). JS의 Math.round(v*10)/10 과 동일."""
    return math.floor(v * 10 + 0.5) / 10
