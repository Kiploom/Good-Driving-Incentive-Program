"""add driver notification table

Revision ID: 202502111200
Revises:
Create Date: 2025-02-11 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "202502111200"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "DriverNotification",
        sa.Column("NotificationID", sa.String(length=36), primary_key=True),
        sa.Column("DriverID", sa.String(length=36), nullable=False),
        sa.Column("Type", sa.String(length=50), nullable=False),
        sa.Column("Title", sa.String(length=255), nullable=False),
        sa.Column("Body", sa.Text(), nullable=False),
        sa.Column("Metadata", sa.JSON(), nullable=True),
        sa.Column("DeliveredVia", sa.String(length=50), nullable=True),
        sa.Column("IsRead", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "CreatedAt",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("ReadAt", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["DriverID"],
            ["Driver.DriverID"],
        ),
    )
    op.create_index(
        "ix_DriverNotification_DriverID", "DriverNotification", ["DriverID"], unique=False
    )
    op.create_index(
        "ix_DriverNotification_IsRead", "DriverNotification", ["IsRead"], unique=False
    )


def downgrade():
    op.drop_index("ix_DriverNotification_IsRead", table_name="DriverNotification")
    op.drop_index("ix_DriverNotification_DriverID", table_name="DriverNotification")
    op.drop_table("DriverNotification")

