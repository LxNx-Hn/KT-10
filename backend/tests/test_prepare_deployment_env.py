"""배포 환경 가져오기는 키 종류를 섞거나 비밀값을 출력하지 않는다."""
import json
from pathlib import Path
import zipfile

import pytest

from scripts import prepare_deployment_env


def test_import_env_maps_known_aliases_without_using_js_key_as_rest_key(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    example = tmp_path / ".env.production.example"
    target = tmp_path / ".env.production"
    supplied = tmp_path / "supplied-env"
    example.write_text(
        "\n".join((
            "VITE_KAKAO_MAP_KEY=",
            "KAKAO_REST_API_KEY=",
            "ODSAY_API_KEY=",
            "BUS_SERVICE_KEY=",
            "POSTGRES_PASSWORD=",
            "SESSION_SECRET=",
            "TRAINING_ANONYMIZATION_SALT=",
            "LABELING_API_TOKEN=",
        )) + "\n",
        encoding="utf-8",
    )
    supplied.write_text(
        "\n".join((
            "KAKAO_JAVASCRIPT_KEY=javascript-secret",
            "KAKAO_REST_API=rest-secret",
            "ODSAY_API_KEY=odsay-secret",
            "BUSAN_BUS_API_KEY=bus-secret",
        )) + "\n",
        encoding="utf-8",
    )
    target.write_text(
        "\n".join((
            "VITE_KAKAO_MAP_KEY=old-javascript-secret",
            "KAKAO_REST_API_KEY=existing-rest-secret",
            "ODSAY_API_KEY=old-odsay-secret",
        )) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare_deployment_env, "EXAMPLE", example)
    monkeypatch.setattr(prepare_deployment_env, "TARGET", target)

    prepare_deployment_env.prepare(import_existing=False, import_env=supplied)

    values = prepare_deployment_env._values(target)
    assert values["VITE_KAKAO_MAP_KEY"] == "javascript-secret"
    assert values["KAKAO_REST_API_KEY"] == "rest-secret"
    assert values["ODSAY_API_KEY"] == "odsay-secret"
    assert values["BUS_SERVICE_KEY"] == "bus-secret"
    output = capsys.readouterr().out
    assert "javascript-secret" not in output
    assert "rest-secret" not in output
    assert "odsay-secret" not in output
    assert "bus-secret" not in output


def _valid_production_env() -> str:
    return "\n".join((
        "PUBLIC_ORIGIN=https://route.example.kr",
        "BIND_ADDRESS=127.0.0.1",
        "PORT=8080",
        "ROUTE_MODE=live",
        "BUILDING_SOURCE=vworld",
        "VITE_KAKAO_MAP_KEY=javascript-key",
        "KAKAO_REST_API_KEY=rest-key",
        "KAKAO_OAUTH_CLIENT_SECRET=oauth-secret",
        "ODSAY_API_KEY=odsay-key",
        "TMAP_API_KEY=tmap-key",
        "ORS_API_KEY=ors-key",
        "VWORLD_API_KEY=vworld-key",
        "VWORLD_CACHE_TTL_HOURS=168",
        "OPENWEATHER_API_KEY=weather-key",
        "BUS_SERVICE_KEY=bus-key",
        "POSTGRES_PASSWORD=" + "p" * 24,
        "SESSION_SECRET=" + "s" * 48,
        "TRAINING_ANONYMIZATION_SALT=" + "a" * 32,
        "LABELING_API_TOKEN=" + "l" * 48,
        "AI_INTERNAL_SERVICE_TOKEN=" + "i" * 48,
        "WITHDRAWAL_HASH_SALT=" + "w" * 32,
        "REQUEST_TIMEOUT=8",
        "RANKER_TIER=human_validated",
        "OSMNX_WALK_GEOMETRY_ENABLED=false",
        "OSMNX_OVERPASS_URL=https://lambert.openstreetmap.de/api",
        "OSMNX_REQUEST_TIMEOUT_SECONDS=12",
        "OSMNX_WALK_GEOMETRY_TIMEOUT_SECONDS=15",
    )) + "\n"


def test_check_accepts_hardened_production_contract(
    tmp_path: Path,
    monkeypatch,
):
    target = tmp_path / ".env.production"
    target.write_text(_valid_production_env(), encoding="utf-8")
    monkeypatch.setattr(prepare_deployment_env, "TARGET", target)

    prepare_deployment_env.check()


def test_check_rejects_missing_withdrawal_hash_salt(tmp_path: Path, monkeypatch):
    """salt가 비면 탈퇴 기록이 반복 탈퇴를 판별하지 못한 채 배포된다."""
    target = tmp_path / ".env.production"
    target.write_text(
        _valid_production_env().replace(
            "WITHDRAWAL_HASH_SALT=" + "w" * 32,
            "WITHDRAWAL_HASH_SALT=",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare_deployment_env, "TARGET", target)

    with pytest.raises(SystemExit):
        prepare_deployment_env.check()


def test_check_rejects_withdrawal_salt_reused_from_another_secret(
    tmp_path: Path,
    monkeypatch,
):
    """세션·학습 salt를 재사용하면 서로 다른 목적의 해시를 교차 대조할 수 있다."""
    target = tmp_path / ".env.production"
    target.write_text(
        _valid_production_env().replace(
            "WITHDRAWAL_HASH_SALT=" + "w" * 32,
            "WITHDRAWAL_HASH_SALT=" + "a" * 32,  # TRAINING_ANONYMIZATION_SALT와 동일
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare_deployment_env, "TARGET", target)

    with pytest.raises(SystemExit):
        prepare_deployment_env.check()


def test_check_accepts_explicit_osmnx_when_tmap_is_absent(
    tmp_path: Path,
    monkeypatch,
):
    target = tmp_path / ".env.production"
    target.write_text(
        _valid_production_env()
        .replace("TMAP_API_KEY=tmap-key", "TMAP_API_KEY=")
        .replace(
            "OSMNX_WALK_GEOMETRY_ENABLED=false",
            "OSMNX_WALK_GEOMETRY_ENABLED=true",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare_deployment_env, "TARGET", target)

    prepare_deployment_env.check()


def test_check_rejects_missing_wheelchair_routing_key(
    tmp_path: Path,
    monkeypatch,
):
    target = tmp_path / ".env.production"
    target.write_text(
        _valid_production_env().replace("ORS_API_KEY=ors-key", "ORS_API_KEY="),
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare_deployment_env, "TARGET", target)

    with pytest.raises(SystemExit):
        prepare_deployment_env.check()


def test_check_accepts_local_ai_mode_with_complete_bootstrap_artifact(
    tmp_path: Path,
    monkeypatch,
):
    target = tmp_path / ".env.production"
    model = tmp_path / "rankers.bootstrap-baseline.zip"
    metadata = tmp_path / "rankers.bootstrap-baseline.metadata.json"
    profiles = sorted(prepare_deployment_env.MODEL_PROFILES)
    target.write_text(
        _valid_production_env()
        .replace(
            "PUBLIC_ORIGIN=https://route.example.kr",
            "PUBLIC_ORIGIN=http://localhost:8080",
        )
        .replace("ROUTE_MODE=live", "ROUTE_MODE=ai")
        .replace(
            "RANKER_TIER=human_validated",
            "RANKER_TIER=bootstrap_baseline",
        ),
        encoding="utf-8",
    )
    metadata.write_text(
        json.dumps({
            "model_tier": "bootstrap_baseline",
            "profiles": profiles,
        }),
        encoding="utf-8",
    )
    with zipfile.ZipFile(model, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({
                "model_tier": "bootstrap_baseline",
                "profiles": profiles,
            }),
        )
        for profile in profiles:
            archive.writestr(f"models/{profile}.json", "{}")
    monkeypatch.setattr(prepare_deployment_env, "TARGET", target)
    monkeypatch.setattr(prepare_deployment_env, "BOOTSTRAP_MODEL", model)
    monkeypatch.setattr(prepare_deployment_env, "BOOTSTRAP_METADATA", metadata)

    prepare_deployment_env.check()


def test_check_accepts_bootstrap_model_for_public_origin_with_artifact(
    tmp_path: Path,
    monkeypatch,
):
    target = tmp_path / ".env.production"
    model = tmp_path / "rankers.bootstrap-baseline.zip"
    metadata = tmp_path / "rankers.bootstrap-baseline.metadata.json"
    profiles = sorted(prepare_deployment_env.MODEL_PROFILES)
    target.write_text(
        _valid_production_env()
        .replace("ROUTE_MODE=live", "ROUTE_MODE=ai")
        .replace(
            "RANKER_TIER=human_validated",
            "RANKER_TIER=bootstrap_baseline",
        ),
        encoding="utf-8",
    )
    metadata.write_text(
        json.dumps({
            "model_tier": "bootstrap_baseline",
            "profiles": profiles,
        }),
        encoding="utf-8",
    )
    with zipfile.ZipFile(model, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({
                "model_tier": "bootstrap_baseline",
                "profiles": profiles,
            }),
        )
        for profile in profiles:
            archive.writestr(f"models/{profile}.json", "{}")
    monkeypatch.setattr(prepare_deployment_env, "TARGET", target)
    monkeypatch.setattr(prepare_deployment_env, "BOOTSTRAP_MODEL", model)
    monkeypatch.setattr(prepare_deployment_env, "BOOTSTRAP_METADATA", metadata)

    prepare_deployment_env.check()


def test_check_rejects_bootstrap_model_when_route_mode_is_not_ai(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    target = tmp_path / ".env.production"
    target.write_text(
        _valid_production_env().replace(
            "RANKER_TIER=human_validated",
            "RANKER_TIER=bootstrap_baseline",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare_deployment_env, "TARGET", target)

    with pytest.raises(SystemExit):
        prepare_deployment_env.check()
    assert "ROUTE_MODE(ai required for bootstrap_baseline)" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "PUBLIC_ORIGIN=https://route.example.kr",
            "PUBLIC_ORIGIN=https://user:pass@route.example.kr/path",
            "PUBLIC_ORIGIN",
        ),
        (
            "PUBLIC_ORIGIN=https://route.example.kr",
            "PUBLIC_ORIGIN=https://route.example.kr:notaport",
            "PUBLIC_ORIGIN",
        ),
        (
            "SESSION_SECRET=" + "s" * 48,
            "SESSION_SECRET=short",
            "minimum 32",
        ),
        (
            "KAKAO_REST_API_KEY=rest-key",
            "KAKAO_REST_API_KEY=javascript-key",
            "must be distinct",
        ),
        (
            "BIND_ADDRESS=127.0.0.1",
            "BIND_ADDRESS=203.0.113.10",
            "BIND_ADDRESS",
        ),
        (
            "TMAP_API_KEY=tmap-key",
            "TMAP_API_KEY=",
            "exact walking geometry",
        ),
        (
            "OSMNX_REQUEST_TIMEOUT_SECONDS=12",
            "OSMNX_REQUEST_TIMEOUT_SECONDS=120",
            "OSMNX_REQUEST_TIMEOUT_SECONDS",
        ),
        (
            "OSMNX_OVERPASS_URL=https://lambert.openstreetmap.de/api",
            "OSMNX_OVERPASS_URL=http://localhost:9999/api",
            "OSMNX_OVERPASS_URL",
        ),
        (
            "VWORLD_CACHE_TTL_HOURS=168",
            "VWORLD_CACHE_TTL_HOURS=0",
            "VWORLD_CACHE_TTL_HOURS",
        ),
    ],
)
def test_check_rejects_insecure_or_misclassified_configuration(
    tmp_path: Path,
    monkeypatch,
    capsys,
    old: str,
    new: str,
    message: str,
):
    target = tmp_path / ".env.production"
    target.write_text(
        _valid_production_env().replace(old, new),
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare_deployment_env, "TARGET", target)

    with pytest.raises(SystemExit):
        prepare_deployment_env.check()
    assert message in capsys.readouterr().out
