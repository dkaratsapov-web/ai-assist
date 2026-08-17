"""ниша проекта

Revision ID: 6b87b9059524
Revises: 78f1bb3a98b0
Create Date: 2026-08-17 10:32:39.803837
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '6b87b9059524'
down_revision: str | None = '78f1bb3a98b0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ниша необязательна: у существующих проектов её просто нет, и это
    # нормальное состояние, а не незаполненные данные.
    op.add_column("projects", sa.Column("niche", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "niche")
