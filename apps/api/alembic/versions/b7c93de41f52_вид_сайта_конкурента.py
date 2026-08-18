"""вид сайта конкурента

Revision ID: b7c93de41f52
Revises: a4e21b7c9d30
Create Date: 2026-08-18 13:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'b7c93de41f52'
down_revision: str | None = 'a4e21b7c9d30'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Умолчание на время добавления: столбец не допускает пустоты, а
    # конкуренты в таблице уже есть. Сразу после снимается — значение
    # подставляет приложение.
    op.add_column(
        'competitors',
        sa.Column(
            'kind',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column('competitors', 'kind', server_default=None)


def downgrade() -> None:
    op.drop_column('competitors', 'kind')
