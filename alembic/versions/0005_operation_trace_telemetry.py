"""Add intent/action traces and link searches and decisions.

Revision ID: 0005_operation_trace_telemetry
Revises: 0004_postgres_query_hash_only
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_operation_trace_telemetry"
down_revision: str | Sequence[str] | None = "0004_postgres_query_hash_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE plk_memory.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE plk_memory.{table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""CREATE POLICY {table}_organization_isolation
        ON plk_memory.{table}
        USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
        WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid)
        """
    )


def upgrade() -> None:
    op.create_table(
        "intent_events",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("client", sa.String(255), nullable=False),
        sa.Column("operation_type", sa.String(64), nullable=False),
        sa.Column("intent_hash", sa.String(64), nullable=False),
        sa.Column("target_hash", sa.String(64)),
        sa.Column("side_effect", sa.String(32), nullable=False),
        sa.Column("plk_requirement", sa.String(32), nullable=False),
        sa.Column("no_search_reason", sa.String(32)),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "side_effect IN ('read', 'local_write', 'external_write', 'destructive')",
            name=op.f("ck_intent_events_intent_side_effect"),
        ),
        sa.CheckConstraint(
            "plk_requirement IN ('required', 'optional', 'not_required')",
            name=op.f("ck_intent_events_plk_requirement"),
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "trace_id", name=op.f("pk_intent_events")
        ),
        schema="plk_memory",
    )
    op.create_index(
        "ix_intent_events_org_created",
        "intent_events",
        ["organization_id", "created_at"],
        schema="plk_memory",
    )
    op.create_table(
        "action_events",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("action_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("client", sa.String(255), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(255)),
        sa.Column("target_hash", sa.String(64)),
        sa.Column("side_effect", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("decision_id", sa.String(64)),
        sa.Column("error_category", sa.String(64)),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "trace_id"],
            [
                "plk_memory.intent_events.organization_id",
                "plk_memory.intent_events.trace_id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "decision_id"],
            [
                "plk_memory.decision_events.organization_id",
                "plk_memory.decision_events.decision_id",
            ],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "phase IN ('attempted', 'completed')",
            name=op.f("ck_action_events_action_phase"),
        ),
        sa.CheckConstraint(
            "outcome IN ('pending', 'succeeded', 'failed', 'blocked', 'cancelled')",
            name=op.f("ck_action_events_action_outcome"),
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "event_id", name=op.f("pk_action_events")
        ),
        schema="plk_memory",
    )
    op.create_index(
        "ix_action_events_org_trace_created",
        "action_events",
        ["organization_id", "trace_id", "created_at"],
        schema="plk_memory",
    )
    op.add_column(
        "search_events", sa.Column("trace_id", sa.String(64)), schema="plk_memory"
    )
    op.add_column(
        "decision_events", sa.Column("trace_id", sa.String(64)), schema="plk_memory"
    )
    op.create_foreign_key(
        "fk_search_events_org_trace_intent_events",
        "search_events",
        "intent_events",
        ["organization_id", "trace_id"],
        ["organization_id", "trace_id"],
        source_schema="plk_memory",
        referent_schema="plk_memory",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_decision_events_org_trace_intent_events",
        "decision_events",
        "intent_events",
        ["organization_id", "trace_id"],
        ["organization_id", "trace_id"],
        source_schema="plk_memory",
        referent_schema="plk_memory",
        ondelete="SET NULL",
    )
    for table in ("intent_events", "action_events"):
        _enable_rls(table)
        op.execute(
            f"CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON plk_memory.{table} "
            "FOR EACH ROW EXECUTE FUNCTION plk_memory.reject_immutable_mutation()"
        )


def downgrade() -> None:
    op.drop_constraint(
        "fk_decision_events_org_trace_intent_events",
        "decision_events",
        schema="plk_memory",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_search_events_org_trace_intent_events",
        "search_events",
        schema="plk_memory",
        type_="foreignkey",
    )
    op.drop_column("decision_events", "trace_id", schema="plk_memory")
    op.drop_column("search_events", "trace_id", schema="plk_memory")
    op.drop_table("action_events", schema="plk_memory")
    op.drop_table("intent_events", schema="plk_memory")
