"""Add user_agreements for current terms acceptance records.

기존 User 행에 동의했다고 기록하지 않는다. row 없음 = 아직 수락 없음.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260813_0008"
down_revision: Union[str, Sequence[str], None] = "20260812_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_agreements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("document_version", sa.String(32), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "document_type",
            "document_version",
            "action",
            name="uq_user_agreements_user_doc_version_action",
        ),
        sa.CheckConstraint(
            "document_type IN ('terms')",
            name="ck_user_agreements_document_type",
        ),
        sa.CheckConstraint(
            "action IN ('accepted')",
            name="ck_user_agreements_action",
        ),
    )
    op.create_index(
        "ix_user_agreements_user_id",
        "user_agreements",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_agreements_user_id", table_name="user_agreements")
    op.drop_table("user_agreements")
