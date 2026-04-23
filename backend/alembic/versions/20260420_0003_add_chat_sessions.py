"""Add chat sessions and session title jobs."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260420_0003"
down_revision = "20260419_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_session",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("clerk_user_id", sa.String(length=255), nullable=False),
        sa.Column(
            "title",
            sa.String(length=255),
            nullable=False,
            server_default="New session",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_chat_session_workspace_id_clerk_user_id_updated_at_id",
        "chat_session",
        ["workspace_id", "clerk_user_id", "updated_at", "id"],
    )

    op.create_table(
        "chat_session_title_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("chat_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("session_id"),
    )
    op.create_index(
        "ix_chat_session_title_job_status_id",
        "chat_session_title_job",
        ["status", "id"],
    )

    op.add_column("chat_message", sa.Column("session_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_chat_message_session_id_chat_session",
        "chat_message",
        "chat_session",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_chat_message_session_id_id",
        "chat_message",
        ["session_id", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_message_session_id_id", table_name="chat_message")
    op.drop_constraint(
        "fk_chat_message_session_id_chat_session",
        "chat_message",
        type_="foreignkey",
    )
    op.drop_column("chat_message", "session_id")

    op.drop_index("ix_chat_session_title_job_status_id", table_name="chat_session_title_job")
    op.drop_table("chat_session_title_job")

    op.drop_index(
        "ix_chat_session_workspace_id_clerk_user_id_updated_at_id",
        table_name="chat_session",
    )
    op.drop_table("chat_session")
