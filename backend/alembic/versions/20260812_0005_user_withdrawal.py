"""Add the account withdrawal queue that defers user purge by a retention window."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0005"
down_revision: Union[str, Sequence[str], None] = "20260811_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_withdrawals",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("purge_after", sa.DateTime(), nullable=False),
        sa.Column(
            "provider_unlinked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # 파기 배치는 기한이 지난 항목만 훑으므로 purge_after 범위 조회를 인덱싱한다.
    op.create_index(
        "ix_user_withdrawals_purge_after",
        "user_withdrawals",
        ["purge_after"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_withdrawals_purge_after",
        table_name="user_withdrawals",
    )
    op.drop_table("user_withdrawals")
