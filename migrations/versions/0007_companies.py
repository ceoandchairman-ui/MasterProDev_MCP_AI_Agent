"""customer companies; users link to a company

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False),
        sa.Column("industry", sa.String(80), nullable=True),
        sa.Column("size_band", sa.String(40), nullable=True),
        sa.Column("website", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name_key", name="uq_companies_tenant_name"),
    )
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("company_id", sa.String(32), nullable=True))
        batch.create_foreign_key("fk_users_company", "companies", ["company_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("fk_users_company", type_="foreignkey")
        batch.drop_column("company_id")
    op.drop_table("companies")
