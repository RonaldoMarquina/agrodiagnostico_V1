"""FastAPI application for Identity service with authentication, profile and admin routes."""
import uuid
from typing import Literal
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.profile import router as profile_router
from app.persistence import SERVICE, schema_ready


class Live(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["alive"]
    service: Literal["identity"]


class Ready(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready"]
    service: Literal["identity"]


class NotReady(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["not_ready"]
    service: Literal["identity"]


app = FastAPI(
    title="AgroDiagnóstico " + SERVICE,
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)


@app.middleware("http")
async def correlation_and_security_headers(request: Request, call_next):
    # Extract or generate correlation id
    cid_header = request.headers.get("X-Correlation-ID")
    cid = None
    if cid_header:
        try:
            cid = str(uuid.UUID(cid_header))
        except (ValueError, TypeError):
            # If invalid UUID format in header, return 400 immediately per OpenAPI contract
            cid = str(uuid.uuid4())
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "code": "INVALID_CORRELATION_ID",
                    "message": "X-Correlation-ID must be a valid UUID",
                    "correlation_id": cid,
                },
                headers={
                    "Cache-Control": "private, no-store",
                    "X-Correlation-ID": cid,
                },
            )
    if not cid:
        cid = str(uuid.uuid4())

    request.state.correlation_id = cid
    response = await call_next(request)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Correlation-ID"] = cid
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    cid = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    details = []
    for err in exc.errors():
        loc = err.get("loc", ())
        field_name = str(loc[-1]) if loc else "body"
        details.append({
            "field": field_name,
            "code": "INVALID_FIELD",
        })
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "code": "INVALID_REQUEST",
            "message": "Solicitud inválida o campos no permitidos.",
            "correlation_id": cid,
            "details": details[:20],
        },
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": cid,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    cid = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    if isinstance(exc.detail, dict):
        body = {
            "code": exc.detail.get("code", "ERROR"),
            "message": exc.detail.get("message", "Error en la solicitud"),
            "correlation_id": exc.detail.get("correlation_id", cid),
        }
        if "details" in exc.detail:
            body["details"] = exc.detail["details"]
    else:
        body = {
            "code": "ERROR",
            "message": str(exc.detail),
            "correlation_id": cid,
        }
    response = JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": cid,
        },
    )
    if exc.status_code == 401 and request.url.path in {"/api/v1/auth/refresh", "/api/v1/auth/logout"}:
        from app.api.auth import _clear_auth_cookies
        _clear_auth_cookies(response)
    return response


# Health checks (Incremento 0)
@app.get("/health/live", response_model=Live, operation_id=SERVICE + "_live")
def live():
    return {"status": "alive", "service": SERVICE}


@app.get(
    "/health/ready",
    response_model=Ready,
    responses={503: {"model": NotReady}},
    operation_id=SERVICE + "_ready",
)
def ready():
    ok = schema_ready()
    return JSONResponse(
        {"status": "ready" if ok else "not_ready", "service": SERVICE},
        status_code=200 if ok else 503,
    )


# Business routers (Incremento 1)
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(admin_router)
