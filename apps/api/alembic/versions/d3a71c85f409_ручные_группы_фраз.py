"""ручные группы фраз

Revision ID: d3a71c85f409
Revises: c1f4a8b6e207
Create Date: 2026-08-18 18:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd3a71c85f409'
down_revision: str | None = 'd5b17ca0e394'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Умолчание остаётся в базе: у всех существующих фраз группа проставлена
    # расчётом, а не человеком, и это верно по смыслу, а не только на время
    # миграции.
    op.add_column(
        'keywords',
        sa.Column(
            'cluster_manual', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column('keywords', 'cluster_manual')
