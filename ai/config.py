"""
AI 파이프라인 환경설정. API 키는 ai/.env 또는 환경변수에서만 읽는다.
ODsay/TMAP 키가 없으면 해당 수집기는 명시적으로 미설정 상태를 반환한다.
OSMnx 보행 네트워크 보완은 느린 외부 네트워크 작업이므로 명시적으로
활성화한 환경에서만 동작한다.
"""
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    # Backend 전용 내부 API 인증 토큰. Backend와 같은 값을 주입한다.
    # 비어 있으면 개발 편의를 위해 인증을 요구하지 않지만, production
    # 환경에서는 readiness가 실패한다.
    AI_INTERNAL_SERVICE_TOKEN: str = ""
    APP_ENV: Literal["development", "production", "test"] = "development"

    ODSAY_API_KEY: str = ""
    # 공공데이터포털 승인 API용 Decoding 키. 수집 배치가 요청 파라미터를
    # URL 인코딩하므로 Encoded 키를 별도로 보관하지 않는다.
    DATA_GO_KR_SERVICE_KEY: str = ""
    ODSAY_CACHE_DIR: str = ""
    ODSAY_CACHE_TTL_SECONDS: int = Field(
        default=1800,
        ge=60,
        le=31_536_000,
    )
    ODSAY_TIMEOUT_SECONDS: int = Field(default=20, ge=5, le=600)
    # ODsay 후보 수의 절대 상한. 요청이 이 값을 넘으면 조용히 자르지 않고
    # 명시적 오류를 반환한다.
    ODSAY_MAX_CANDIDATES: int = Field(default=10, ge=1, le=10)
    # AI 프로세스 전체에서 동시에 열 수 있는 ODsay HTTP 요청 수
    # (search와 loadLane 포함).
    ODSAY_MAX_CONCURRENT_REQUESTS: int = Field(default=3, ge=1, le=10)
    # ODsay의 30회 일일 한도를 넘지 않도록 신규 network 호출은 29회까지만
    # 원자적으로 예약한다. 캐시 hit는 이 상한을 소비하지 않는다.
    ODSAY_DAILY_BUDGET: int = Field(default=29, ge=1, le=1_000_000)
    # ODsay 호환 플러그인을 선택한 환경에서는 loadLane 정밀 선형을 유지한다.
    # 운영 기본 TMAP 경로에는 이 설정이 개입하지 않는다.
    ODSAY_LOAD_LANE_ENABLED: bool = True
    ELEVATION_CACHE_DIR: str = ""
    ELEVATION_CACHE_TTL_SECONDS: int = Field(
        default=2_592_000,
        ge=3600,
        le=31_536_000,
    )
    # 지역 DEM 범위 밖에서는 영속 캐시의 공개 GLO-90 COG 또는
    # Open-Meteo API를 사용한다.
    ELEVATION_DEM_DIR: str = ""
    # 운영 live 요청은 지역 DEM이 누락돼도 원격 COG 다운로드나 Open-Meteo
    # network 호출로 대체하지 않는다(경사 미확인으로 명시). 개발·배치 수집
    # 컨테이너만 이 값을 명시적으로 켜서 기존 fallback을 사용한다.
    ELEVATION_NETWORK_FALLBACK_ENABLED: bool = False
    # QGIS에서 생성한 부산 90m DEM. 운영 경사는 이 로컬 파일에서 조회한다.
    ELEVATION_REGIONAL_DEM_PATH: str = ""
    TMAP_API_KEY: str = ""
    TMAP_CACHE_DIR: str = ""
    # 배포 이미지에 포함한 검증 완료 TMAP 경사로 캐시. 사용자 요청은 이
    # 읽기 전용 fallback과 쓰기 캐시만 조회하며 TMAP 네트워크를 호출하지 않는다.
    TMAP_PRECOMPUTED_CACHE_DIR: str = str(
        Path(__file__).resolve().parent / "data" / "precomputed" / "tmap"
    )
    TMAP_CACHE_TTL_SECONDS: int = Field(
        default=1800,
        ge=60,
        # TMAP 약관상 저장 데이터는 24시간 이상 사용할 수 없다.
        le=86_399,
    )
    TMAP_MAX_CONCURRENT_REQUESTS: int = Field(default=3, ge=1, le=10)
    # ODsay가 없어도 동작하는 통합 대중교통 공급자. TMAP 한 번의 요청으로
    # 최대 10개 후보와 대중교통/보행 선형을 함께 받는다.
    TMAP_TRANSIT_CACHE_DIR: str = ""
    TMAP_TRANSIT_CACHE_TTL_SECONDS: int = Field(
        default=1800,
        ge=60,
        le=86_399,
    )
    TMAP_TRANSIT_TIMEOUT_SECONDS: int = Field(default=12, ge=3, le=120)
    TMAP_TRANSIT_MAX_CANDIDATES: int = Field(default=10, ge=1, le=10)
    TMAP_TRANSIT_MAX_CONCURRENT_REQUESTS: int = Field(
        default=3,
        ge=1,
        le=10,
    )
    # 부산 BIMS는 TMAP에 누락된 부산 시내버스 직행만 보완하는 선택 공급원이다.
    # 공식 노선 순서 캐시는 짧게 유지하며, 평균 정류장 시간이나 보행시간이
    # 없으면 후보를 만들지 않는다.
    BUS_SERVICE_KEY: str = ""
    BIMS_CACHE_TTL_SECONDS: int = Field(default=1800, ge=60, le=86_399)
    BIMS_TIMEOUT_SECONDS: int = Field(default=12, ge=5, le=60)
    BIMS_MAX_CONCURRENT_REQUESTS: int = Field(default=2, ge=1, le=10)
    BIMS_MAX_CANDIDATES: int = Field(default=10, ge=1, le=20)
    BIMS_WALK_SPEED_M_PER_MIN: float = Field(default=80.0, gt=0, le=200)
    # 운영 기본은 TMAP 단일 공급자다. ODsay는 한도가 작아
    # 명시적인 오프라인·호환 설정에서만 순서에 포함한다.
    # 지원 값은 odsay,tmap이며 중복·미지원 값은 readiness와 요청에서 거부한다.
    TRANSIT_PROVIDER_ORDER: str = "tmap"
    # 명시적으로 odsay,tmap 호환 순서를 선택한 환경에서만
    # ODsay에 선행 응답 기회를 주고, 지연 시 TMAP을 병렬 시작한다.
    TRANSIT_PROVIDER_HEDGE_SECONDS: float = Field(default=2.0, ge=0, le=5)
    TRANSIT_PROVIDER_TOTAL_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        ge=5,
        le=30,
    )
    # TMAP 대중교통 응답에 보행 선형이 없을 때만 수행하는 별도 보행
    # 보완 호출의 상한. 초과 시 공급자가 준 승하차 지점 연결은 estimated로
    # 유지하며, 전체 대중교통 후보를 지연시키지 않는다.
    TRANSIT_WALK_ENRICHMENT_TIMEOUT_SECONDS: float = Field(
        default=4.0,
        ge=0.5,
        le=10,
    )
    # 대중교통과 독립 보행 후보를 병렬 수집하는 전체 상한. 한 선택적
    # 수집기가 지연돼도 이미 확보한 실제 후보를 ALB 제한 안에 반환한다.
    ROUTE_COLLECTION_TOTAL_TIMEOUT_SECONDS: float = Field(
        default=11.0,
        ge=6,
        le=20,
    )
    # OpenRouteService의 wheelchair profile은 계단 회피뿐 아니라 OSM에
    # 기록된 노면·평탄도·폭·턱·경사·wheelchair 접근 제한을 함께 적용한다.
    # TMAP의 물리 경사로 안내점과 역할이 다르므로 별도 키로 관리한다.
    ORS_API_KEY: str = ""
    ORS_BASE_URL: AnyHttpUrl = "https://api.openrouteservice.org"
    ORS_CACHE_DIR: str = ""
    ORS_TIMEOUT_SECONDS: int = Field(default=20, ge=5, le=120)
    ORS_MAX_CONCURRENT_REQUESTS: int = Field(default=3, ge=1, le=10)
    ROUTE_FEATURE_CACHE_DIR: str = ""
    ROUTE_FEATURE_CACHE_TTL_SECONDS: int = Field(
        default=1800,
        ge=300,
        le=2_592_000,
    )
    OSMNX_WALK_GEOMETRY_ENABLED: bool = False
    # 일반 요청은 캐시 누락 시 백그라운드 준비 후 즉시 estimated를 반환한다.
    # 장시간 학습 수집 전용 컨테이너만 동기 준비를 명시적으로 선택한다.
    OSMNX_WALK_GEOMETRY_BLOCKING: bool = False
    OSMNX_OVERPASS_URL: AnyHttpUrl = "https://lambert.openstreetmap.de/api"
    OSMNX_REQUEST_TIMEOUT_SECONDS: int = Field(default=12, ge=3, le=60)
    OSMNX_WALK_GEOMETRY_TIMEOUT_SECONDS: int = Field(default=15, ge=3, le=60)
    # 초기 평가 baseline은 명시적으로 선택한 환경에서만 제공한다.
    # 기본값은 실제 사용자 라벨로 검증된 운영 모델이다.
    RANKER_TIER: Literal[
        "human_validated",
        "bootstrap_baseline",
    ] = "bootstrap_baseline"


settings = Settings()
