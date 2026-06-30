"""앱 설정: 데모 지역(부산진구) + CORS 허용 오리진."""
from __future__ import annotations

DISTRICT = {
    "id": "busanjin-gu",
    "name": "부산광역시 부산진구",
    "short_name": "부산진구",
    "center": {"lat": 35.1577, "lng": 129.0594},
}

# 프론트엔드(Vite) 개발 서버 + 일반 로컬 오리진
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
]
