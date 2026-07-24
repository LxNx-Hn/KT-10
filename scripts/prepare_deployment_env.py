"""배포용 단일 환경파일을 생성·병합·검증한다.

비밀값은 출력하지 않는다. 외부 키는 기존 하위 .env에서 선택적으로 가져오고,
서비스 내부 비밀값은 안전한 난수로 생성한다.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import secrets
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.production.example"
TARGET = ROOT / ".env.production"
GENERATED = {
    "POSTGRES_PASSWORD": 24,
    "SESSION_SECRET": 48,
    "TRAINING_ANONYMIZATION_SALT": 32,
    "LABELING_API_TOKEN": 48,
}
REQUIRED_EXTERNAL = (
    "VITE_KAKAO_MAP_KEY",
    "KAKAO_REST_API_KEY",
    "KAKAO_OAUTH_CLIENT_SECRET",
    "ODSAY_API_KEY",
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
    "VWORLD_API_KEY": ROOT / "backend" / ".env",
    "OPENWEATHER_API_KEY": ROOT / "backend" / ".env",
    "BUS_SERVICE_KEY": ROOT / "backend" / ".env",
}
# 외부 전달 파일에서 쓰일 수 있는 명칭을 정규화한다. JavaScript 키와
# REST 키는 서로 대체할 수 없으므로 의도적으로 별도 항목으로 유지한다.
IMPORT_ALIASES = {
    "VITE_KAKAO_MAP_KEY": ("VITE_KAKAO_MAP_KEY", "KAKAO_JAVASCRIPT_KEY"),
    "KAKAO_REST_API_KEY": ("KAKAO_REST_API_KEY",),
    "KAKAO_OAUTH_CLIENT_SECRET": ("KAKAO_OAUTH_CLIENT_SECRET",),
    "ODSAY_API_KEY": ("ODSAY_API_KEY",),
    "TMAP_API_KEY": ("TMAP_API_KEY",),
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
            if not values.get(key):
                values[key] = _first_present(imported, aliases)
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
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        missing.append("PUBLIC_ORIGIN(valid URL)")
    if origin.startswith("http://") and parsed.hostname not in {"localhost", "127.0.0.1"}:
        missing.append("PUBLIC_ORIGIN(HTTPS required outside localhost)")
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
