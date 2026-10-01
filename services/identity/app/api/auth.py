"""Authentication API endpoints: register, login, refresh, logout, password-recovery."""
from app.infrastructure.audit import audit_entry
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_correlation_id, validate_csrf, validate_origin
from app.api.schemas import (
    LoginRequest,
    MessageResponse,
    ProfileResponse,
    RecoveryConfirmRequest,
    RecoveryRequest,
    RegisterRequest,
    SessionResponse,
)
from app.domain.models import PasswordRecoveryToken, RefreshSession, User
from app.infrastructure.email import get_email_sender
from app.infrastructure.security import (
    generate_secure_token,
    csrf_for_refresh,
    hash_password,
    hash_token,
    verify_password,
)
from app.infrastructure.tokens import get_token_manager
from app.persistence import get_db

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "__Secure-agro_refresh"
CSRF_COOKIE_NAME = "csrf_token"
REFRESH_TOKEN_EXPIRE_DAYS = 7


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _set_auth_cookies(response: Response, raw_refresh_token: str, csrf_token: str) -> None:
    # Set-Cookie: __Secure-agro_refresh
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/api/v1/auth",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )
    # Set-Cookie: csrf_token
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=True,
        samesite="lax",
        path="/api/v1/auth",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value="",
        httponly=True,
        secure=True,
        samesite="lax",
        path="/api/v1/auth",
        max_age=0,
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value="",
        httponly=False,
        secure=True,
        samesite="lax",
        path="/api/v1/auth",
        max_age=0,
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=ProfileResponse,
    operation_id="identity_register",
)
def register(
    payload: RegisterRequest,
    correlation_id: UUID = Depends(get_correlation_id),
    db: Session = Depends(get_db),
):
    email_clean = payload.email.strip().lower()
    existing = db.query(User).filter(User.email == email_clean).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ACCOUNT_UNAVAILABLE",
                "message": "No se pudo registrar la cuenta con el correo proporcionado.",
                "correlation_id": str(correlation_id),
            },
        )

    try:
        pw_hash = hash_password(payload.password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": str(e),
                "correlation_id": str(correlation_id),
            },
        )

    user = User(
        email=email_clean,
        password_hash=pw_hash,
        display_name=payload.display_name.strip(),
        role="USER",
        status="ACTIVE",
    )
    db.add(user)
    db.flush()
    db.add(audit_entry(user_id=user.id, event_type="USER_REGISTERED", correlation_id=correlation_id))
    db.commit()
    db.refresh(user)

    return ProfileResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        created_at=user.created_at.isoformat(),
    )


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    response_model=SessionResponse,
    operation_id="identity_login",
)
def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    correlation_id: UUID = Depends(get_correlation_id),
    origin: str = Depends(validate_origin),
    db: Session = Depends(get_db),
):
    email_clean = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email_clean).first()

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:500]

    if not user or not verify_password(payload.password, user.password_hash) or user.status != "ACTIVE":
        # Audit failed login attempt
        failed_log = audit_entry(correlation_id=correlation_id,
            user_id=user.id if user else None,
            event_type="LOGIN_FAILED",
            ip_address=client_ip,
            user_agent=user_agent,
            details={"email": email_clean},
        )
        db.add(failed_log)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "Credenciales inválidas.",
                "correlation_id": str(correlation_id),
            },
        )

    # Generate Ed25519 access token
    token_mgr = get_token_manager()
    access_token = token_mgr.create_access_token(user_id=user.id, role=user.role)

    # Generate refresh session and CSRF token
    raw_refresh = generate_secure_token(32)
    refresh_hash = hash_token(raw_refresh)
    csrf_token = csrf_for_refresh(raw_refresh)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    session = RefreshSession(
        user_id=user.id,
        family_id=None,  # Assigned below before insertion
        token_hash=refresh_hash,
        expires_at=expires_at,
        created_ip=client_ip,
        user_agent=user_agent,
    )
    import uuid as _uuid
    session.family_id = _uuid.uuid4()
    db.add(session)

    # Audit successful login
    db.add(audit_entry(correlation_id=correlation_id,
        user_id=user.id,
        event_type="LOGIN_SUCCESS",
        ip_address=client_ip,
        user_agent=user_agent,
    ))
    db.commit()

    _set_auth_cookies(response, raw_refresh, csrf_token)

    return SessionResponse(
        access_token=access_token,
        token_type="Bearer",
        expires_in=900,
        csrf_token=csrf_token,
    )


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    response_model=SessionResponse,
    operation_id="identity_refresh",
)
def refresh(
    request: Request,
    response: Response,
    correlation_id: UUID = Depends(get_correlation_id),
    origin: str = Depends(validate_origin),
    csrf: str = Depends(validate_csrf),
    refresh_cookie: Optional[str] = Cookie(None, alias=REFRESH_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    if not refresh_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Cookie de sesión ausente o expirada.",
                "correlation_id": str(correlation_id),
            },
        )

    token_h = hash_token(refresh_cookie)
    now = datetime.now(timezone.utc)
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:500]

    # Atomic pessimistic lock using SELECT ... FOR UPDATE
    session = (
        db.query(RefreshSession)
        .filter(RefreshSession.token_hash == token_h)
        .with_for_update()
        .first()
    )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Sesión inválida.",
                "correlation_id": str(correlation_id),
            },
        )

    # 1. Reuse detection: if already rotated, revoke the ENTIRE token family!
    if session.rotated_at is not None:
        db.query(RefreshSession).filter(
            RefreshSession.family_id == session.family_id
        ).update({RefreshSession.revoked_at: now}, synchronize_session=False)

        db.add(audit_entry(correlation_id=correlation_id,
            user_id=session.user_id,
            event_type="REFRESH_TOKEN_REUSE_DETECTED",
            ip_address=client_ip,
            user_agent=user_agent,
            details={"family_id": str(session.family_id), "session_id": str(session.id)},
        ))
        db.commit()

        _clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "SESSION_REUSE_DETECTED",
                "message": "Reutilización de token detectada. Todas las sesiones de la familia han sido revocadas.",
                "correlation_id": str(correlation_id),
            },
        )

    # 2. Check if already revoked or expired
    if session.revoked_at is not None or ensure_utc(session.expires_at) <= now:
        _clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "SESSION_EXPIRED",
                "message": "Sesión expirada o revocada.",
                "correlation_id": str(correlation_id),
            },
        )

    # 3. Check user status
    user = db.query(User).filter(User.id == session.user_id).first()
    if not user or user.status != "ACTIVE":
        _clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "ACCOUNT_INACTIVE",
                "message": "Cuenta no disponible.",
                "correlation_id": str(correlation_id),
            },
        )

    # 4. Atomic rotation: create new session and mark old as rotated
    new_raw_token = generate_secure_token(32)
    new_hash = hash_token(new_raw_token)
    new_csrf = csrf_for_refresh(new_raw_token)
    new_expires_at = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    new_session = RefreshSession(
        user_id=user.id,
        family_id=session.family_id,
        token_hash=new_hash,
        expires_at=new_expires_at,
        created_ip=client_ip,
        user_agent=user_agent,
    )
    db.add(new_session)
    db.flush()  # populate new_session.id

    session.rotated_at = now
    session.replaced_by_session_id = new_session.id
    db.commit()

    token_mgr = get_token_manager()
    access_token = token_mgr.create_access_token(user_id=user.id, role=user.role)

    _set_auth_cookies(response, new_raw_token, new_csrf)

    return SessionResponse(
        access_token=access_token,
        token_type="Bearer",
        expires_in=900,
        csrf_token=new_csrf,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="identity_logout",
)
def logout(
    request: Request,
    response: Response,
    correlation_id: UUID = Depends(get_correlation_id),
    origin: str = Depends(validate_origin),
    csrf: str = Depends(validate_csrf),
    refresh_cookie: Optional[str] = Cookie(None, alias=REFRESH_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    if not refresh_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Cookie de sesión requerida.",
                "correlation_id": str(correlation_id),
            },
        )

    token_h = hash_token(refresh_cookie)
    now = datetime.now(timezone.utc)
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:500]

    session = (
        db.query(RefreshSession)
        .filter(RefreshSession.token_hash == token_h)
        .with_for_update()
        .first()
    )

    if not session or session.revoked_at is not None or ensure_utc(session.expires_at) <= now:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Sesión inválida."})

    if session.revoked_at is None:
        db.query(RefreshSession).filter(RefreshSession.family_id == session.family_id).update(
            {RefreshSession.revoked_at: now}, synchronize_session=False)
        db.add(audit_entry(correlation_id=correlation_id,
            user_id=session.user_id,
            event_type="LOGOUT",
            ip_address=client_ip,
            user_agent=user_agent,
        ))
        db.commit()

    _clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/password-recovery",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=MessageResponse,
    operation_id="identity_start_recovery",
)
def password_recovery(
    payload: RecoveryRequest,
    correlation_id: UUID = Depends(get_correlation_id),
    db: Session = Depends(get_db),
):
    email_clean = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email_clean).first()

    # Generic 202 response to prevent account enumeration
    generic_message = (
        "Si la cuenta existe, recibirá instrucciones de recuperación."
    )

    if user and user.status == "ACTIVE":
        raw_token = generate_secure_token(32)
        token_h = hash_token(raw_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=30)

        recovery_entry = PasswordRecoveryToken(
            user_id=user.id,
            token_hash=token_h,
            expires_at=expires_at,
        )
        db.add(recovery_entry)
        db.add(audit_entry(correlation_id=correlation_id,
            user_id=user.id,
            event_type="PASSWORD_RECOVERY_REQUESTED",
        ))
        db.commit()

        email_sender = get_email_sender()
        email_sender.send_password_recovery(user.email, raw_token)

    return MessageResponse(message=generic_message)


