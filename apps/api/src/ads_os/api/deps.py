"""Зависимости запроса.

Полноценная аутентификация с MFA (v0.3 §91) делается отдельным срезом. До этого
контекст организации берётся из заголовков — и только вне production, чтобы
такой режим невозможно было случайно включить на боевом стенде.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db.session import get_sessionmaker
from ..errors import ForbiddenError
from ..tenancy.context import Role, TenantContext


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_tenant_context(
    settings: SettingsDep,
    x_organization_id: Annotated[uuid.UUID | None, Header()] = None,
    x_user_id: Annotated[uuid.UUID | None, Header()] = None,
    x_user_role: Annotated[str | None, Header()] = None,
) -> TenantContext:
    """Временный способ установить контекст арендатора.

    Заголовкам нельзя доверять как источнику авторизации (v0.3 §93) — поэтому
    режим работает только вне production и будет заменён на сессию с проверкой
    прав. Ошибка здесь означала бы, что кто угодно может назначить себе любую
    организацию, поэтому проверка окружения жёсткая и без исключений.
    """
    if settings.is_production:
        raise ForbiddenError(
            "Аутентификация ещё не подключена, работа в production запрещена"
        )

    if x_organization_id is None or x_user_id is None:
        raise ForbiddenError("Не указан контекст организации")

    try:
        role = Role(x_user_role or Role.SPECIALIST)
    except ValueError as exc:
        raise ForbiddenError("Неизвестная роль") from exc

    return TenantContext(organization_id=x_organization_id, user_id=x_user_id, role=role)


TenantDep = Annotated[TenantContext, Depends(get_tenant_context)]


def require_write(ctx: TenantDep) -> TenantContext:
    """Роль VIEWER не изменяет ничего (v0.3 §4)."""
    if not ctx.can_write:
        raise ForbiddenError("Роль не позволяет изменять данные")
    return ctx


WriteDep = Annotated[TenantContext, Depends(require_write)]
