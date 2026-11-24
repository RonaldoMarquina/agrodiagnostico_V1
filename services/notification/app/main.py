"""FastAPI application for Notification service with health checks, correlation, error envelopes, and public routes."""
import logging
from typing import Literal
import uuid

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import psycopg
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.api.notifications import router as notifications_router
from app.persistence import SERVICE, schema_ready

logger = logging.getLogger(__name__)


class Live(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["alive"]
    service: Literal["notification"]


class Ready(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready"]
    service: Literal["notification"]


class NotReady(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["not_ready"]
    service: Literal["notification"]


app = FastAPI(
    title="AgroDiagnóstico " + SERVICE,
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)


@app.middleware("http")
async def correlation_and_security_headers(request: Request, call_next):
    if "x-correlation-id" in request.headers:
        cid_header = request.headers["x-correlation-id"]
        try:
            cid = str(uuid.UUID(cid_header))
        except (ValueError, TypeError):
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
    else:
        cid = str(uuid.uuid4())

    request.state.correlation_id = cid

    try:
        response = await call_next(request)
    except (OperationalError, psycopg.OperationalError) as exc:
        logger.error("Persistence unavailable for correlation_id=%s: %s", cid, exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "PERSISTENCE_UNAVAILABLE",
                "message": "Persistencia temporalmente no disponible.",
                "correlation_id": cid,
            },
            headers={
                "Cache-Control": "private, no-store",
                "X-Correlation-ID": cid,
            },
        )
    except Exception as exc:
        logger.error("Unhandled exception for correlation_id=%s: %s", cid, exc, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "INTERNAL_ERROR",
                "message": "Error interno del servidor.",
                "correlation_id": cid,
            },
            headers={
                "Cache-Control": "private, no-store",
                "X-Correlation-ID": cid,
            },
        )

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
        details.append({"field": field_name, "code": "INVALID_FIELD"})
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
        code_map = {
            400: "INVALID_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            500: "INTERNAL_ERROR",
            503: "SERVICE_UNAVAILABLE",
        }
        body = {
            "code": code_map.get(exc.status_code, "ERROR"),
            "message": str(exc.detail),
            "correlation_id": cid,
        }
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": cid,
        },
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    cid = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    logger.error("Database unavailable for correlation_id=%s: %s", cid, exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "code": "PERSISTENCE_UNAVAILABLE",
            "message": "Persistencia temporalmente no disponible.",
            "correlation_id": cid,
        },
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": cid,
        },
    )


@app.exception_handler(psycopg.Error)
async def psycopg_exception_handler(request: Request, exc: psycopg.Error):
    cid = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    logger.error("Psycopg database unavailable for correlation_id=%s: %s", cid, exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "code": "PERSISTENCE_UNAVAILABLE",
            "message": "Persistencia temporalmente no disponible.",
            "correlation_id": cid,
        },
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": cid,
        },
    )


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


app.include_router(notifications_router)
