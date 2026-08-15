"""Контекст арендатора.

Каждый запрос выполняется от имени конкретного пользователя конкретной
организации. Контекст живёт в ContextVar, а не передаётся аргументом, потому что
его обязаны видеть и репозитории, и фоновые задания: перенос tenant context в
фоновые задачи — прямое требование v0.3 §93.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    """Роли из v0.3 §4."""

    OWNER = "owner"
    SPECIALIST = "specialist"
    VIEWER = "viewer"


@dataclass(frozen=True, slots=True)
class TenantContext:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: Role
    #: Имя для журнала действий. Хранится здесь, чтобы не запрашивать
    #: пользователя заново при каждой записи. Пустое значение бывает только в
    #: локальной разработке, где контекст приходит заголовками.
    user_name: str = ""

    @property
    def is_owner(self) -> bool:
        return self.role is Role.OWNER

    @property
    def can_write(self) -> bool:
        """Просмотр — не изменение. Роль VIEWER не меняет ничего (v0.3 §4)."""
        return self.role in (Role.OWNER, Role.SPECIALIST)


_current: ContextVar[TenantContext | None] = ContextVar("tenant_context", default=None)


class MissingTenantContextError(RuntimeError):
    """Попытка обратиться к данным арендатора вне контекста.

    Это не пользовательская ошибка, а дефект: значит, где-то запрос к данным
    выполняется без установленной организации, и фильтр изоляции не применится.
    """


def current_context() -> TenantContext:
    ctx = _current.get()
    if ctx is None:
        raise MissingTenantContextError(
            "Запрос к данным арендатора вне контекста организации. "
            "Установите контекст через use_context()."
        )
    return ctx


def try_current_context() -> TenantContext | None:
    return _current.get()


@contextmanager
def use_context(ctx: TenantContext) -> Iterator[TenantContext]:
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)
