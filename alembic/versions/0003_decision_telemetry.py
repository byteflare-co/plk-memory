"""Add tenant-scoped search and decision contribution telemetry.

Revision ID: 0003_decision_telemetry
Revises: 0002_runtime_workflows
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_decision_telemetry"
down_revision: str | Sequence[str] | None = "0002_runtime_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE plk_memory.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE plk_memory.{table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_organization_isolation
        ON plk_memory.{table}
        USING (
            organization_id = current_setting(
                'app.current_organization_id', true
            )::uuid
        )
        WITH CHECK (
            organization_id = current_setting(
                'app.current_organization_id', true
            )::uuid
        )
        """
    )


def upgrade() -> None:
    op.create_table(
        "search_events",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("search_id", sa.String(length=26), nullable=False),
        sa.Column("client", sa.String(length=255), nullable=False),
        sa.Column("query_preview", sa.Text(), nullable=True),
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "fact_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('ok', 'degraded', 'error')",
            name=op.f("ck_search_events_search_outcome"),
        ),
        sa.CheckConstraint(
            "hits >= 0", name=op.f("ck_search_events_nonnegative_hits")
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name=op.f("ck_search_events_nonnegative_latency"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(fact_refs) = 'array'",
            name=op.f("ck_search_events_fact_refs_array"),
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "search_id", name=op.f("pk_search_events")
        ),
        schema="plk_memory",
    )
    op.create_index(
        "ix_search_events_org_created",
        "search_events",
        ["organization_id", "created_at"],
        schema="plk_memory",
    )
    op.create_table(
        "decision_events",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("decision_id", sa.String(length=64), nullable=False),
        sa.Column("client", sa.String(length=255), nullable=False),
        sa.Column("effect", sa.String(length=32), nullable=False),
        sa.Column("no_use_reason", sa.String(length=32), nullable=True),
        sa.Column("search_ids", postgresql.JSONB(), nullable=False),
        sa.Column(
            "used_fact_refs",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "effect IN ('changed_action', 'prevented_error', 'confirmed', 'none')",
            name=op.f("ck_decision_events_decision_effect"),
        ),
        sa.CheckConstraint(
            "no_use_reason IS NULL OR no_use_reason IN "
            "('irrelevant', 'already_known', 'stale', 'conflict', 'insufficient')",
            name=op.f("ck_decision_events_decision_no_use_reason"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(search_ids) = 'array'",
            name=op.f("ck_decision_events_search_ids_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(used_fact_refs) = 'array'",
            name=op.f("ck_decision_events_used_fact_refs_array"),
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "decision_id", name=op.f("pk_decision_events")
        ),
        schema="plk_memory",
    )
    op.create_index(
        "ix_decision_events_org_created",
        "decision_events",
        ["organization_id", "created_at"],
        schema="plk_memory",
    )
    op.create_table(
        "decision_search_links",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("search_id", sa.String(length=26), nullable=False),
        sa.Column("decision_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "decision_id"],
            [
                "plk_memory.decision_events.organization_id",
                "plk_memory.decision_events.decision_id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "search_id"],
            [
                "plk_memory.search_events.organization_id",
                "plk_memory.search_events.search_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "search_id",
            name=op.f("pk_decision_search_links"),
        ),
        schema="plk_memory",
    )
    for table in ("search_events", "decision_events", "decision_search_links"):
        _enable_rls(table)
    for table in ("decision_events", "decision_search_links"):
        op.execute(
            f"CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE "
            f"ON plk_memory.{table} FOR EACH ROW "
            "EXECUTE FUNCTION plk_memory.reject_immutable_mutation()"
        )


def downgrade() -> None:
    for table in ("decision_search_links", "decision_events", "search_events"):
        op.drop_table(table, schema="plk_memory")
