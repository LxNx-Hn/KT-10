"""AI 서비스와 저장소 루트 양쪽의 패키지 import 계약."""


def test_snapshot_module_supports_ai_service_import_path():
    from scoring.snapshots import SNAPSHOT_SCHEMA_VERSION

    assert SNAPSHOT_SCHEMA_VERSION == "route-feature-snapshot-v2"


def test_snapshot_module_supports_repo_root_import_path():
    from ai.scoring.snapshots import SNAPSHOT_SCHEMA_VERSION

    assert SNAPSHOT_SCHEMA_VERSION == "route-feature-snapshot-v2"
