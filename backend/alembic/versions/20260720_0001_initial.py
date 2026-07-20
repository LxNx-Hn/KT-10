"""PostgreSQL initial schema for Kakao users, reviews, and facility moderation."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260720_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kakao_id", sa.String(64), nullable=False),
        sa.Column("nickname", sa.String(100), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_users_kakao_id", "users", ["kakao_id"], unique=True)
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("profile", sa.String(16), nullable=False, server_default="general"),
        sa.Column("uses_wheelchair", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("uses_walking_aid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("visual_support_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("hearing_support_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("avoid_stairs_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("max_walk_distance_m", sa.Integer(), nullable=True),
        sa.Column("training_consent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("personalization_state", sa.Text(), nullable=False, server_default='{"version":1,"bias":0.0,"weights":{},"updates":0}'),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "route_impressions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("route_id", sa.String(120), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("profile", sa.String(16), nullable=False, server_default="general"),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("feature_snapshot", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_route_impressions_user_id", "route_impressions", ["user_id"])
    op.create_index("ix_route_impressions_route_id", "route_impressions", ["route_id"])
    op.create_table(
        "route_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("impression_id", sa.String(36), sa.ForeignKey("route_impressions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("route_id", sa.String(120), nullable=False),
        sa.Column("was_usable", sa.Boolean(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("issue_type", sa.String(64), nullable=True),
        sa.Column("stairs_difficulty", sa.Integer(), nullable=True),
        sa.Column("slope_difficulty", sa.Integer(), nullable=True),
        sa.Column("transfer_difficulty", sa.Integer(), nullable=True),
        sa.Column("actual_duration_min", sa.Integer(), nullable=True),
        sa.Column("would_reuse", sa.Boolean(), nullable=True),
        sa.Column("information_accurate", sa.Boolean(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("training_consent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_route_reviews_user_id", "route_reviews", ["user_id"])
    op.create_index("ix_route_reviews_route_id", "route_reviews", ["route_id"])
    op.create_table(
        "facility_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("facility_name", sa.String(200), nullable=False),
        sa.Column("facility_type", sa.String(64), nullable=False),
        sa.Column("issue_type", sa.String(64), nullable=False),
        sa.Column("reported_lat", sa.Float(), nullable=True),
        sa.Column("reported_lng", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_facility_reports_user_id", "facility_reports", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_facility_reports_user_id", table_name="facility_reports")
    op.drop_table("facility_reports")
    op.drop_index("ix_route_reviews_route_id", table_name="route_reviews")
    op.drop_index("ix_route_reviews_user_id", table_name="route_reviews")
    op.drop_table("route_reviews")
    op.drop_index("ix_route_impressions_route_id", table_name="route_impressions")
    op.drop_index("ix_route_impressions_user_id", table_name="route_impressions")
    op.drop_table("route_impressions")
    op.drop_table("user_preferences")
    op.drop_index("ix_users_kakao_id", table_name="users")
    op.drop_table("users")
