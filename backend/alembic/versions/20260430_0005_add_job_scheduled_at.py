"""Add scheduled retry timestamps to background jobs."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260430_0005"
down_revision = "20260422_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_job",
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "chat_session_title_job",
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.drop_index("ix_ingestion_job_status_created_at_id", table_name="ingestion_job")
    op.create_index(
        "ix_ingestion_job_status_scheduled_at_created_at_id",
        "ingestion_job",
        ["status", "scheduled_at", "created_at", "id"],
    )

    op.drop_index("ix_chat_session_title_job_status_id", table_name="chat_session_title_job")
    op.create_index(
        "ix_chat_session_title_job_status_scheduled_at_id",
        "chat_session_title_job",
        ["status", "scheduled_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_session_title_job_status_scheduled_at_id",
        table_name="chat_session_title_job",
    )
    op.create_index(
        "ix_chat_session_title_job_status_id",
        "chat_session_title_job",
        ["status", "id"],
    )

    op.drop_index(
        "ix_ingestion_job_status_scheduled_at_created_at_id",
        table_name="ingestion_job",
    )
    op.create_index(
        "ix_ingestion_job_status_created_at_id",
        "ingestion_job",
        ["status", "created_at", "id"],
    )

    op.drop_column("chat_session_title_job", "scheduled_at")
    op.drop_column("ingestion_job", "scheduled_at")
