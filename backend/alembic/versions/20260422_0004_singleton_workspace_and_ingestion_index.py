"""Enforce singleton workspace and add ingestion queue index."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260422_0004"
down_revision = "20260420_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    existing_workspace_ids = list(
        bind.execute(sa.text("SELECT id FROM workspace ORDER BY id")).scalars()
    )
    if 1 not in existing_workspace_ids:
        canonical_name = (
            bind.execute(
                sa.text("SELECT name FROM workspace ORDER BY id LIMIT 1")
            ).scalar_one_or_none()
            or "Personal Workspace"
        )
        bind.execute(
            sa.text("INSERT INTO workspace (id, name) VALUES (:id, :name)"),
            {"id": 1, "name": canonical_name},
        )

    bind.execute(sa.text("UPDATE document SET workspace_id = 1 WHERE workspace_id <> 1"))
    bind.execute(sa.text("UPDATE chat_session SET workspace_id = 1 WHERE workspace_id <> 1"))
    bind.execute(sa.text("UPDATE chat_message SET workspace_id = 1 WHERE workspace_id <> 1"))
    bind.execute(sa.text("DELETE FROM workspace WHERE id <> 1"))

    op.create_check_constraint("ck_workspace_singleton_id", "workspace", "id = 1")
    op.create_index(
        "ix_ingestion_job_status_created_at_id",
        "ingestion_job",
        ["status", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_job_status_created_at_id", table_name="ingestion_job")
    op.drop_constraint("ck_workspace_singleton_id", "workspace", type_="check")
