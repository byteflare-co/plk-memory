"""Make PostgreSQL search telemetry permanently hash-only.

Revision ID: 0004_postgres_query_hash_only
Revises: 0003_decision_telemetry
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_postgres_query_hash_only"
down_revision: str | Sequence[str] | None = "0003_decision_telemetry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE plk_memory.search_events DISABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "UPDATE plk_memory.search_events SET query_preview = NULL "
        "WHERE query_preview IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_search_events_query_preview_hash_only",
        "search_events",
        "query_preview IS NULL",
        schema="plk_memory",
    )
    op.execute(
        "ALTER TABLE plk_memory.search_events ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE plk_memory.search_events FORCE ROW LEVEL SECURITY"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_search_events_query_preview_hash_only",
        "search_events",
        type_="check",
        schema="plk_memory",
    )
