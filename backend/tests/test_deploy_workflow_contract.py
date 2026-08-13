"""운영 ECS 배포가 접근성 공급자 키 계약을 보존한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-ecs.yml"


def test_ai_task_definition_preserves_odsay_secret_and_injects_ors_key():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "ORS_API_KEY: ${{ secrets.ORS_API_KEY }}" in workflow
    assert "require_task_secret_reference" in workflow
    assert ".secrets[]?" in workflow
    assert "select(.name == $secret_name)" in workflow
    assert "must reference managed secret" in workflow
    assert "put-secret-value" not in workflow
    assert "ODSAY_API_KEY: ${{ secrets.ODSAY_API_KEY }}" not in workflow
    assert 'name: "ORS_API_KEY"' in workflow
    assert 'value: $ors_api_key' in workflow
    assert "ORS_API_KEY secret is required for wheelchair routing." in workflow
