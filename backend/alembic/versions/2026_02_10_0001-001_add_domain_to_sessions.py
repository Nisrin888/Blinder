"""Add domain column to sessions table.

Revision ID: 001
Revises:
Create Date: 2026-02-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "domain",
            sa.String(50),
            nullable=True,
            server_default=sa.text("'general'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "domain")
