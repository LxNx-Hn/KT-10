"""AI 단위 테스트는 로컬·운영 dotenv의 내부 토큰에 영향받지 않는다."""
import pytest
from collectors import odsay_instrumentation
from config import settings


@pytest.fixture(autouse=True)
def isolate_internal_service_token(monkeypatch):
    """토큰 계약 테스트만 필요한 값을 명시적으로 설정한다."""
    odsay_instrumentation.reset_daily_budget_state_for_tests()
    monkeypatch.setattr(settings, "AI_INTERNAL_SERVICE_TOKEN", "")
    monkeypatch.setattr(settings, "APP_ENV", "test")
