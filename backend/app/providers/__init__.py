"""
데이터 프로바이더: 키가 있으면 라이브 외부 API, 없으면 mock 폴백.
외부 호출 실패 시에도 예외를 던지지 않고 mock 으로 폴백하여 서비스 가용성을 유지한다.
예외는 클래스명만 로깅하고 URL/키가 포함될 수 있는 상세 메시지는 남기지 않는다.
"""
from .places import search_places  # noqa: F401
from .weather import get_current_weather  # noqa: F401
from .odsay import get_public_transit_candidates  # noqa: F401
