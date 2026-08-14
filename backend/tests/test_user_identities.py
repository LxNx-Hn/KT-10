"""UserIdentity schema, Kakao backfill semantics, and lookup helpers."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, User, UserIdentity, UserPreference, utc_now_naive
from app.identities import (
    PROVIDER_KAKAO,
    ProviderIdentityConflict,
    ensure_kakao_identity,
    find_user_by_provider_identity,
)


def _engine(tmp_path, name):
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def test_user_identity_unique_provider_subject(tmp_path):
    engine = _engine(tmp_path, "identity-unique-subject.sqlite3")
    with Session(engine) as db:
        db.add(User(id="a", kakao_id="100"))
        db.add(User(id="b", kakao_id="200"))
        db.flush()
        db.add(UserIdentity(
            user_id="a",
            provider=PROVIDER_KAKAO,
            provider_subject="100",
        ))
        db.commit()

    with Session(engine) as db:
        db.add(UserIdentity(
            user_id="b",
            provider=PROVIDER_KAKAO,
            provider_subject="100",
        ))
        with pytest.raises(IntegrityError):
            db.commit()


def test_user_identity_unique_user_provider(tmp_path):
    engine = _engine(tmp_path, "identity-unique-user.sqlite3")
    with Session(engine) as db:
        db.add(User(id="a", kakao_id="100"))
        db.flush()
        db.add(UserIdentity(
            user_id="a",
            provider=PROVIDER_KAKAO,
            provider_subject="100",
        ))
        db.commit()

    with Session(engine) as db:
        db.add(UserIdentity(
            user_id="a",
            provider=PROVIDER_KAKAO,
            provider_subject="999",
        ))
        with pytest.raises(IntegrityError):
            db.commit()


def test_user_delete_cascades_identities(tmp_path):
    engine = _engine(tmp_path, "identity-cascade.sqlite3")
    with Session(engine) as db:
        db.add(User(id="member", kakao_id="7001"))
        db.flush()
        db.add(UserPreference(user_id="member"))
        db.add(UserIdentity(
            user_id="member",
            provider=PROVIDER_KAKAO,
            provider_subject="7001",
        ))
        db.commit()

    with Session(engine) as db:
        user = db.get(User, "member")
        assert user is not None
        db.delete(user)
        db.commit()

    with Session(engine) as db:
        assert db.get(User, "member") is None
        assert db.scalar(select(func.count()).select_from(UserIdentity)) == 0


def test_kakao_backfill_semantics_one_identity_per_user(tmp_path):
    """migration과 동일한 백필 규칙: 기존 User마다 Kakao identity 1개."""
    engine = _engine(tmp_path, "identity-backfill.sqlite3")
    with Session(engine) as db:
        db.add(User(id="u1", kakao_id="111"))
        db.add(User(id="u2", kakao_id="222"))
        db.commit()

    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(UserIdentity)) == 0
        users = list(db.scalars(select(User)))
        for user in users:
            db.add(UserIdentity(
                id=str(uuid4()),
                user_id=user.id,
                provider=PROVIDER_KAKAO,
                provider_subject=user.kakao_id,
                created_at=utc_now_naive(),
            ))
        db.commit()

    with Session(engine) as db:
        identities = list(db.scalars(select(UserIdentity)))
        assert len(identities) == 2
        by_user = {row.user_id: row for row in identities}
        assert by_user["u1"].provider == PROVIDER_KAKAO
        assert by_user["u1"].provider_subject == "111"
        assert by_user["u2"].provider_subject == "222"
        assert db.get(User, "u1").kakao_id == "111"
        assert db.get(User, "u2").kakao_id == "222"


def test_lookup_prefers_identity_over_legacy(tmp_path):
    engine = _engine(tmp_path, "identity-lookup.sqlite3")
    with Session(engine) as db:
        db.add(User(id="member", kakao_id="123456"))
        db.flush()
        db.add(UserIdentity(
            user_id="member",
            provider=PROVIDER_KAKAO,
            provider_subject="123456",
        ))
        db.commit()

    with Session(engine) as db:
        user = find_user_by_provider_identity(
            db,
            provider=PROVIDER_KAKAO,
            provider_subject="123456",
        )
        assert user is not None
        assert user.id == "member"


def test_legacy_kakao_fallback_self_heals(tmp_path):
    engine = _engine(tmp_path, "identity-heal.sqlite3")
    with Session(engine) as db:
        db.add(User(id="legacy", kakao_id="555"))
        db.commit()

    with Session(engine) as db:
        assert db.scalar(select(UserIdentity)) is None
        user = find_user_by_provider_identity(
            db,
            provider=PROVIDER_KAKAO,
            provider_subject="555",
        )
        assert user is not None
        assert user.id == "legacy"
        db.commit()

    with Session(engine) as db:
        identity = db.scalar(select(UserIdentity))
        assert identity is not None
        assert identity.user_id == "legacy"
        assert identity.provider == PROVIDER_KAKAO
        assert identity.provider_subject == "555"


def test_non_kakao_provider_does_not_use_legacy_kakao_id(tmp_path):
    engine = _engine(tmp_path, "identity-no-legacy-apple.sqlite3")
    with Session(engine) as db:
        db.add(User(id="member", kakao_id="apple-sub-should-not-match"))
        db.commit()

    with Session(engine) as db:
        assert find_user_by_provider_identity(
            db,
            provider="apple",
            provider_subject="apple-sub-should-not-match",
        ) is None
        assert db.scalar(select(func.count()).select_from(UserIdentity)) == 0


def test_ensure_kakao_identity_is_idempotent(tmp_path):
    engine = _engine(tmp_path, "identity-idempotent.sqlite3")
    with Session(engine) as db:
        user = User(id="member", kakao_id="42")
        db.add(user)
        db.flush()
        ensure_kakao_identity(db, user)
        ensure_kakao_identity(db, user)
        db.commit()

    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(UserIdentity)) == 1


def test_ensure_kakao_identity_conflict_other_owner_is_fail_closed(tmp_path):
    """subject가 다른 User에 묶여 있으면 legacy User로 heal/로그인하지 않는다."""
    engine = _engine(tmp_path, "identity-conflict-owner.sqlite3")
    with Session(engine) as db:
        db.add(User(id="a", kakao_id="123"))
        db.add(User(id="b", kakao_id="456"))
        db.flush()
        # 비정상: subject 123이 B에 귀속 (A.kakao_id와 불일치)
        db.add(UserIdentity(
            user_id="b",
            provider=PROVIDER_KAKAO,
            provider_subject="123",
        ))
        db.commit()

    with Session(engine) as db:
        a = db.get(User, "a")
        assert a is not None
        with pytest.raises(ProviderIdentityConflict):
            ensure_kakao_identity(db, a)
        # A에 잘못 연결되지 않음
        assert db.scalar(
            select(func.count()).select_from(UserIdentity).where(
                UserIdentity.user_id == "a",
            )
        ) == 0
        owned = db.scalar(
            select(UserIdentity).where(
                UserIdentity.provider == PROVIDER_KAKAO,
                UserIdentity.provider_subject == "123",
            )
        )
        assert owned is not None
        assert owned.user_id == "b"


def test_legacy_lookup_fail_closed_when_raced_identity_owner_differs(tmp_path):
    """legacy User 조회 후 subject identity owner가 다르면 conflict."""
    engine = _engine(tmp_path, "identity-conflict-race.sqlite3")
    with Session(engine) as db:
        db.add(User(id="a", kakao_id="123"))
        db.add(User(id="b", kakao_id="456"))
        db.flush()
        db.add(UserIdentity(
            user_id="b",
            provider=PROVIDER_KAKAO,
            provider_subject="123",
        ))
        db.commit()

    with Session(engine) as db:
        # identity가 있으므로 정상 경로에서는 B를 반환한다 (source of truth).
        user = find_user_by_provider_identity(
            db,
            provider=PROVIDER_KAKAO,
            provider_subject="123",
        )
        assert user is not None
        assert user.id == "b"

        # legacy A에 대해 heal을 강제하면 fail-closed.
        a = db.get(User, "a")
        assert a is not None
        with pytest.raises(ProviderIdentityConflict):
            ensure_kakao_identity(db, a)


def test_ensure_unique_user_provider_conflict_is_fail_closed(tmp_path):
    """같은 User에 다른 kakao subject identity가 있으면 추가 heal을 거부한다."""
    engine = _engine(tmp_path, "identity-conflict-user-provider.sqlite3")
    with Session(engine) as db:
        db.add(User(id="a", kakao_id="123"))
        db.flush()
        db.add(UserIdentity(
            user_id="a",
            provider=PROVIDER_KAKAO,
            provider_subject="999",
        ))
        db.commit()

    with Session(engine) as db:
        a = db.get(User, "a")
        assert a is not None
        with pytest.raises(ProviderIdentityConflict):
            ensure_kakao_identity(db, a)
        identities = list(db.scalars(select(UserIdentity)))
        assert len(identities) == 1
        assert identities[0].provider_subject == "999"


def test_signup_dual_write_nested_rolls_back_on_kakao_id_conflict(tmp_path):
    """동일 kakao_id가 있으면 새 User/Preference/Identity 조각이 남지 않는다."""
    from app.api import auth as auth_module

    engine = _engine(tmp_path, "identity-dual-write.sqlite3")
    with Session(engine) as db:
        db.add(User(id="existing", kakao_id="123456", nickname="이전"))
        db.flush()
        db.add(UserPreference(user_id="existing"))
        db.add(UserIdentity(
            user_id="existing",
            provider=PROVIDER_KAKAO,
            provider_subject="123456",
        ))
        db.commit()

    with Session(engine) as db:
        user = auth_module._create_user_with_preference(
            db,
            kakao_id="123456",
            nickname="새닉",
        )
        db.commit()
        assert user.id == "existing"
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(UserPreference)) == 1
        assert db.scalar(select(func.count()).select_from(UserIdentity)) == 1


def test_alembic_user_identities_upgrade_backfills_kakao(tmp_path):
    """사전 schema + users만 있는 DB에서 migration upgrade가 백필한다."""
    import importlib.util
    from pathlib import Path

    import alembic.op as op_module
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'alembic-identities.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE users ("
            "id VARCHAR(36) PRIMARY KEY,"
            "kakao_id VARCHAR(64) NOT NULL UNIQUE,"
            "nickname VARCHAR(100),"
            "is_admin BOOLEAN NOT NULL DEFAULT 0,"
            "created_at DATETIME"
            ")"
        ))
        conn.execute(text(
            "INSERT INTO users (id, kakao_id, nickname, is_admin) "
            "VALUES ('u1', '111', NULL, 0), ('u2', '222', NULL, 0)"
        ))

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260814_0009_user_identities.py"
    )
    spec = importlib.util.spec_from_file_location("m20260814_0009", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        ops = Operations(context)
        originals = {
            "create_table": op_module.create_table,
            "create_index": op_module.create_index,
            "get_bind": getattr(op_module, "get_bind", None),
        }
        op_module.create_table = ops.create_table
        op_module.create_index = ops.create_index
        op_module.get_bind = lambda: conn  # type: ignore[assignment]
        try:
            module.upgrade()
        finally:
            op_module.create_table = originals["create_table"]
            op_module.create_index = originals["create_index"]
            if originals["get_bind"] is None:
                delattr(op_module, "get_bind")
            else:
                op_module.get_bind = originals["get_bind"]  # type: ignore[assignment]

    with engine.connect() as conn:
        rows = list(conn.execute(text(
            "SELECT user_id, provider, provider_subject FROM user_identities "
            "ORDER BY user_id"
        )))
        assert rows == [
            ("u1", "kakao", "111"),
            ("u2", "kakao", "222"),
        ]
        users = list(conn.execute(text(
            "SELECT id, kakao_id FROM users ORDER BY id"
        )))
        assert users == [("u1", "111"), ("u2", "222")]
