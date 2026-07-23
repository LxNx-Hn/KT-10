"""Prevent repeated reviews for one displayed route impression."""
from typing import Sequence, Union

from alembic import op

revision: str = "20260724_0002"
down_revision: Union[str, Sequence[str], None] = "20260720_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_route_reviews_user_impression",
        "route_reviews",
        ["user_id", "impression_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_route_reviews_user_impression",
        "route_reviews",
        type_="unique",
    )
