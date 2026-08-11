from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base, User
from ml.manage_admin import set_admin


@pytest.fixture()
def admin_database(tmp_path):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'admin.sqlite3').as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(id="member", kakao_id="123456", is_admin=False))
        db.commit()
    engine.dispose()
    return database_url


def test_explicit_admin_grant_and_revoke(admin_database):
    granted = set_admin(admin_database, "123456", is_admin=True)
    assert granted == {"userId": "member", "isAdmin": True, "changed": True}
    assert set_admin(admin_database, "123456", is_admin=True)["changed"] is False

    revoked = set_admin(admin_database, "123456", is_admin=False)
    assert revoked == {"userId": "member", "isAdmin": False, "changed": True}


def test_admin_management_rejects_unknown_or_invalid_identity(admin_database):
    with pytest.raises(LookupError, match="Complete Kakao login"):
        set_admin(admin_database, "999999", is_admin=True)
    for invalid in ("", "abc", "0", "-1"):
        with pytest.raises(ValueError, match="positive numeric"):
            set_admin(admin_database, invalid, is_admin=True)
