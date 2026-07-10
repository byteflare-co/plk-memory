"""SQLAlchemy Core schema for PostgreSQL-primary PLK storage.

Every tenant-owned key and foreign key includes ``organization_id``.  Facts
hold the current projection while revisions are immutable audit/content rows.
The database migration additionally enables row-level security for every table.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

SCHEMA = "plk_memory"

metadata = MetaData(
    schema=SCHEMA,
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    },
)


knowledge_facts = Table(
    "knowledge_facts",
    metadata,
    Column("organization_id", UUID(as_uuid=True), nullable=False),
    Column("fact_id", String(64), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("namespace", String(255), nullable=False),
    Column("status", String(32), nullable=False),
    Column("current_version", Integer, nullable=False),
    Column("current_revision_id", UUID(as_uuid=True), nullable=False),
    Column("created_by", String(255), nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column("updated_by", String(255), nullable=False),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    PrimaryKeyConstraint("organization_id", "fact_id"),
    UniqueConstraint(
        "organization_id",
        "current_revision_id",
        name="uq_knowledge_facts_org_current_revision",
    ),
    CheckConstraint(
        "kind IN ('philosophy', 'logic', 'knowhow')",
        name="fact_kind",
    ),
    CheckConstraint(
        "status IN ('active', 'invalidated')",
        name="fact_status",
    ),
    CheckConstraint("current_version >= 1", name="positive_version"),
)


knowledge_fact_revisions = Table(
    "knowledge_fact_revisions",
    metadata,
    Column("organization_id", UUID(as_uuid=True), nullable=False),
    Column("revision_id", UUID(as_uuid=True), nullable=False),
    Column("fact_id", String(64), nullable=False),
    Column("version", Integer, nullable=False),
    Column("kind", String(32), nullable=False),
    Column("statement", Text, nullable=False),
    Column("why", Text, nullable=False),
    Column("how_to_apply", Text, nullable=False),
    Column("sources", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("source_type", String(32), nullable=False),
    Column("namespace", String(255), nullable=False),
    Column("tags", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("body", Text, nullable=False, server_default=""),
    Column("status", String(32), nullable=False),
    Column("invalidation_reason", Text),
    Column("change_reason", Text, nullable=False),
    Column("actor_id", String(255), nullable=False),
    Column("actor_type", String(32), nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    PrimaryKeyConstraint("organization_id", "revision_id"),
    UniqueConstraint(
        "organization_id",
        "fact_id",
        "version",
        name="uq_knowledge_fact_revisions_org_fact_version",
    ),
    ForeignKeyConstraint(
        ["organization_id", "fact_id"],
        [
            f"{SCHEMA}.knowledge_facts.organization_id",
            f"{SCHEMA}.knowledge_facts.fact_id",
        ],
        name="fk_knowledge_fact_revisions_org_fact",
        ondelete="CASCADE",
        deferrable=True,
        initially="DEFERRED",
    ),
    CheckConstraint("version >= 1", name="positive_version"),
    CheckConstraint(
        "kind IN ('philosophy', 'logic', 'knowhow')",
        name="fact_kind",
    ),
    CheckConstraint(
        "status IN ('active', 'invalidated')",
        name="fact_status",
    ),
    CheckConstraint(
        "source_type IN ('user', 'agent', 'external-untrusted')",
        name="source_type",
    ),
    CheckConstraint(
        "actor_type IN ('human', 'agent', 'service')",
        name="actor_type",
    ),
    CheckConstraint("jsonb_typeof(sources) = 'array'", name="sources_array"),
    CheckConstraint("jsonb_typeof(tags) = 'array'", name="tags_array"),
)

# This deferred circular FK lets one transaction insert the fact head and its
# first immutable revision without temporarily exposing an incomplete head.
knowledge_facts.append_constraint(
    ForeignKeyConstraint(
        ["organization_id", "current_revision_id"],
        [
            f"{SCHEMA}.knowledge_fact_revisions.organization_id",
            f"{SCHEMA}.knowledge_fact_revisions.revision_id",
        ],
        name="fk_knowledge_facts_org_current_revision",
        deferrable=True,
        initially="DEFERRED",
        use_alter=True,
    )
)


knowledge_relations = Table(
    "knowledge_relations",
    metadata,
    Column("organization_id", UUID(as_uuid=True), nullable=False),
    Column("relation_id", UUID(as_uuid=True), nullable=False),
    Column("relation_type", String(32), nullable=False),
    Column("from_fact_id", String(64), nullable=False),
    Column("to_fact_id", String(64), nullable=False),
    Column("created_revision_id", UUID(as_uuid=True), nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    PrimaryKeyConstraint("organization_id", "relation_id"),
    UniqueConstraint(
        "organization_id",
        "relation_type",
        "from_fact_id",
        "to_fact_id",
        name="uq_knowledge_relations_org_type_from_to",
    ),
    ForeignKeyConstraint(
        ["organization_id", "from_fact_id"],
        [
            f"{SCHEMA}.knowledge_facts.organization_id",
            f"{SCHEMA}.knowledge_facts.fact_id",
        ],
        name="fk_knowledge_relations_org_from_fact",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["organization_id", "to_fact_id"],
        [
            f"{SCHEMA}.knowledge_facts.organization_id",
            f"{SCHEMA}.knowledge_facts.fact_id",
        ],
        name="fk_knowledge_relations_org_to_fact",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["organization_id", "created_revision_id"],
        [
            f"{SCHEMA}.knowledge_fact_revisions.organization_id",
            f"{SCHEMA}.knowledge_fact_revisions.revision_id",
        ],
        name="fk_knowledge_relations_org_created_revision",
    ),
    CheckConstraint(
        "relation_type IN ('supersedes', 'related_to')", name="relation_type"
    ),
    CheckConstraint("from_fact_id <> to_fact_id", name="different_facts"),
)


idempotency_records = Table(
    "idempotency_records",
    metadata,
    Column("organization_id", UUID(as_uuid=True), nullable=False),
    Column("idempotency_key", String(255), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("operation", String(64), nullable=False),
    Column("resource_type", String(64), nullable=False),
    Column("resource_id", String(255)),
    Column("response_body", JSONB),
    Column("event_id", UUID(as_uuid=True)),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column("expires_at", DateTime(timezone=True)),
    PrimaryKeyConstraint("organization_id", "idempotency_key"),
)


outbox_events = Table(
    "outbox_events",
    metadata,
    Column("organization_id", UUID(as_uuid=True), nullable=False),
    Column("event_id", UUID(as_uuid=True), nullable=False),
    Column("aggregate_type", String(64), nullable=False),
    Column("aggregate_id", String(255), nullable=False),
    Column("aggregate_version", Integer, nullable=False),
    Column("event_type", String(128), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column(
        "occurred_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column(
        "available_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("lease_owner", String(255)),
    Column("lease_until", DateTime(timezone=True)),
    Column("processed_at", DateTime(timezone=True)),
    Column("last_error", Text),
    PrimaryKeyConstraint("organization_id", "event_id"),
    UniqueConstraint(
        "organization_id",
        "aggregate_type",
        "aggregate_id",
        "aggregate_version",
        "event_type",
        name="uq_outbox_events_org_aggregate_version_type",
    ),
    CheckConstraint("aggregate_version >= 1", name="positive_aggregate_version"),
    CheckConstraint("attempts >= 0", name="nonnegative_attempts"),
)


approval_requests = Table(
    "approval_requests",
    metadata,
    Column("organization_id", UUID(as_uuid=True), nullable=False),
    Column("request_id", UUID(as_uuid=True), nullable=False),
    Column("fact_id", String(64), nullable=False),
    Column("source_version", Integer, nullable=False),
    Column("status", String(32), nullable=False, server_default="pending"),
    Column("requested_by", String(255), nullable=False),
    Column("request_reason", Text, nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    PrimaryKeyConstraint("organization_id", "request_id"),
    ForeignKeyConstraint(
        ["organization_id", "fact_id", "source_version"],
        [
            f"{SCHEMA}.knowledge_fact_revisions.organization_id",
            f"{SCHEMA}.knowledge_fact_revisions.fact_id",
            f"{SCHEMA}.knowledge_fact_revisions.version",
        ],
        name="fk_approval_requests_org_fact_version",
    ),
    CheckConstraint(
        "status IN ('pending', 'approved', 'rejected', 'stale', 'cancelled')",
        name="approval_status",
    ),
)


approval_decisions = Table(
    "approval_decisions",
    metadata,
    Column("organization_id", UUID(as_uuid=True), nullable=False),
    Column("decision_id", UUID(as_uuid=True), nullable=False),
    Column("request_id", UUID(as_uuid=True), nullable=False),
    Column("decision", String(32), nullable=False),
    Column("rationale", Text, nullable=False),
    Column("actor_id", String(255), nullable=False),
    Column("actor_type", String(32), nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    PrimaryKeyConstraint("organization_id", "decision_id"),
    UniqueConstraint(
        "organization_id",
        "request_id",
        name="uq_approval_decisions_org_request",
    ),
    ForeignKeyConstraint(
        ["organization_id", "request_id"],
        [
            f"{SCHEMA}.approval_requests.organization_id",
            f"{SCHEMA}.approval_requests.request_id",
        ],
        name="fk_approval_decisions_org_request",
        ondelete="CASCADE",
    ),
    CheckConstraint("decision IN ('approved', 'rejected')", name="approval_decision"),
    CheckConstraint(
        "actor_type IN ('human', 'agent', 'service')",
        name="actor_type",
    ),
)


search_projection_state = Table(
    "search_projection_state",
    metadata,
    Column("organization_id", UUID(as_uuid=True), nullable=False),
    Column("backend", String(64), nullable=False),
    Column("fact_id", String(64), nullable=False),
    Column("indexed_version", Integer, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("backend_refs", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("last_event_id", UUID(as_uuid=True), nullable=False),
    Column("indexed_at", DateTime(timezone=True), nullable=False),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    PrimaryKeyConstraint("organization_id", "backend", "fact_id"),
    ForeignKeyConstraint(
        ["organization_id", "fact_id"],
        [
            f"{SCHEMA}.knowledge_facts.organization_id",
            f"{SCHEMA}.knowledge_facts.fact_id",
        ],
        name="fk_search_projection_state_org_fact",
        ondelete="CASCADE",
    ),
    CheckConstraint("indexed_version >= 1", name="positive_indexed_version"),
    CheckConstraint("jsonb_typeof(backend_refs) = 'array'", name="backend_refs_array"),
)


audit_events = Table(
    "audit_events",
    metadata,
    Column("organization_id", UUID(as_uuid=True), nullable=False),
    Column("audit_id", UUID(as_uuid=True), nullable=False),
    Column("action", String(128), nullable=False),
    Column("resource_type", String(64), nullable=False),
    Column("resource_id", String(255), nullable=False),
    Column("actor_id", String(255), nullable=False),
    Column("actor_type", String(32), nullable=False),
    Column("request_id", String(255)),
    Column("correlation_id", String(255)),
    Column("details", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    PrimaryKeyConstraint("organization_id", "audit_id"),
    CheckConstraint(
        "actor_type IN ('human', 'agent', 'service')",
        name="actor_type",
    ),
)


Index(
    "ix_knowledge_facts_org_namespace_status",
    knowledge_facts.c.organization_id,
    knowledge_facts.c.namespace,
    knowledge_facts.c.status,
)
Index(
    "ix_knowledge_fact_revisions_org_fact_created",
    knowledge_fact_revisions.c.organization_id,
    knowledge_fact_revisions.c.fact_id,
    knowledge_fact_revisions.c.created_at,
)
Index(
    "uq_knowledge_relations_one_active_superseder",
    knowledge_relations.c.organization_id,
    knowledge_relations.c.to_fact_id,
    unique=True,
    postgresql_where=(
        (knowledge_relations.c.relation_type == "supersedes")
        & knowledge_relations.c.is_active
    ),
)
Index(
    "ix_outbox_events_claimable",
    outbox_events.c.available_at,
    outbox_events.c.occurred_at,
    postgresql_where=outbox_events.c.processed_at.is_(None),
)
Index(
    "ix_approval_requests_org_status_created",
    approval_requests.c.organization_id,
    approval_requests.c.status,
    approval_requests.c.created_at,
)
Index(
    "ix_audit_events_org_resource_created",
    audit_events.c.organization_id,
    audit_events.c.resource_type,
    audit_events.c.resource_id,
    audit_events.c.created_at,
)


TENANT_TABLES = tuple(metadata.tables.values())
