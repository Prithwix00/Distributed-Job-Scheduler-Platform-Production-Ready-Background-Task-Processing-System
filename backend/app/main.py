"""FastAPI application factory and entrypoint."""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder

from .config import settings
from .core import AppError, configure_logging, get_logger
from .database import Base, engine
from . import models  # noqa: F401  ensures all tables register on Base.metadata
from .routers import auth, projects, jobs, workers, dashboard

configure_logging()
log = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # For a real deployment, migrations are managed by Alembic. create_all keeps
    # local dev and the test suite frictionless.
    Base.metadata.create_all(bind=engine)
    log.info("api.startup", extra={"extra_fields": {"env": settings.environment}})
    yield
    log.info("api.shutdown")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    description="A production-inspired distributed job scheduling platform.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Attach a request id and log a structured access line with latency."""
    rid = request.headers.get("x-request-id", str(uuid.uuid4()))
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    response.headers["x-request-id"] = rid
    log.info(
        "http.request",
        extra={"extra_fields": {
            "request_id": rid, "method": request.method,
            "path": request.url.path, "status": response.status_code,
            "latency_ms": round(elapsed, 2),
        }},
    )
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.__class__.__name__, "detail": exc.detail, "code": exc.code},
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "ValidationError", "detail": jsonable_encoder(exc.errors()),
                 "code": "validation_error"},
    )


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": settings.app_name}


API = "/api/v1"
app.include_router(auth.router, prefix=API)
app.include_router(projects.router, prefix=API)
app.include_router(jobs.router, prefix=API)
app.include_router(workers.router, prefix=API)
app.include_router(dashboard.router, prefix=API)
