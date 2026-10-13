from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    roles: Mapped[list[str]] = mapped_column(JSONB)
    customer_id: Mapped[str | None] = mapped_column(String(64))


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id", "customer_id"], ["users.tenant_id", "users.id"]),
        CheckConstraint("paid_amount_fen >= 0", name="ck_order_paid_nonnegative"),
        CheckConstraint(
            "refunded_amount_fen >= 0 AND refunded_amount_fen <= paid_amount_fen",
            name="ck_order_refunded_range",
        ),
        CheckConstraint("version > 0", name="ck_order_version_positive"),
        CheckConstraint(
            "product_category IN ('STANDARD','CUSTOM','PERISHABLE')", name="ck_order_category"
        ),
        CheckConstraint("status IN ('DELIVERED','IN_TRANSIT')", name="ck_order_status"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    product_category: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    paid_amount_fen: Mapped[int] = mapped_column(Integer)
    refunded_amount_fen: Mapped[int] = mapped_column(Integer)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)


class LogisticsEvent(Base):
    __tablename__ = "logistics_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["users.tenant_id", "users.id"]),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    owner_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)


class Policy(Base):
    __tablename__ = "policy_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_policy_tenant_id"),
        CheckConstraint("effective_to > effective_from", name="ck_policy_period"),
        CheckConstraint("status IN ('PUBLISHED','DRAFT')", name="ck_policy_status"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rules: Mapped[dict] = mapped_column(JSONB)
    clauses: Mapped[list[dict]] = mapped_column(JSONB)
    content_digest: Mapped[str] = mapped_column(String(64))


class PolicyChunk(Base):
    __tablename__ = "policy_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_version"], ["policy_versions.tenant_id", "policy_versions.id"]
        ),
        CheckConstraint(
            "intent IN ('RETURN_REFUND','DAMAGE_REFUND','LOGISTICS','ALL')", name="ck_chunk_intent"
        ),
        Index("ix_policy_chunk_scope", "tenant_id", "policy_version", "intent"),
    )
    policy_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    intent: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)


class DevSession(Base):
    __tablename__ = "dev_sessions"
    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SeedImport(Base):
    __tablename__ = "seed_imports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_digest: Mapped[str] = mapped_column(String(64))
    fixture_version: Mapped[str] = mapped_column(String(64))
    policy_schema_version: Mapped[str] = mapped_column(String(64))
    fixture_clock: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


TERMINAL_CASES = ("REFUNDED", "REJECTED", "CANCELLED")


class AfterSalesCase(Base):
    __tablename__ = "after_sales_cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_version"], ["policy_versions.tenant_id", "policy_versions.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "order_id"], ["orders.tenant_id", "orders.id"]),
        ForeignKeyConstraint(["tenant_id", "created_by"], ["users.tenant_id", "users.id"]),
        CheckConstraint("requested_amount_fen > 0", name="ck_case_amount"),
        CheckConstraint("version > 0 AND order_version > 0", name="ck_case_versions"),
        CheckConstraint("case_type IN ('RETURN_REFUND','DAMAGE_REFUND')", name="ck_case_type"),
        CheckConstraint(
            "status IN ('DRAFT','WAITING_FOR_USER','PENDING_REVIEW','AWAITING_RETURN',"
            "'READY_TO_REFUND','REFUND_PENDING','MANUAL_INTERVENTION',"
            "'REFUNDED','REJECTED','CANCELLED')",
            name="ck_case_status",
        ),
        Index(
            "uq_active_case_order",
            "order_id",
            unique=True,
            postgresql_where=text("status NOT IN ('REFUNDED','REJECTED','CANCELLED')"),
        ),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    order_id: Mapped[str] = mapped_column(String(64))
    case_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB)
    requested_amount_fen: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[str] = mapped_column(ForeignKey("policy_versions.id"))
    policy_digest: Mapped[str] = mapped_column(String(64))
    rules_snapshot: Mapped[dict] = mapped_column(JSONB)
    order_version: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Confirmation(Base):
    __tablename__ = "confirmations"
    __table_args__ = (
        CheckConstraint("case_version > 0", name="ck_confirmation_version"),
        CheckConstraint("(confirmed_at IS NULL) = (confirmed_by IS NULL)", name="ck_confirm_actor"),
        CheckConstraint(
            "consumed_at IS NULL OR confirmed_at IS NOT NULL", name="ck_confirm_consumed"
        ),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("after_sales_cases.id"), index=True)
    case_version: Mapped[int] = mapped_column(Integer)
    payload_digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    __table_args__ = (
        UniqueConstraint("case_id"),
        CheckConstraint("decision IN ('APPROVE','REJECT')", name="ck_review_decision"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("after_sales_cases.id"))
    case_version: Mapped[int] = mapped_column(Integer)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(16))
    return_required: Mapped[bool] = mapped_column()
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RefundJob(Base):
    __tablename__ = "refund_jobs"
    __table_args__ = (
        UniqueConstraint("case_id"),
        UniqueConstraint("operation_key"),
        CheckConstraint("amount_fen > 0 AND attempts >= 0", name="ck_job_amount_attempts"),
        CheckConstraint("case_version > 0", name="ck_job_version"),
        CheckConstraint("(lease_until IS NULL) = (lease_token IS NULL)", name="ck_job_lease"),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','RETRY','DONE','MANUAL')", name="ck_job_status"
        ),
        Index("ix_job_due", "status", "next_attempt_at"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("after_sales_cases.id"))
    operation_key: Mapped[str] = mapped_column(String(128))
    amount_fen: Mapped[int] = mapped_column(Integer)
    case_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(String(64))


