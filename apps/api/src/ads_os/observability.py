"""Структурированные логи и корреляция запросов.

Логи должны помогать расследованию, но не становиться вторым хранилищем
персональных данных (v0.3 §106). Поэтому здесь же живёт маскирование: значения
заголовков авторизации, токенов и паролей никогда не попадают в вывод.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar
from typing import Any

from pythonjsonlogger.json import JsonFormatter

#: Идентификатор запроса, доступный любому месту обработки без проброса аргументом.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_SECRET_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
    "api_key",
    "secret",
}

_PHONE_RE = re.compile(r"(\+?\d[\d\-\s()]{8,}\d)")
_EMAIL_RE = re.compile(r"([\w.+-]+)@([\w-]+\.[\w.-]+)")


def mask_value(key: str, value: Any) -> Any:
    """Скрывает значение, если ключ выглядит секретом."""
    if key.lower() in _SECRET_KEYS:
        return "***"
    return value


def mask_pii(text: str) -> str:
    """Маскирует телефоны и адреса почты в свободном тексте.

    Полный вид почти никогда не нужен для расследования, а хранение его в логах
    превращает журнал во второе хранилище персональных данных (v0.3 §106).
    """
    text = _PHONE_RE.sub(lambda m: m.group(1)[:3] + "***" + m.group(1)[-2:], text)
    text = _EMAIL_RE.sub(lambda m: m.group(1)[:2] + "***@" + m.group(2), text)
    return text


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def configure_logging(level: str = "info") -> None:
    """Настраивает JSON-логи для всего процесса."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s",
            rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
        )
    )
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn пишет собственные логи доступа — они дублируют наш middleware.
    logging.getLogger("uvicorn.access").disabled = True
