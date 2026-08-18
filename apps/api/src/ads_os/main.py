"""Точка входа приложения."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .api.v1 import (
    activity,
    ad_platform,
    audit,
    auth,
    competitors,
    health,
    minus_sets,
    niches,
    notifications,
    organization,
    overview,
    projects,
    semantics,
    sessions,
)
from .config import get_settings
from .db.session import dispose_engine
from .errors import register_error_handlers
from .observability import configure_logging, new_request_id, request_id_var

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "запуск приложения",
        extra={
            "app_env": settings.app_env,
            "ai_provider": settings.ai_provider,
            "ad_platform_adapter": settings.ad_platform_adapter,
        },
    )
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="AI Helper Pro API",
        version="0.1.0",
        description=(
            "Backend AI Helper Pro. Схемы этого API — источник правды для контракта: "
            "типы фронтенда генерируются из OpenAPI (v0.4 §18)."
        ),
        lifespan=lifespan,
        openapi_url="/openapi.json",
        docs_url="/docs" if not settings.is_production else None,
    )

    # Список источников задаётся явно: маска «*» здесь запрещена (v0.3 §102).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.app_base_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Сквозной идентификатор запроса.

        Клиентский заголовок не принимается: иначе идентификаторы в логах можно
        было бы подделать и запутать расследование.
        """
        request_id = new_request_id()
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "запрос обработан",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)

        response.headers["X-Request-Id"] = request_id
        return response

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Заголовки безопасности (v0.3 §102)."""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return response

    register_error_handlers(app)

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(projects.router, prefix="/api/v1")
    app.include_router(audit.router, prefix="/api/v1")
    app.include_router(competitors.router, prefix="/api/v1")
    app.include_router(semantics.router, prefix="/api/v1")
    app.include_router(semantics.search_router, prefix="/api/v1")
    app.include_router(minus_sets.router, prefix="/api/v1")
    app.include_router(niches.router, prefix="/api/v1")
    app.include_router(ad_platform.router, prefix="/api/v1")
    app.include_router(overview.router, prefix="/api/v1")
    app.include_router(activity.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    app.include_router(organization.router, prefix="/api/v1")

    return app


app = create_app()
