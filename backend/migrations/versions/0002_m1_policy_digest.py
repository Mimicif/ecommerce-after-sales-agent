"""Track published policy content integrity without rewriting existing business data."""

import hashlib
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_m1"
down_revision = "0001_m0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("policy_versions", sa.Column("content_digest", sa.String(64), nullable=True))
    policies = sa.table(
        "policy_versions",
        sa.column("id", sa.String),
        sa.column("rules", postgresql.JSONB),
        sa.column("clauses", postgresql.JSONB),
        sa.column("content_digest", sa.String),
    )
    connection = op.get_bind()
    for row in connection.execute(sa.select(policies.c.id, policies.c.rules, policies.c.clauses)):
        payload = json.dumps(
            {"rules": row.rules, "clauses": row.clauses},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        connection.execute(
            policies.update().where(policies.c.id == row.id).values(content_digest=digest)
        )
    op.alter_column("policy_versions", "content_digest", nullable=False)


def downgrade():
    op.drop_column("policy_versions", "content_digest")
