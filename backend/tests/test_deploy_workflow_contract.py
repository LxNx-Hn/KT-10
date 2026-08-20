"""운영 ECS 배포가 접근성 공급자 키 계약을 보존한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-ecs.yml"


def test_task_definitions_inject_tmap_public_data_bus_and_ors_keys():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "TMAP_API_KEY: ${{ secrets.TMAP_API_KEY }}" in workflow
    assert "ORS_API_KEY: ${{ secrets.ORS_API_KEY }}" in workflow
    assert "DATA_GO_KR_SERVICE_KEY: ${{ secrets.DATA_GO_KR_SERVICE_KEY || secrets.DECO }}" in workflow
    assert "BUS_SERVICE_KEY: ${{ secrets.BUS_SERVICE_KEY }}" in workflow
    assert 'name: "TMAP_API_KEY"' in workflow
    assert 'value: $tmap_api_key' in workflow
    assert 'name: "DATA_GO_KR_SERVICE_KEY"' in workflow
    assert 'value: $data_go_kr_service_key' in workflow
    assert 'name: "BUS_SERVICE_KEY"' in workflow
    assert 'value: $bus_service_key' in workflow
    assert 'name: "ORS_API_KEY"' in workflow
    assert 'value: $ors_api_key' in workflow
    assert "TMAP_API_KEY secret is required for transit routing." in workflow
    assert "ODSAY_API_KEY secret is required" not in workflow
    assert "ORS_API_KEY secret is required for wheelchair routing." in workflow
