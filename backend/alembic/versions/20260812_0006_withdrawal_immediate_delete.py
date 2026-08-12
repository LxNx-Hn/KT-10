"""Replace the withdrawal queue with a separated minimal-retention record.

탈퇴 정책이 "전부 30일 보관 후 삭제"에서 "즉시 삭제 + 최소 정보만 분리
보관"으로 바뀌었다. 사용자 행이 탈퇴 시점에 사라지므로 기록이 users를
참조할 수 없고, 보관 항목도 완전히 달라져 테이블을 교체한다.
"""
from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0006"
down_revision: Union[str, Sequence[str], None] = "20260812_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    old_withdrawals = sa.table(
        "user_withdrawals",
        sa.column("user_id", sa.String(36)),
        sa.column("requested_at", sa.DateTime()),
        sa.column("purge_after", sa.DateTime()),
        sa.column("provider_unlinked", sa.Boolean()),
    )
    users = sa.table(
        "users",
        sa.column("id", sa.String(36)),
        sa.column("kakao_id", sa.String(64)),
    )
    pending = list(bind.execute(
        sa.select(
            old_withdrawals.c.user_id,
            old_withdrawals.c.requested_at,
            old_withdrawals.c.purge_after,
            old_withdrawals.c.provider_unlinked,
            users.c.kakao_id,
        ).select_from(
            old_withdrawals.join(
                users,
                old_withdrawals.c.user_id == users.c.id,
            )
        )
    ).mappings())

    # 기존 대기열과 인덱스 이름이 겹치므로 임시 이름으로 새 테이블을 만든 뒤
    # 데이터를 옮기고 교체한다. 마이그레이션 전체는 한 트랜잭션이다.
    op.create_table(
        "user_withdrawals_v2",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_ref", sa.String(36), nullable=False),
        sa.Column("subject_hash", sa.String(64), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("purge_after", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("pending_provider_id", sa.String(64), nullable=True),
    )
    replacement = sa.table(
        "user_withdrawals_v2",
        sa.column("id", sa.String(36)),
        sa.column("user_ref", sa.String(36)),
        sa.column("subject_hash", sa.String(64)),
        sa.column("requested_at", sa.DateTime()),
        sa.column("purge_after", sa.DateTime()),
        sa.column("status", sa.String(32)),
        sa.column("pending_provider_id", sa.String(64)),
    )
    if pending:
        bind.execute(
            replacement.insert(),
            [
                {
                    "id": str(uuid4()),
                    "user_ref": row["user_id"],
                    # migration에는 운영 salt를 주입하지 않는다. 기존 대기 건은
                    # 역산 가능한 무염 해시를 만들지 않고 미보관한다.
                    "subject_hash": None,
                    "requested_at": row["requested_at"],
                    "purge_after": row["purge_after"],
                    "status": (
                        "completed"
                        if row["provider_unlinked"]
                        else "provider_unlink_pending"
                    ),
                    "pending_provider_id": (
                        None if row["provider_unlinked"] else row["kakao_id"]
                    ),
                }
                for row in pending
            ],
        )

    op.drop_index("ix_user_withdrawals_purge_after", table_name="user_withdrawals")
    op.drop_table("user_withdrawals")
    op.rename_table("user_withdrawals_v2", "user_withdrawals")

    # 구 정책의 탈퇴 신청도 새 정책대로 즉시 삭제한다. route_impressions의
    # CASCADE 전환은 다음 migration이므로 먼저 명시적으로 지워야 한다.
    pending_user_ids = [row["user_id"] for row in pending]
    if pending_user_ids:
        facility_reports = sa.table(
            "facility_reports",
            sa.column("user_id", sa.String(36)),
            sa.column("description", sa.Text()),
            sa.column("reported_lat", sa.Float()),
            sa.column("reported_lng", sa.Float()),
        )
        route_impressions = sa.table(
            "route_impressions",
            sa.column("user_id", sa.String(36)),
        )
        bind.execute(
            facility_reports.update()
            .where(facility_reports.c.user_id.in_(pending_user_ids))
            .values(description=None, reported_lat=None, reported_lng=None)
        )
        bind.execute(
            route_impressions.delete().where(
                route_impressions.c.user_id.in_(pending_user_ids)
            )
        )
        bind.execute(users.delete().where(users.c.id.in_(pending_user_ids)))

    op.create_index(
        "ix_user_withdrawals_user_ref", "user_withdrawals", ["user_ref"]
    )
    # 반복 탈퇴 판별 조회.
    op.create_index(
        "ix_user_withdrawals_subject_hash", "user_withdrawals", ["subject_hash"]
    )
    # 파기 배치의 기한 경과 조회.
    op.create_index(
        "ix_user_withdrawals_purge_after", "user_withdrawals", ["purge_after"]
    )
    # 연결 끊기 재시도 대상 조회.
    op.create_index(
        "ix_user_withdrawals_status", "user_withdrawals", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_withdrawals_status", table_name="user_withdrawals")
    op.drop_index("ix_user_withdrawals_purge_after", table_name="user_withdrawals")
    op.drop_index("ix_user_withdrawals_subject_hash", table_name="user_withdrawals")
    op.drop_index("ix_user_withdrawals_user_ref", table_name="user_withdrawals")
    op.drop_table("user_withdrawals")

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
    op.create_index(
        "ix_user_withdrawals_purge_after", "user_withdrawals", ["purge_after"]
    )
