"""서비스 권역(부산 전역)과 부산역 중심 MVP 검증 기준."""
from __future__ import annotations

DISTRICT = {
    "id": "busan",
    "name": "부산광역시 전역",
    "short_name": "부산",
    "center": {"lat": 35.1798, "lng": 129.0750},
    "bounds": {"min_lat": 34.8, "max_lat": 35.5, "min_lng": 128.7, "max_lng": 129.4},
    "mvp_area": "부산역 일대",
}

# 프론트엔드(Vite) 개발 서버 + 일반 로컬 오리진
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
]
