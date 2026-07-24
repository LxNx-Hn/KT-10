"""Add optional direct-observation dimensions to route reviews."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0003"
down_revision: Union[str, Sequence[str], None] = "20260724_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "route_reviews",
        sa.Column("crowding_difficulty", sa.Integer(), nullable=True),
    )
    op.add_column(
        "route_reviews",
        sa.Column(
            "transfer_information_difficulty",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "route_reviews",
        sa.Column(
            "accessibility_facility_difficulty",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_route_reviews_crowding_difficulty_range",
        "route_reviews",
        "crowding_difficulty IS NULL OR crowding_difficulty BETWEEN 1 AND 5",
    )
    op.create_check_constraint(
        "ck_route_reviews_transfer_information_difficulty_range",
        "route_reviews",
        "transfer_information_difficulty IS NULL "
        "OR transfer_information_difficulty BETWEEN 1 AND 5",
    )
    op.create_check_constraint(
        "ck_route_reviews_accessibility_facility_difficulty_range",
        "route_reviews",
        "accessibility_facility_difficulty IS NULL "
        "OR accessibility_facility_difficulty BETWEEN 1 AND 5",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_route_reviews_accessibility_facility_difficulty_range",
        "route_reviews",
        type_="check",
    )
    op.drop_constraint(
        "ck_route_reviews_transfer_information_difficulty_range",
        "route_reviews",
        type_="check",
    )
    op.drop_constraint(
        "ck_route_reviews_crowding_difficulty_range",
        "route_reviews",
        type_="check",
    )
    op.drop_column("route_reviews", "accessibility_facility_difficulty")
    op.drop_column("route_reviews", "transfer_information_difficulty")
    op.drop_column("route_reviews", "crowding_difficulty")
