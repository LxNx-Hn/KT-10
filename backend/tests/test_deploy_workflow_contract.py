"""운영 ECS 배포가 접근성 공급자 키 계약을 보존한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-ecs.yml"


def test_ai_task_definition_injects_current_odsay_and_ors_keys():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "ODSAY_API_KEY: ${{ secrets.ODSAY_API_KEY }}" in workflow
    assert "ORS_API_KEY: ${{ secrets.ORS_API_KEY }}" in workflow
    assert 'map(select(.name != "ODSAY_API_KEY"))' in workflow
    assert 'name: "ODSAY_API_KEY"' in workflow
    assert 'value: $odsay_api_key' in workflow
    assert 'name: "ORS_API_KEY"' in workflow
    assert 'value: $ors_api_key' in workflow
    assert "ODSAY_API_KEY secret is required for transit routing." in workflow
    assert "ORS_API_KEY secret is required for wheelchair routing." in workflow
