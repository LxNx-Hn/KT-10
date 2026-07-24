"""배포 환경 가져오기는 키 종류를 섞거나 비밀값을 출력하지 않는다."""
from pathlib import Path

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
    monkeypatch.setattr(prepare_deployment_env, "EXAMPLE", example)
    monkeypatch.setattr(prepare_deployment_env, "TARGET", target)

    prepare_deployment_env.prepare(import_existing=False, import_env=supplied)

    values = prepare_deployment_env._values(target)
    assert values["VITE_KAKAO_MAP_KEY"] == "javascript-secret"
    assert values["KAKAO_REST_API_KEY"] == ""
    assert values["ODSAY_API_KEY"] == "odsay-secret"
    assert values["BUS_SERVICE_KEY"] == "bus-secret"
    output = capsys.readouterr().out
    assert "javascript-secret" not in output
    assert "odsay-secret" not in output
    assert "bus-secret" not in output
