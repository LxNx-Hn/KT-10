"""Add independent administrator moderation metadata to route reviews."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0004"
down_revision: Union[str, Sequence[str], None] = "20260724_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "route_reviews",
        sa.Column(
            "moderation_status",
            sa.String(24),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "route_reviews",
        sa.Column("resolution_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "route_reviews",
        sa.Column(
            "reviewed_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "route_reviews",
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_route_reviews_moderation_status",
        "route_reviews",
        ["moderation_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_route_reviews_moderation_status",
        table_name="route_reviews",
    )
    op.drop_column("route_reviews", "reviewed_at")
    op.drop_column("route_reviews", "reviewed_by")
    op.drop_column("route_reviews", "resolution_note")
    op.drop_column("route_reviews", "moderation_status")
