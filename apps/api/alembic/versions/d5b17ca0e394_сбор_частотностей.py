"""сбор частотностей

Revision ID: d5b17ca0e394
Revises: c1f4a8b6e207
Create Date: 2026-08-18 16:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'd5b17ca0e394'
down_revision: str | None = 'c1f4a8b6e207'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'keyword_collections',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'not_started',
                'queued',
                'running',
                'needs_review',
                'completed',
                'failed',
                name='module_status',
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            'masks',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column('added', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('requests', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('resumes_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_reason', sa.String(length=500), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_keyword_collections_project_created',
        'keyword_collections',
        ['project_id', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_keyword_collections_project_created', table_name='keyword_collections')
    op.drop_table('keyword_collections')
