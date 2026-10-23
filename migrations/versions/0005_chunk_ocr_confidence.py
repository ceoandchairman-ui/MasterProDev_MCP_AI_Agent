"""OCR confidence on knowledge chunks

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("ocr_confidence", sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "ocr_confidence")
