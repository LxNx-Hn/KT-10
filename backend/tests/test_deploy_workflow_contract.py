"""운영 ECS 배포가 회전된 접근성 공급자 키를 확실히 주입한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-ecs.yml"


def test_ai_task_definition_injects_current_odsay_and_ors_secrets():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "ODSAY_API_KEY: ${{ secrets.ODSAY_API_KEY }}" in workflow
    assert "ORS_API_KEY: ${{ secrets.ORS_API_KEY }}" in workflow
    assert "sync_task_secret_value" in workflow
    assert ".secrets[]?" in workflow
    assert "select(.name == $secret_name)" in workflow
    assert "aws secretsmanager put-secret-value" in workflow
    assert "aws ssm put-parameter" in workflow
    assert 'parameter_name="/${value_from#*:parameter/}"' in workflow
    assert "must reference managed secret" in workflow
    assert "value: $odsay_api_key" not in workflow
    assert 'name: "ORS_API_KEY"' in workflow
    assert 'value: $ors_api_key' in workflow
    assert "ODSAY_API_KEY secret is required for transit routing." in workflow
    assert "ORS_API_KEY secret is required for wheelchair routing." in workflow
