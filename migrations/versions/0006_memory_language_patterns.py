"""memory language and embedding; reviewed response patterns

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memories", sa.Column("language", sa.String(8), nullable=False, server_default="en"))
    op.add_column("memories", sa.Column("embedding", sa.JSON, nullable=True))
    op.create_table(
        "response_patterns",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("intent", sa.String(40), nullable=False),
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("user_text", sa.Text, nullable=False),
        sa.Column("reply_text", sa.Text, nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="proposed"),
        sa.Column("reviewed_by", sa.String(64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_patterns_intent_status", "response_patterns", ["intent", "status"])


def downgrade() -> None:
    op.drop_index("ix_patterns_intent_status", table_name="response_patterns")
    op.drop_table("response_patterns")
    op.drop_column("memories", "embedding")
    op.drop_column("memories", "language")
