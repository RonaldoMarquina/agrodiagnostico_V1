"""FastAPI dependencies for Notification service: correlation ID and JWT auth."""
from typing import Optional
import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt as pyjwt

from app.infrastructure.security import Principal
from app.infrastructure.tokens import (
    TokenError,
    TokenExpiredError,
    TokenInvalidError,
    get_token_verifier,
)

bearer_scheme = HTTPBearer(auto_error=False)


def get_correlation_id(request: Request) -> uuid.UUID:
    cid_str = getattr(request.state, "correlation_id", None)
    if not cid_str:
        return uuid.uuid4()
    return uuid.UUID(cid_str)


def get_current_principal(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Principal:
    """Authenticate caller using local Ed25519 public-key verification."""
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Bearer token requerido."},
        )

    # Reject internal service tokens on public user routes with 403 FORBIDDEN
    try:
        unverified = pyjwt.decode(auth.credentials, options={"verify_signature": False})
        if unverified.get("iss") == "agrodiagnostico-internal" or unverified.get("aud") in {
            "diagnosis-internal",
            "identity-internal",
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "Operación no autorizada."},
            )
    except HTTPException:
        raise
    except Exception:
        pass

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

    return Principal(
        id=uuid.UUID(payload["sub"]),
        role=payload["role"],
        token_id=str(payload.get("jti", "")),
    )


def require_user(principal: Principal = Depends(get_current_principal)) -> Principal:
    return principal
