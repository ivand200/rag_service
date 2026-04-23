from __future__ import annotations

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, ChatMessage, ChatSession, ChatSessionTitleJob, JobStatus, Workspace


def test_chat_session_schema_links_sessions_title_jobs_and_messages() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    db = session_factory()
    try:
        workspace = Workspace(name="Personal Workspace")
        db.add(workspace)
        db.flush()

        chat_session = ChatSession(workspace_id=workspace.id, clerk_user_id="user_123")
        db.add(chat_session)
        db.flush()

        title_job = ChatSessionTitleJob(session_id=chat_session.id, status=JobStatus.queued.value)
        message = ChatMessage(
            workspace_id=workspace.id,
            clerk_user_id="user_123",
            session_id=chat_session.id,
            role="user",
            content="How does retrieval work here?",
            grounded=False,
            citations_json=[],
        )
        db.add_all([title_job, message])
        db.commit()

        db.refresh(chat_session)
        assert chat_session.title == "New session"
        assert chat_session.title_job is not None
        assert chat_session.title_job.status == JobStatus.queued.value
        assert [saved_message.content for saved_message in chat_session.messages] == [
            "How does retrieval work here?"
        ]
        assert workspace.sessions[0].clerk_user_id == "user_123"
        assert workspace.messages[0].session_id == chat_session.id
    finally:
        db.close()

    inspector = inspect(engine)
    session_columns = {column["name"]: column for column in inspector.get_columns("chat_message")}
    assert session_columns["session_id"]["nullable"] is True
    assert {index["name"] for index in inspector.get_indexes("chat_message")} >= {
        "ix_chat_message_session_id_id",
        "ix_chat_message_workspace_id_clerk_user_id_id",
    }
    assert {index["name"] for index in inspector.get_indexes("chat_session")} >= {
        "ix_chat_session_workspace_id_clerk_user_id_updated_at_id"
    }
    assert {index["name"] for index in inspector.get_indexes("chat_session_title_job")} >= {
        "ix_chat_session_title_job_status_id"
    }
    assert {index["name"] for index in inspector.get_indexes("ingestion_job")} >= {
        "ix_ingestion_job_status_created_at_id"
    }
