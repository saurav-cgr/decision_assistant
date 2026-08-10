from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from decision_assistant.answering.router import router as answering_router
from decision_assistant.config import Settings, get_settings
from decision_assistant.decisions.router import router as decisions_router
from decision_assistant.documents.router import router as documents_router
from decision_assistant.errors import ApplicationError, ErrorResponse
from decision_assistant.retrieval.router import router as retrieval_router

RequestHandler = Callable[[Request], Awaitable[Response]]


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid4()))


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    details: Any | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        code=code,
        message=message,
        request_id=_request_id(request),
        retryable=retryable,
        details=details,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(title="Decision Assistant API")
    app.state.settings = resolved_settings
    app.include_router(answering_router)
    app.include_router(decisions_router)
    app.include_router(documents_router)
    app.include_router(retrieval_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: RequestHandler,
    ) -> Response:
        request.state.request_id = request.headers.get("x-request-id") or str(uuid4())
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.exception_handler(ApplicationError)
    async def handle_application_error(
        request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed",
            details=exc.errors(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        message = "Not found" if exc.status_code == 404 else str(exc.detail)
        return _error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=message,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        _: Exception,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=500,
            code="internal_error",
            message="Internal server error",
            retryable=True,
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
