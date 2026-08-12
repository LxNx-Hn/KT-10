"""배포용 단일 환경파일을 생성·병합·검증한다.

비밀값은 출력하지 않는다. 외부 키는 기존 하위 .env에서 선택적으로 가져오고,
서비스 내부 비밀값은 안전한 난수로 생성한다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
from urllib.parse import urlparse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.production.example"
TARGET = ROOT / ".env.production"
BOOTSTRAP_MODEL = ROOT / "ai" / "data" / "rankers.bootstrap-baseline.zip"
BOOTSTRAP_METADATA = (
    ROOT / "ai" / "data" / "rankers.bootstrap-baseline.metadata.json"
)
MODEL_PROFILES = {
    "general",
    "elderly",
    "child",
    "youth",
    "disabled",
    "pregnant",
}
GENERATED = {
    "POSTGRES_PASSWORD": 24,
    "SESSION_SECRET": 48,
    "TRAINING_ANONYMIZATION_SALT": 32,
    "LABELING_API_TOKEN": 48,
    # Backend와 AI 사이의 내부 호출을 보호하는 공유 비밀이다. 운영 Compose는
    # 이 값이 없으면 기동하지 않으므로 단일 .env.production에서 함께 생성한다.
    "AI_INTERNAL_SERVICE_TOKEN": 48,
    # 탈퇴 기록의 반복 탈퇴 판별 해시 salt. 추측 가능한 값이면 회원번호가
    # 역산되므로 사람이 손으로 짓지 않고 생성한다. 아래 중복 금지 검사가
    # 세션·학습 salt 재사용도 함께 막는다.
    "WITHDRAWAL_HASH_SALT": 32,
}
MIN_SECRET_LENGTHS = {
    "POSTGRES_PASSWORD": 16,
    "SESSION_SECRET": 32,
    "TRAINING_ANONYMIZATION_SALT": 16,
    "LABELING_API_TOKEN": 32,
    "AI_INTERNAL_SERVICE_TOKEN": 32,
    # Settings.withdrawal_hashing_configured와 같은 하한이다.
    "WITHDRAWAL_HASH_SALT": 16,
}
REQUIRED_EXTERNAL = (
    "VITE_KAKAO_MAP_KEY",
    "KAKAO_REST_API_KEY",
    "KAKAO_OAUTH_CLIENT_SECRET",
    "ODSAY_API_KEY",
    "ORS_API_KEY",
    "VWORLD_API_KEY",
    "OPENWEATHER_API_KEY",
    "BUS_SERVICE_KEY",
)
IMPORT_SOURCES = {
    "VITE_KAKAO_MAP_KEY": ROOT / "frontend" / ".env",
    "KAKAO_REST_API_KEY": ROOT / "backend" / ".env",
    "KAKAO_OAUTH_CLIENT_SECRET": ROOT / "backend" / ".env",
    "ODSAY_API_KEY": ROOT / "ai" / ".env",
    "TMAP_API_KEY": ROOT / "ai" / ".env",
    "ORS_API_KEY": ROOT / "ai" / ".env",
    "VWORLD_API_KEY": ROOT / "backend" / ".env",
    "OPENWEATHER_API_KEY": ROOT / "backend" / ".env",
    "BUS_SERVICE_KEY": ROOT / "backend" / ".env",
}
# 외부 전달 파일에서 쓰일 수 있는 명칭을 정규화한다. JavaScript 키와
# REST 키는 서로 대체할 수 없으므로 의도적으로 별도 항목으로 유지한다.
IMPORT_ALIASES = {
    "VITE_KAKAO_MAP_KEY": ("VITE_KAKAO_MAP_KEY", "KAKAO_JAVASCRIPT_KEY"),
    "KAKAO_REST_API_KEY": ("KAKAO_REST_API_KEY", "KAKAO_REST_API"),
    "KAKAO_OAUTH_CLIENT_SECRET": ("KAKAO_OAUTH_CLIENT_SECRET",),
    "ODSAY_API_KEY": ("ODSAY_API_KEY",),
    "TMAP_API_KEY": ("TMAP_API_KEY",),
    "ORS_API_KEY": ("ORS_API_KEY",),
    "VWORLD_API_KEY": ("VWORLD_API_KEY",),
    "OPENWEATHER_API_KEY": ("OPENWEATHER_API_KEY",),
    "BUS_SERVICE_KEY": ("BUS_SERVICE_KEY", "BUSAN_BUS_API_KEY"),
}


def _values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _render(template: str, values: dict[str, str]) -> str:
    lines: list[str] = []
    for raw in template.splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            lines.append(raw)
            continue
        key = raw.split("=", 1)[0].strip()
        lines.append(f"{key}={values.get(key, raw.split('=', 1)[1])}")
    return "\n".join(lines) + "\n"


def _first_present(values: dict[str, str], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        value = values.get(alias, "")
        if value:
            return value
    return ""


def _bootstrap_artifact_ready() -> bool:
    if not BOOTSTRAP_MODEL.is_file() or not BOOTSTRAP_METADATA.is_file():
        return False
    try:
        metadata = json.loads(BOOTSTRAP_METADATA.read_text(encoding="utf-8"))
        with zipfile.ZipFile(BOOTSTRAP_MODEL) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            archived_profiles = {
                Path(name).stem
                for name in archive.namelist()
                if name.startswith("models/") and name.endswith(".json")
            }
    except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile):
        return False
    return bool(
        metadata.get("model_tier") == "bootstrap_baseline"
        and set(metadata.get("profiles", ())) == MODEL_PROFILES
        and manifest.get("model_tier") == "bootstrap_baseline"
        and set(manifest.get("profiles", ())) == MODEL_PROFILES
        and archived_profiles == MODEL_PROFILES
    )


def prepare(import_existing: bool, import_env: Path | None = None) -> None:
    if not EXAMPLE.exists():
        raise SystemExit(".env.production.example 파일이 없습니다.")
    if import_env is not None and not import_env.is_file():
        raise SystemExit("가져올 환경파일이 없습니다.")
    template = EXAMPLE.read_text(encoding="utf-8")
    values = _values(EXAMPLE)
    values.update(_values(TARGET))
    if import_existing:
        source_cache = {
            path: _values(path) for path in set(IMPORT_SOURCES.values())
        }
        for key, path in IMPORT_SOURCES.items():
            if not values.get(key):
                values[key] = source_cache[path].get(key, "")
    if import_env is not None:
        imported = _values(import_env)
        for key, aliases in IMPORT_ALIASES.items():
            imported_value = _first_present(imported, aliases)
            if imported_value:
                # 사용자가 명시한 파일의 비어 있지 않은 값은 기존
                # 하위 .env와 이전 production 값을 덮어써 키 회전을
                # 가능하게 한다. 없는 키는 기존 값을 보존한다.
                values[key] = imported_value
    for key, size in GENERATED.items():
        if not values.get(key):
            values[key] = secrets.token_urlsafe(size)
    if values.get("PUBLIC_ORIGIN") == "https://your-domain.example":
        values["PUBLIC_ORIGIN"] = "http://localhost:8080"
    TARGET.write_text(_render(template, values), encoding="utf-8")
    print(".env.production 준비 완료 (비밀값은 출력하지 않음)")


def check() -> None:
    values = _values(TARGET)
    missing = [
        key for key in (*REQUIRED_EXTERNAL, *GENERATED)
        if not values.get(key) or values[key].startswith("YOUR_")
    ]
    origin = values.get("PUBLIC_ORIGIN", "")
    parsed = urlparse(origin)
    try:
        _ = parsed.port
        invalid_origin_port = False
    except ValueError:
        invalid_origin_port = True
    if (
        invalid_origin_port
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
        or origin.endswith("/")
    ):
        missing.append("PUBLIC_ORIGIN(valid URL)")
    if origin.startswith("http://") and parsed.hostname not in {"localhost", "127.0.0.1"}:
        missing.append("PUBLIC_ORIGIN(HTTPS required outside localhost)")
    for key, minimum in MIN_SECRET_LENGTHS.items():
        if values.get(key) and len(values[key]) < minimum:
            missing.append(f"{key}(minimum {minimum} characters)")
    generated_values = [
        values.get(key, "")
        for key in GENERATED
        if values.get(key)
    ]
    if len(generated_values) != len(set(generated_values)):
        missing.append("generated secrets(must be distinct)")
    if (
        values.get("VITE_KAKAO_MAP_KEY")
        and values.get("VITE_KAKAO_MAP_KEY")
        == values.get("KAKAO_REST_API_KEY")
    ):
        missing.append("Kakao JavaScript/REST keys(must be distinct)")
    try:
        port = int(values.get("PORT", ""))
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        missing.append("PORT(1..65535)")
    bind_address = values.get("BIND_ADDRESS", "127.0.0.1")
    if bind_address not in {"127.0.0.1", "0.0.0.0"}:
        missing.append("BIND_ADDRESS(127.0.0.1 or 0.0.0.0)")
    try:
        request_timeout = float(values.get("REQUEST_TIMEOUT", ""))
    except ValueError:
        request_timeout = 0
    if not 0 < request_timeout <= 60:
        missing.append("REQUEST_TIMEOUT(>0 and <=60)")
    if values.get("ROUTE_MODE") not in {"live", "ai"}:
        missing.append("ROUTE_MODE(live or ai)")
    if values.get("BUILDING_SOURCE") != "vworld":
        missing.append("BUILDING_SOURCE(vworld)")
    ranker_tier = values.get("RANKER_TIER")
    if ranker_tier not in {"human_validated", "bootstrap_baseline"}:
        missing.append("RANKER_TIER(human_validated or bootstrap_baseline)")
    if ranker_tier == "bootstrap_baseline":
        if values.get("ROUTE_MODE") != "ai":
            missing.append("ROUTE_MODE(ai required for bootstrap_baseline)")
        if not _bootstrap_artifact_ready():
            missing.append("bootstrap_baseline(model artifact contract)")
    if values.get("OSMNX_WALK_GEOMETRY_ENABLED", "").lower() not in {
        "true",
        "false",
    }:
        missing.append("OSMNX_WALK_GEOMETRY_ENABLED(boolean)")
    for key in (
        "OSMNX_REQUEST_TIMEOUT_SECONDS",
        "OSMNX_WALK_GEOMETRY_TIMEOUT_SECONDS",
    ):
        try:
            timeout_seconds = int(values.get(key, ""))
        except ValueError:
            timeout_seconds = 0
        if not 3 <= timeout_seconds <= 60:
            missing.append(f"{key}(3..60)")
    overpass_url = urlparse(values.get("OSMNX_OVERPASS_URL", ""))
    if (
        overpass_url.scheme != "https"
        or not overpass_url.hostname
        or overpass_url.username is not None
        or overpass_url.password is not None
        or overpass_url.params
        or overpass_url.query
        or overpass_url.fragment
    ):
        missing.append("OSMNX_OVERPASS_URL(valid HTTPS URL)")
    try:
        vworld_cache_ttl = int(values.get("VWORLD_CACHE_TTL_HOURS", ""))
    except ValueError:
        vworld_cache_ttl = 0
    if not 1 <= vworld_cache_ttl <= 24 * 365:
        missing.append("VWORLD_CACHE_TTL_HOURS(1..8760)")
    if (
        not values.get("TMAP_API_KEY")
        and values.get("OSMNX_WALK_GEOMETRY_ENABLED", "").lower() != "true"
    ):
        missing.append(
            "exact walking geometry(TMAP_API_KEY or OSMNX_WALK_GEOMETRY_ENABLED=true)"
        )
    if missing:
        print("배포 준비 미완료: " + ", ".join(dict.fromkeys(missing)))
        raise SystemExit(1)
    print("배포 필수 설정 확인 완료")
    if not values.get("TMAP_API_KEY"):
        print("선택 설정 미입력: TMAP_API_KEY (보행 상세 보강 기능만 비활성)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--import-existing",
        action="store_true",
        help="frontend/backend/ai의 기존 .env 키를 값 노출 없이 가져옵니다.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=".env.production의 필수 설정을 값 노출 없이 검사합니다.",
    )
    parser.add_argument(
        "--import-env",
        type=Path,
        help=(
            "추가 환경파일을 가져옵니다. KAKAO_JAVASCRIPT_KEY는 지도용 "
            "VITE_KAKAO_MAP_KEY로만 매핑하며 REST 키로 대체하지 않습니다."
        ),
    )
    args = parser.parse_args()
    if args.check:
        check()
    else:
        prepare(args.import_existing, args.import_env)


if __name__ == "__main__":
    main()
