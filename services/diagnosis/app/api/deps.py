"""FastAPI dependencies for Diagnosis service: correlation ID, auth and RBAC."""
import uuid
from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.infrastructure.security import Principal
from app.infrastructure.tokens import (
    TokenError,
    TokenExpiredError,
    TokenInvalidError,
    get_token_verifier,
)
from app.persistence import get_db


bearer_scheme = HTTPBearer(auto_error=False)


def get_correlation_id(request: Request) -> uuid.UUID:
    """The middleware is the single authority for request correlation."""
    cid_str = getattr(request.state, "correlation_id", None)
    if not cid_str:
        return uuid.uuid4()
    return uuid.UUID(cid_str)


def get_current_principal(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Principal:
    """Authenticate caller using local Ed25519 JWT verification. No identity queries."""
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Bearer token requerido."},
        )

    verifier = get_token_verifier()
    try:
        payload = verifier.decode_access_token(auth.credentials)
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message": "El token de acceso ha expirado."},
        )
    except (TokenInvalidError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_INVALID", "message": "Token de acceso inválido."},
        )
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Autenticación no disponible."},
        )

    user_id = uuid.UUID(payload["sub"])
    role = payload["role"]
    token_id = str(payload.get("jti", ""))
    return Principal(id=user_id, role=role, token_id=token_id)


def require_admin(principal: Principal = Depends(get_current_principal)) -> Principal:
    """Ensure current authenticated principal has ADMIN role."""
    if principal.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Se requiere rol de administrador."},
        )
    return principal


def require_user(principal: Principal = Depends(get_current_principal)) -> Principal:
    """Ensure caller is authenticated."""
    return principal
