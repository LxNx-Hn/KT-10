"""
AI FastAPI 서버 진입점.

실행 (저장소 루트에서): uvicorn main:app --app-dir ai --host 0.0.0.0 --port 8001 --reload
--app-dir ai 로 ai/ 를 sys.path에 추가하여 내부 모듈(collectors, scoring 등)을
ai_pipeline 시절과 동일한 unprefixed import로 그대로 사용할 수 있게 한다.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.router import _get_layers, router
from collectors.osmnx_collector import prepare_regional_graph
from config import settings

logger = logging.getLogger(__name__)
REQUIRED_LAYER_NAMES = frozenset({
    "shelter",
    "cctv",
    "aed",
    "wheelchair_charger",
    "dongbaekjeon",
    "smart_shelter",
    "subway",
    "crosswalk",
    "bus_stop",
})

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.OSMNX_WALK_GEOMETRY_ENABLED:
        try:
            graph_status = await asyncio.to_thread(prepare_regional_graph)
            if graph_status is not None:
                logger.info(
                    "부산 오프라인 보행 그래프 준비 완료: nodes=%s edges=%s",
                    graph_status["nodes"],
                    graph_status["edges"],
                )
        except Exception:
            logger.exception("부산 오프라인 보행 그래프 준비 실패")
            raise
    yield


app = FastAPI(
    title="교통약자 경로추천 AI 서버",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai"}


@app.get("/ready")
def readiness():
    """외부 경로 호출 없이 실제 후보 파이프라인의 시작 가능 상태를 확인한다."""
    odsay_key = settings.ODSAY_API_KEY.strip()
    odsay_ready = bool(
        odsay_key and not odsay_key.startswith("YOUR_")
    )
    layer_error = None
    try:
        layers = _get_layers()
        layer_names = set(layers) if isinstance(layers, dict) else set()
        layers_ready = (
            REQUIRED_LAYER_NAMES.issubset(layer_names)
            and all(len(layers[name]) > 0 for name in REQUIRED_LAYER_NAMES)
        )
        layer_count = len(layer_names)
    except Exception as exc:
        # Readiness는 외부에 경로·원본 파일명을 노출하지 않되 서버 로그에는
        # 원인을 보존한다. 메모리 고갈·프로세스 종료 계열 BaseException은 잡지 않는다.
        logger.exception("AI 공간 레이어 readiness 검증 실패")
        layers_ready = False
        layer_count = 0
        layer_error = type(exc).__name__

    ready = odsay_ready and layers_ready
    tmap_key = settings.TMAP_API_KEY.strip()
    exact_walk_geometry_configured = bool(
        (tmap_key and not tmap_key.startswith("YOUR_"))
        or settings.OSMNX_WALK_GEOMETRY_ENABLED
    )
    body = {
        "ready": ready,
        "service": "ai",
        "checks": {
            "odsay_configured": odsay_ready,
            "spatial_layers_loaded": layers_ready,
        },
        "capabilities": {
            "exact_walking_geometry_configured": (
                exact_walk_geometry_configured
            ),
        },
        "spatial_layer_count": layer_count,
        "model_artifact_required": False,
    }
    if layer_error is not None:
        body["layer_error"] = layer_error
    return body if ready else JSONResponse(status_code=503, content=body)
