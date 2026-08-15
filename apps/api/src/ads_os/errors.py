"""Обработка ошибок.

Правило v0.3 §63: никаких тихих сбоев. Каждая ошибка получает код, признак
повторяемости и идентификатор запроса, по которому её можно найти в логах.
Наружу при этом не уходит ни трассировка, ни текст исключения (v0.3 §137).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .observability import request_id_var

logger = logging.getLogger(__name__)


class ErrorBody(BaseModel):
    """Единая форма ошибки для всех эндпоинтов."""

    error_code: str = Field(description="Машиночитаемый код ошибки")
    message: str = Field(description="Короткое объяснение для пользователя")
    request_id: str = Field(description="Идентификатор запроса для обращения в поддержку")
    retryable: bool = Field(description="Имеет ли смысл повторить запрос")
    details: dict[str, Any] | None = Field(
        default=None, description="Уточнения, безопасные для показа пользователю"
    )


class AppError(Exception):
    """Ошибка приложения с явным кодом.

    Наследники задают `status_code` и `error_code`, чтобы обработчик не гадал по
    тексту сообщения.
    """

    status_code: int = 500
    error_code: str = "internal_error"
    retryable: bool = False
    message: str = "Внутренняя ошибка"

    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    error_code = "not_found"
    message = "Объект не найден"


class ForbiddenError(AppError):
    status_code = 403
    error_code = "forbidden"
    message = "Недостаточно прав"


class ValidationError(AppError):
    status_code = 422
    error_code = "validation_failed"
    message = "Данные не прошли проверку"


class ConflictError(AppError):
    """Состояние сущности изменилось с момента чтения.

    Используется оптимистичной блокировкой: действие, подготовленное на устаревших
    данных, выполнять нельзя (v0.4 §100).
    """

    status_code = 409
    error_code = "version_conflict"
    message = "Объект изменился, повторите операцию на актуальных данных"
    retryable = True


def _response(status_code: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=body.model_dump())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "ошибка приложения",
            extra={"error_code": exc.error_code, "details": exc.details},
        )
        return _response(
            exc.status_code,
            ErrorBody(
                error_code=exc.error_code,
                message=exc.message,
                request_id=request_id_var.get(),
                retryable=exc.retryable,
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Наружу отдаём только путь до поля и тип нарушения: содержимое ввода
        # может оказаться персональными данными.
        fields = [
            {"field": ".".join(str(p) for p in err["loc"][1:]), "type": err["type"]}
            for err in exc.errors()
        ]
        return _response(
            422,
            ErrorBody(
                error_code="validation_failed",
                message="Данные не прошли проверку",
                request_id=request_id_var.get(),
                retryable=False,
                details={"fields": fields},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _response(
            exc.status_code,
            ErrorBody(
                error_code="http_error",
                message=str(exc.detail),
                request_id=request_id_var.get(),
                retryable=exc.status_code >= 500,
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Трассировка остаётся в логах, наружу уходит только код обращения.
        logger.exception("необработанное исключение", exc_info=exc)
        return _response(
            500,
            ErrorBody(
                error_code="internal_error",
                message="Внутренняя ошибка. Передайте код обращения в поддержку.",
                request_id=request_id_var.get(),
                retryable=True,
            ),
        )
