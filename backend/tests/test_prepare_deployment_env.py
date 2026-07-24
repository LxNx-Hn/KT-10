"""배포 환경 가져오기는 키 종류를 섞거나 비밀값을 출력하지 않는다."""
from pathlib import Path

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
    assert values["KAKAO_REST_API_KEY"] == "existing-rest-secret"
    assert values["ODSAY_API_KEY"] == "odsay-secret"
    assert values["BUS_SERVICE_KEY"] == "bus-secret"
    output = capsys.readouterr().out
    assert "javascript-secret" not in output
    assert "odsay-secret" not in output
    assert "bus-secret" not in output


def _valid_production_env() -> str:
    return "\n".join((
        "PUBLIC_ORIGIN=https://route.example.kr",
        "PORT=8080",
        "ROUTE_MODE=live",
        "BUILDING_SOURCE=vworld",
        "VITE_KAKAO_MAP_KEY=javascript-key",
        "KAKAO_REST_API_KEY=rest-key",
        "KAKAO_OAUTH_CLIENT_SECRET=oauth-secret",
        "ODSAY_API_KEY=odsay-key",
        "VWORLD_API_KEY=vworld-key",
        "OPENWEATHER_API_KEY=weather-key",
        "BUS_SERVICE_KEY=bus-key",
        "POSTGRES_PASSWORD=" + "p" * 24,
        "SESSION_SECRET=" + "s" * 48,
        "TRAINING_ANONYMIZATION_SALT=" + "a" * 32,
        "LABELING_API_TOKEN=" + "l" * 48,
        "REQUEST_TIMEOUT=8",
        "RANKER_TIER=human_validated",
        "OSMNX_WALK_GEOMETRY_ENABLED=false",
    )) + "\n"


def test_check_accepts_hardened_production_contract(
    tmp_path: Path,
    monkeypatch,
):
    target = tmp_path / ".env.production"
    target.write_text(_valid_production_env(), encoding="utf-8")
    monkeypatch.setattr(prepare_deployment_env, "TARGET", target)

    prepare_deployment_env.check()


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
            "RANKER_TIER=human_validated",
            "RANKER_TIER=judge_baseline",
            "human_validated",
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
