"""m2_cases_refunds"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_m2"
down_revision = "0002_m1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_policy_tenant_id", "policy_versions", ["tenant_id", "id"])
    op.create_table(
        "simulated_provider_operations",
        sa.Column("operation_key", sa.String(length=128), nullable=False),
        sa.Column("provider_operation_id", sa.String(length=64), nullable=False),
        sa.Column("amount_fen", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider_reference", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_fen > 0 AND status = 'SUCCEEDED'", name="ck_provider_result"),
        sa.PrimaryKeyConstraint("operation_key"),
        sa.UniqueConstraint("provider_operation_id"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_events_tenant_id"), "audit_events", ["tenant_id"], unique=False)
    op.create_table(
        "idempotency_records",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("client_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["tenant_id", "actor_id"], ["users.tenant_id", "users.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "actor_id", "operation", "client_key"),
    )
    op.create_table(
        "after_sales_cases",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("case_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requested_amount_fen", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("policy_digest", sa.String(length=64), nullable=False),
        sa.Column("rules_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("order_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("case_type IN ('RETURN_REFUND','DAMAGE_REFUND')", name="ck_case_type"),
        sa.CheckConstraint(
            "status IN ('DRAFT','WAITING_FOR_USER','PENDING_REVIEW','AWAITING_RETURN',"
            "'READY_TO_REFUND','REFUND_PENDING','MANUAL_INTERVENTION',"
            "'REFUNDED','REJECTED','CANCELLED')",
            name="ck_case_status",
        ),
        sa.CheckConstraint("requested_amount_fen > 0", name="ck_case_amount"),
        sa.CheckConstraint("version > 0 AND order_version > 0", name="ck_case_versions"),
        sa.ForeignKeyConstraint(
            ["policy_version"],
            ["policy_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "policy_version"], ["policy_versions.tenant_id", "policy_versions.id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            ["users.tenant_id", "users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["orders.tenant_id", "orders.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_after_sales_cases_tenant_id"), "after_sales_cases", ["tenant_id"], unique=False
    )
    op.create_index(
        "uq_active_case_order",
        "after_sales_cases",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('REFUNDED','REJECTED','CANCELLED')"),
    )
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "category IN ('LOGISTICS','MANUAL_AFTER_SALES')", name="ck_ticket_category"
        ),
        sa.CheckConstraint("status = 'OPEN'", name="ck_ticket_status"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            ["users.tenant_id", "users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["orders.tenant_id", "orders.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_support_tickets_tenant_id"), "support_tickets", ["tenant_id"], unique=False
    )
    op.create_table(
        "confirmations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_by", sa.String(length=64), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("case_version > 0", name="ck_confirmation_version"),
        sa.CheckConstraint(
            "(confirmed_at IS NULL) = (confirmed_by IS NULL)", name="ck_confirm_actor"
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR confirmed_at IS NOT NULL", name="ck_confirm_consumed"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["after_sales_cases.id"],
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_confirmations_case_id"), "confirmations", ["case_id"], unique=False)
    op.create_table(
        "refund_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("operation_key", sa.String(length=128), nullable=False),
        sa.Column("amount_fen", sa.Integer(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','RETRY','DONE','MANUAL')", name="ck_job_status"
        ),
        sa.CheckConstraint("amount_fen > 0 AND attempts >= 0", name="ck_job_amount_attempts"),
        sa.CheckConstraint("case_version > 0", name="ck_job_version"),
        sa.CheckConstraint("(lease_until IS NULL) = (lease_token IS NULL)", name="ck_job_lease"),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["after_sales_cases.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id"),
        sa.UniqueConstraint("operation_key"),
    )
    op.create_index("ix_job_due", "refund_jobs", ["status", "next_attempt_at"], unique=False)
    op.create_table(
        "refund_transactions",
        sa.Column("provider_operation_id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("operation_key", sa.String(length=128), nullable=False),
        sa.Column("amount_fen", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider_reference", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status = 'SUCCEEDED'", name="ck_transaction_success"),
        sa.CheckConstraint("amount_fen > 0", name="ck_transaction_amount"),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["after_sales_cases.id"],
        ),
        sa.PrimaryKeyConstraint("provider_operation_id"),
        sa.UniqueConstraint("case_id"),
        sa.UniqueConstraint("operation_key"),
    )
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("return_required", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("decision IN ('APPROVE','REJECT')", name="ck_review_decision"),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["after_sales_cases.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id"),
    )


def downgrade():
    op.drop_table("review_decisions")
    op.drop_table("refund_transactions")
    op.drop_index("ix_job_due", table_name="refund_jobs")
    op.drop_table("refund_jobs")
    op.drop_index(op.f("ix_confirmations_case_id"), table_name="confirmations")
    op.drop_table("confirmations")
    op.drop_index(op.f("ix_support_tickets_tenant_id"), table_name="support_tickets")
    op.drop_table("support_tickets")
    op.drop_index(
        "uq_active_case_order",
        table_name="after_sales_cases",
        postgresql_where=sa.text("status NOT IN ('REFUNDED','REJECTED','CANCELLED')"),
    )
    op.drop_index(op.f("ix_after_sales_cases_tenant_id"), table_name="after_sales_cases")
    op.drop_table("after_sales_cases")
    op.drop_table("idempotency_records")
    op.drop_index(op.f("ix_audit_events_tenant_id"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("simulated_provider_operations")
    op.drop_constraint("uq_policy_tenant_id", "policy_versions", type_="unique")
