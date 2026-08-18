"""мнение модели о странице

Revision ID: a4e21b7c9d30
Revises: 9c11ea989e11
Create Date: 2026-08-18 12:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'a4e21b7c9d30'
down_revision: str | None = '9c11ea989e11'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Умолчание нужно на время добавления: столбец не допускает пустоты, а
    # проверки в таблице уже есть. Сразу после снимается — значение
    # подставляет приложение, и оставленное в базе однажды с ним разойдётся.
    op.add_column(
        'site_audits',
        sa.Column(
            'review',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column('site_audits', 'review', server_default=None)


def downgrade() -> None:
    op.drop_column('site_audits', 'review')
