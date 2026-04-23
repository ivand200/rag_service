"""Add Clerk user ownership to chat messages."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260419_0002"
down_revision = "20260411_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_message", sa.Column("clerk_user_id", sa.String(length=255), nullable=True))
    op.create_index(
        "ix_chat_message_workspace_id_clerk_user_id_id",
        "chat_message",
        ["workspace_id", "clerk_user_id", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_message_workspace_id_clerk_user_id_id", table_name="chat_message")
    op.drop_column("chat_message", "clerk_user_id")
