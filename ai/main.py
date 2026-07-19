"""
AI FastAPI 서버 진입점.

실행 (저장소 루트에서): uvicorn main:app --app-dir ai --host 0.0.0.0 --port 8001 --reload
--app-dir ai 로 ai/ 를 sys.path에 추가하여 내부 모듈(collectors, scoring 등)을
ai_pipeline 시절과 동일한 unprefixed import로 그대로 사용할 수 있게 한다.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.router import router

app = FastAPI(title="교통약자 경로추천 AI 서버")

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