@router.post(
    "/password-recovery/confirm",
    status_code=status.HTTP_200_OK,
    response_model=MessageResponse,
    operation_id="identity_confirm_recovery",
)
def confirm_password_recovery(
    payload: RecoveryConfirmRequest,
    correlation_id: UUID = Depends(get_correlation_id),
    db: Session = Depends(get_db),
):
    try:
        new_pw_hash = hash_password(payload.new_password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": str(e),
                "correlation_id": str(correlation_id),
            },
        )

    token_h = hash_token(payload.token)
    now = datetime.now(timezone.utc)

    rec_token = (
        db.query(PasswordRecoveryToken)
        .filter(PasswordRecoveryToken.token_hash == token_h)
        .with_for_update()
        .first()
    )

    if not rec_token or rec_token.used_at is not None or ensure_utc(rec_token.expires_at) <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_TOKEN",
                "message": "Token de recuperación inválido, expirado o ya consumido.",
                "correlation_id": str(correlation_id),
            },
        )

    user = db.query(User).filter(User.id == rec_token.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_TOKEN",
                "message": "Usuario no encontrado.",
                "correlation_id": str(correlation_id),
            },
        )

    # 1. Consume token
    rec_token.used_at = now

    # 2. Update password
    user.password_hash = new_pw_hash
    user.updated_at = now

    # 3. Mandatory revocation of all active refresh sessions
    db.query(RefreshSession).filter(
        RefreshSession.user_id == user.id,
        RefreshSession.revoked_at.is_(None),
    ).update({RefreshSession.revoked_at: now}, synchronize_session=False)

    # 4. Insert audit log
    db.add(audit_entry(correlation_id=correlation_id,
        user_id=user.id,
        event_type="PASSWORD_RECOVERY_CONFIRMED",
    ))
    db.commit()

    return MessageResponse(message="Contraseña restablecida exitosamente.")
