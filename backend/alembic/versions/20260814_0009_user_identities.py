"""Add user_identities and backfill Kakao subjects from users.kakao_id.

users.kakao_id는 유지한다. 기존 계정·preference·agreement·review FK는
건드리지 않고 identity 행만 추가한다.
"""
from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0009"
down_revision: Union[str, Sequence[str], None] = "20260813_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_subject", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_subject",
            name="uq_user_identities_provider_subject",
        ),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            name="uq_user_identities_user_provider",
        ),
    )
    op.create_index(
        "ix_user_identities_user_id",
        "user_identities",
        ["user_id"],
    )

    bind = op.get_bind()
    users = sa.table(
        "users",
        sa.column("id", sa.String(36)),
        sa.column("kakao_id", sa.String(64)),
    )
    identities = sa.table(
        "user_identities",
        sa.column("id", sa.String(36)),
        sa.column("user_id", sa.String(36)),
        sa.column("provider", sa.String(32)),
        sa.column("provider_subject", sa.String(255)),
    )
    rows = list(bind.execute(sa.select(users.c.id, users.c.kakao_id)).mappings())
    if rows:
        bind.execute(
            identities.insert(),
            [
                {
                    "id": str(uuid4()),
                    "user_id": row["id"],
                    "provider": "kakao",
                    "provider_subject": row["kakao_id"],
                }
                for row in rows
            ],
        )


def downgrade() -> None:
    op.drop_index("ix_user_identities_user_id", table_name="user_identities")
    op.drop_table("user_identities")
