"""FastAPI request dependencies, Origin checks, CSRF validation, and authentication."""
import os
import uuid
from typing import Generator, List, Optional
from urllib.parse import urlparse
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.domain.models import User
from app.infrastructure.tokens import (
    TokenError,
    TokenExpiredError,
    TokenInvalidError,
    get_token_manager,
)
from app.persistence import get_db

bearer_scheme = HTTPBearer(auto_error=False)

DEFAULT_ALLOWED_ORIGINS = {
    "http://localhost",
    "https://localhost",
    "http://127.0.0.1",
    "https://127.0.0.1",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8080",
    "https://agrodiagnostico.test",
}


def get_allowed_origins() -> set[str]:
    env_origins = os.environ.get("ALLOWED_ORIGINS")
    if env_origins:
        return {o.strip() for o in env_origins.split(",") if o.strip()}
    return DEFAULT_ALLOWED_ORIGINS


def get_correlation_id(
    x_correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID")
) -> uuid.UUID:
    """Validate incoming X-Correlation-ID or generate a new UUIDv4."""
    if not x_correlation_id:
        return uuid.uuid4()
    try:
        return uuid.UUID(x_correlation_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_CORRELATION_ID", "message": "X-Correlation-ID must be a valid UUID"},
        )


def validate_origin(request: Request) -> str:
    """Validate mandatory Origin header for sensitive endpoints."""
    origin = request.headers.get("Origin")
    if not origin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "MISSING_ORIGIN", "message": "Origin header is required"},
        )
    allowed = get_allowed_origins()
    # Normalize origin without trailing slash
    origin_clean = origin.rstrip("/")
    if origin_clean not in allowed:
        # Check if hostname matches allowed origins without port or scheme
        parsed = urlparse(origin_clean)
        if not any(parsed.hostname == urlparse(a).hostname for a in allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN_ORIGIN", "message": "Origin not allowed"},
            )
    return origin_clean


def validate_csrf(
    request: Request,
    x_csrf_token: Optional[str] = Header(None, alias="X-CSRF-Token"),
    csrf_token_cookie: Optional[str] = Cookie(None, alias="csrf_token"),
) -> str:
    """Verify that X-CSRF-Token matches the expected csrf_token cookie or session value."""
    if not x_csrf_token or not csrf_token_cookie or x_csrf_token != csrf_token_cookie:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "CSRF_TOKEN_MISMATCH", "message": "CSRF token validation failed"},
        )
    return x_csrf_token


def get_current_user(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Authenticate request using Ed25519 Bearer token."""
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Bearer token required"},
        )

    token_mgr = get_token_manager()
    try:
        payload = token_mgr.decode_access_token(auth.credentials)
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message": "Access token has expired"},
        )
    except TokenInvalidError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_INVALID", "message": "Access token is invalid"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_INVALID", "message": "Token missing subject"},
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_INVALID", "message": "Invalid user id in token"},
        )

    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "USER_NOT_FOUND", "message": "User not found"},
        )

    if user.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "ACCOUNT_INACTIVE", "message": "Account is not active"},
        )

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Ensure current authenticated user has ADMIN role."""
    if current_user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Administrator role required"},
        )
    return current_user
