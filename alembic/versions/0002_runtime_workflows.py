"""Add runtime workflow state required after the PostgreSQL foundation.

Revision ID: 0002_runtime_workflows
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_runtime_workflows"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        schema="plk_memory",
    )
    op.add_column(
        "search_projection_state",
        sa.Column("partition", sa.String(length=255), nullable=True),
        schema="plk_memory",
    )
    op.create_index(
        "uq_approval_requests_one_pending_per_fact",
        "approval_requests",
        ["organization_id", "fact_id"],
        unique=True,
        schema="plk_memory",
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_approval_requests_one_pending_per_fact",
        table_name="approval_requests",
        schema="plk_memory",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_column(
        "search_projection_state", "partition", schema="plk_memory"
    )
    op.drop_column("outbox_events", "dead_lettered_at", schema="plk_memory")
