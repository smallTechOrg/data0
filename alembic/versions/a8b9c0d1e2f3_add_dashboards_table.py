"""add_dashboards_table

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-07-12 00:00:00.000000

C40 (Phase 15) — agent-built dashboards. One new `dashboards` table: the
validated Dashboard spec v1 (incl. grid layout) + generation metadata for ONE
dataset. No FK constraints (repo convention; the C15 cascade is enforced in
code). Index on `dataset_id`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dashboards',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('dataset_id', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('command', sa.Text(), nullable=False),
        sa.Column('spec_json', sa.JSON(), nullable=False),
        sa.Column('generation_json', sa.JSON(), nullable=True),
        sa.Column('tokens_input', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tokens_output', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_dashboards_dataset_id', 'dashboards', ['dataset_id'])


def downgrade() -> None:
    op.drop_index('ix_dashboards_dataset_id', table_name='dashboards')
    op.drop_table('dashboards')
