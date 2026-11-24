"""FastAPI dependencies for authenticating user requests via Ed25519 JWT."""
import uuid

from fastapi import HTTPException, Request, status

from app.config import get_settings
from app.infrastructure.tokens import Principal, TokenError, get_token_verifier


def get_current_principal(request: Request) -> Principal:
    """Authenticate caller from Authorization Bearer JWT strictly before invoking any provider."""
    cid = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    settings = get_settings()
    verifier = get_token_verifier(settings)
    auth_header = request.headers.get("authorization")
    try:
        return verifier.verify_principal(auth_header)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Autenticación requerida o inválida.",
                "correlation_id": cid,
            },
        ) from None
