from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.services.auth import (
    AuthenticatedUser,
    AuthenticationConfigurationError,
    AuthenticationError,
    verify_clerk_token,
)
from app.services.e2e import authenticate_e2e_token, create_chat_service, create_embedding_service
from app.services.llm import ChatService, EmbeddingService
from app.services.storage import StorageService

bearer_scheme = HTTPBearer(auto_error=False)


def get_storage_service(settings: Settings = Depends(get_settings)) -> StorageService:
    return StorageService(settings)


def get_embedding_service(settings: Settings = Depends(get_settings)) -> EmbeddingService:
    return create_embedding_service(settings)


def get_chat_service(settings: Settings = Depends(get_settings)) -> ChatService:
    return create_chat_service(settings)


def require_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    if settings.auth_mode == "local":
        return AuthenticatedUser(
            clerk_user_id=settings.local_dev_user_id,
            session_id=settings.local_dev_session_id,
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    e2e_user = authenticate_e2e_token(token=credentials.credentials, settings=settings)
    if e2e_user is not None:
        return e2e_user
    if settings.is_e2e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return verify_clerk_token(token=credentials.credentials, settings=settings)
    except AuthenticationConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="authentication is not configured",
        ) from exc
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
