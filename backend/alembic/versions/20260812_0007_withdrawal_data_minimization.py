"""Delete route impressions on withdrawal instead of only detaching the author.

user_id만 끊어도 route_impressions에는 profile과 feature_snapshot이 남아
이동 경로와 프로필을 추론할 수 있다. 익명화됐다고 보기 어렵고, 짝이 되는
후기가 함께 삭제되므로 학습 데이터로도 쓸 수 없어 함께 삭제한다.

시설 신고는 시설 식별·유지보수 가치가 있어 보존하되, 자유입력 description은
탈퇴 처리에서 비운다(스키마 변경 없음).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20260812_0007"
down_revision: Union[str, Sequence[str], None] = "20260812_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK = "route_impressions_user_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_FK, "route_impressions", type_="foreignkey")
    op.create_foreign_key(
        _FK,
        "route_impressions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(_FK, "route_impressions", type_="foreignkey")
    op.create_foreign_key(
        _FK,
        "route_impressions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
