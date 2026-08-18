"""доступ к отдельным проектам

Revision ID: c1f4a8b6e207
Revises: b7c93de41f52
Create Date: 2026-08-18 14:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'c1f4a8b6e207'
down_revision: str | None = 'b7c93de41f52'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Значение по умолчанию остаётся в базе, а не снимается, как у остальных
    # столбцов. Здесь это не про подстановку приложением, а про смысл: участник,
    # заведённый любым путём, по умолчанию видит все проекты, и появление
    # списка доступов никого ничего не лишает.
    op.add_column(
        'users',
        sa.Column(
            'all_projects', sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )

    op.create_table(
        'project_access',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('granted_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['granted_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'project_id', name='uq_project_access_user_project'),
    )
    op.create_index('ix_project_access_user', 'project_access', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_project_access_user', table_name='project_access')
    op.drop_table('project_access')
    op.drop_column('users', 'all_projects')
