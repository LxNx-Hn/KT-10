"""Replace the withdrawal queue with a separated minimal-retention record.

탈퇴 정책이 "전부 30일 보관 후 삭제"에서 "즉시 삭제 + 최소 정보만 분리
보관"으로 바뀌었다. 사용자 행이 탈퇴 시점에 사라지므로 기록이 users를
참조할 수 없고, 보관 항목도 완전히 달라져 테이블을 교체한다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0006"
down_revision: Union[str, Sequence[str], None] = "20260812_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 구 스키마는 "아직 삭제하지 않은 사용자"를 가리키는 대기열이라 새 스키마의
    # "이미 삭제된 사용자의 기록"으로 자동 변환할 수 없다. 남아 있던 신청은
    # 사용자 데이터가 그대로 있는 상태이므로 운영자가 새 정책으로 다시
    # 처리해야 한다.
    op.drop_index("ix_user_withdrawals_purge_after", table_name="user_withdrawals")
    op.drop_table("user_withdrawals")

    op.create_table(
        "user_withdrawals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_ref", sa.String(36), nullable=False),
        sa.Column("subject_hash", sa.String(64), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("purge_after", sa.DateTime(), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="completed",
        ),
        sa.Column("pending_provider_id", sa.String(64), nullable=True),
    )
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