class RefundTransaction(Base):
    __tablename__ = "refund_transactions"
    __table_args__ = (
        UniqueConstraint("case_id"),
        UniqueConstraint("operation_key"),
        CheckConstraint("amount_fen > 0", name="ck_transaction_amount"),
        CheckConstraint("status = 'SUCCEEDED'", name="ck_transaction_success"),
    )
    provider_operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("after_sales_cases.id"))
    operation_key: Mapped[str] = mapped_column(String(128))
    amount_fen: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    provider_reference: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SimulatedProviderOperation(Base):
    __tablename__ = "simulated_provider_operations"
    __table_args__ = (
        UniqueConstraint("provider_operation_id"),
        CheckConstraint("amount_fen > 0 AND status = 'SUCCEEDED'", name="ck_provider_result"),
    )
    operation_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider_operation_id: Mapped[str] = mapped_column(String(64))
    amount_fen: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    provider_reference: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["users.tenant_id", "users.id"]),
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    operation: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "order_id"], ["orders.tenant_id", "orders.id"]),
        ForeignKeyConstraint(["tenant_id", "created_by"], ["users.tenant_id", "users.id"]),
        CheckConstraint(
            "category IN ('LOGISTICS','MANUAL_AFTER_SALES')", name="ck_ticket_category"
        ),
        CheckConstraint("status = 'OPEN'", name="ck_ticket_status"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    order_id: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict] = mapped_column(JSONB)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["users.tenant_id", "users.id"]),
        CheckConstraint("next_seq > 0", name="ck_conversation_seq"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    owner_id: Mapped[str] = mapped_column(String(64))
    next_seq: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq"),
        UniqueConstraint("conversation_id", "client_message_id"),
        UniqueConstraint("run_id", "role"),
        CheckConstraint("role IN ('user','assistant') AND seq > 0", name="ck_message_role_seq"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    client_message_id: Mapped[str | None] = mapped_column(String(128))
    request_digest: Mapped[str | None] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["users.tenant_id", "users.id"]),
        UniqueConstraint("input_message_id"),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','WAITING_FOR_USER','COMPLETED','FAILED','CANCELLED')",
            name="ck_run_status",
        ),
        CheckConstraint(
            "action IN ('CONSULT','APPLY_AFTER_SALES','CREATE_TICKET','SUBMIT_CONFIRMED')",
            name="ck_run_action",
        ),
        CheckConstraint(
            "model_calls BETWEEN 0 AND 8 AND tool_calls BETWEEN 0 AND 12", name="ck_run_budget"
        ),
        CheckConstraint("(lease_token IS NULL) = (lease_until IS NULL)", name="ck_run_lease"),
        Index(
            "uq_conversation_active_run",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('QUEUED','RUNNING')"),
        ),
        Index("ix_run_claim", "status", "lease_until"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    conversation_id: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(64))
    input_message_id: Mapped[str] = mapped_column(ForeignKey("chat_messages.id"))
    action: Mapped[str] = mapped_column(String(32))
    target_order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"))
    status: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    tool_version: Mapped[str] = mapped_column(String(32))
    model_calls: Mapped[int] = mapped_column(Integer)
    tool_calls: Mapped[int] = mapped_column(Integer)
    next_event_seq: Mapped[int] = mapped_column(Integer)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    response: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEvent(Base):
    __tablename__ = "run_events"
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentInvocation(Base):
    __tablename__ = "agent_invocations"
    __table_args__ = (CheckConstraint("kind IN ('MODEL','TOOL')", name="ck_invocation_kind"),)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), primary_key=True)
    step: Mapped[str] = mapped_column(String(32), primary_key=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict | None] = mapped_column(JSONB)


class GraphCheckpoint(Base):
    __tablename__ = "graph_checkpoints"
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(String(64))
    checkpoint: Mapped[dict] = mapped_column(JSONB)
    checkpoint_metadata: Mapped[dict] = mapped_column(JSONB)


class GraphWrite(Base):
    __tablename__ = "graph_writes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "checkpoint_id"],
            ["graph_checkpoints.run_id", "graph_checkpoints.checkpoint_id"],
        ),
    )
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict | list | str | int | None] = mapped_column(JSONB, nullable=True)
