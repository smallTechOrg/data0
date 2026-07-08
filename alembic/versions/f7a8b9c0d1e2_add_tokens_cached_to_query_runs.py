"""add_tokens_cached_to_query_runs

Revision ID: f7a8b9c0d1e2
Revises: d4e5f6a7b8c9
Create Date: 2026-07-08 00:00:00.000000

C39 (Phase 14) — prompt-cache token accounting. Adds `query_runs.tokens_cached`:
of the run's cumulative `tokens_input`, how many were served from the provider's
prompt cache (Gemini `cached_content_token_count`, accumulated like
`tokens_input`). Nullable with server-default '0' so pre-Phase-14 rows read as 0
(SQLite ADD COLUMN applies the default to existing rows). Plain add_column —
SQLite-safe, no batch mode needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'query_runs',
        sa.Column('tokens_cached', sa.Integer(), nullable=True, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('query_runs', 'tokens_cached')
