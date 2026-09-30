"""Technical health only. No business routes or simulated diagnoses."""
from typing import Literal
from uuid import uuid4
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
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


app = FastAPI(title="AgroDiagnóstico " + SERVICE, version="1.0.0", docs_url=None, redoc_url=None)


@app.middleware("http")
async def private_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Correlation-ID"] = str(uuid4())
    return response


@app.get("/health/live", response_model=Live, operation_id=SERVICE + "_live")
def live():
    return {"status": "alive", "service": SERVICE}


@app.get("/health/ready", response_model=Ready, responses={503: {"model": NotReady}}, operation_id=SERVICE + "_ready")
def ready():
    ok = schema_ready()
    return JSONResponse({"status": "ready" if ok else "not_ready", "service": SERVICE}, status_code=200 if ok else 503)
