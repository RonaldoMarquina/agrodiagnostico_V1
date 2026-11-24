"""FastAPI application for the assistant extension (ADR-0015)."""
import logging
from typing import Literal
import uuid

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.api.assistant import router as assistant_router
from app.config import SERVICE, get_settings
from app.infrastructure.telemetry import log_assistant_event


class Live(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["alive"]
    service: Literal["assistant"]


class Ready(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready"]
    service: Literal["assistant"]


class NotReady(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["not_ready"]
    service: Literal["assistant"]


app = FastAPI(
    title="AgroDiagnóstico " + SERVICE,
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)


@app.middleware("http")
async def correlation_size_and_security_headers(request: Request, call_next):
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
                    "message": "X-Correlation-ID debe ser un UUID válido.",
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
    settings = get_settings()

    if request.method in {"POST", "PUT", "PATCH"}:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_len = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "code": "INVALID_REQUEST",
                        "message": "Solicitud inválida.",
                        "correlation_id": cid,
                    },
                    headers={
                        "Cache-Control": "private, no-store",
                        "X-Correlation-ID": cid,
                    },
                )
            if declared_len > settings.max_transport_bytes:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": "La solicitud excede el tamaño máximo permitido.",
                        "correlation_id": cid,
                    },
                    headers={
                        "Cache-Control": "private, no-store",
                        "X-Correlation-ID": cid,
                    },
                )

        body = await request.body()
        if len(body) > settings.max_transport_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                content={
                    "code": "PAYLOAD_TOO_LARGE",
                    "message": "La solicitud excede el tamaño máximo permitido.",
                    "correlation_id": cid,
                },
                headers={
                    "Cache-Control": "private, no-store",
                    "X-Correlation-ID": cid,
                },
            )

    try:
        response = await call_next(request)
    except Exception as exc:
        log_assistant_event(
            level=logging.ERROR,
            event="assistant_unhandled_error",
            correlation_id=cid,
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_class=type(exc).__name__,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "INTERNAL_ERROR",
                "message": "Ocurrió un error interno. Puedes continuar usando la navegación manual.",
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
        details.append({"field": field_name[:80], "code": "INVALID_FIELD"})
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
            "message": exc.detail.get("message", "Error en la solicitud."),
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
            413: "PAYLOAD_TOO_LARGE",
            429: "RATE_LIMITED",
            500: "INTERNAL_ERROR",
            503: "ASSISTANT_UNAVAILABLE",
            504: "ASSISTANT_TIMEOUT",
        }
        body = {
            "code": code_map.get(exc.status_code, "ERROR"),
            "message": str(exc.detail),
            "correlation_id": cid,
        }
    headers = {
        "Cache-Control": "private, no-store",
        "X-Correlation-ID": cid,
    }
    if exc.headers:
        for k, v in exc.headers.items():
            headers[k] = v
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=headers,
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
    settings = get_settings()
    ok, _reason = settings.readiness_check()
    return JSONResponse(
        {"status": "ready" if ok else "not_ready", "service": SERVICE},
        status_code=200 if ok else 503,
    )


app.include_router(assistant_router)
