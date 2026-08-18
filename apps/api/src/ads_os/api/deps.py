"""Зависимости запроса.

Контекст организации берётся из сессии — то есть из того, что система выдала
сама и может в любой момент отозвать.

Заголовки как источник контекста остались только для локальной разработки и
тестов. На любом развёрнутом стенде они не работают: заголовок присылает
клиент, и доверять ему как основанию для авторизации нельзя (v0.3 §93). Раньше
такой режим допускался и на staging — с появлением настоящего входа это больше
не нужно.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db.session import get_sessionmaker
from ..errors import AppError, ForbiddenError
from ..models import User
from ..services.auth import (
    COOKIE_NAME,
    AuthenticatedUser,
    allowed_projects,
    resolve_session,
    touch,
)
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


class NotAuthenticatedError(AppError):
    """Сессии нет, она истекла или была отозвана.

    Отдельный код нужен интерфейсу: по нему он отправляет человека на страницу
    входа, а не показывает общую ошибку.
    """

    status_code = 401
    error_code = "not_authenticated"
    message = "Требуется вход"


async def get_current_user(
    request: Request, db: SessionDep, settings: SettingsDep
) -> AuthenticatedUser:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise NotAuthenticatedError()

    auth = await resolve_session(db, token)
    if auth is None:
        raise NotAuthenticatedError()

    if touch(auth.session):
        await db.flush()

    return auth


AuthDep = Annotated[AuthenticatedUser, Depends(get_current_user)]


async def get_tenant_context(
    request: Request,
    db: SessionDep,
    settings: SettingsDep,
    x_organization_id: Annotated[uuid.UUID | None, Header()] = None,
    x_user_id: Annotated[uuid.UUID | None, Header()] = None,
    x_user_role: Annotated[str | None, Header()] = None,
) -> TenantContext:
    """Контекст арендатора: сначала сессия, затем — только в разработке — заголовки."""
    token = request.cookies.get(COOKIE_NAME)
    if token:
        auth = await resolve_session(db, token)
        if auth is not None:
            if touch(auth.session):
                await db.flush()
            return auth.context
        raise NotAuthenticatedError()

    if settings.app_env != "development":
        # Единственная развилка, где ошибка стоила бы утечки между клиентами:
        # проверка жёсткая и без исключений.
        raise NotAuthenticatedError()

    if x_organization_id is None or x_user_id is None:
        raise NotAuthenticatedError()

    try:
        role = Role(x_user_role or Role.SPECIALIST)
    except ValueError as exc:
        raise ForbiddenError("Неизвестная роль") from exc

    # Список открытых проектов читается и здесь. Без него путь через заголовки
    # вёл бы себя иначе, чем настоящий вход: ограничение доступа работало бы в
    # бою и молчало при разработке — то есть проверить его было бы негде, а
    # заметить поломку можно было бы только на живых данных клиента.
    user = (
        await db.execute(select(User).where(User.id == x_user_id))
    ).scalar_one_or_none()

    return TenantContext(
        organization_id=x_organization_id,
        user_id=x_user_id,
        role=role,
        allowed_projects=await allowed_projects(db, user) if user is not None else None,
    )


TenantDep = Annotated[TenantContext, Depends(get_tenant_context)]


def require_write(ctx: TenantDep) -> TenantContext:
    """Роль VIEWER не изменяет ничего (v0.3 §4)."""
    if not ctx.can_write:
        raise ForbiddenError("Роль не позволяет изменять данные")
    return ctx


WriteDep = Annotated[TenantContext, Depends(require_write)]


def require_owner(ctx: TenantDep) -> TenantContext:
    """Управление участниками доступно только владельцу.

    Специалист ведёт проекты, но не раздаёт доступы: иначе роль владельца
    перестаёт что-либо значить.
    """
    if not ctx.is_owner:
        raise ForbiddenError("Действие доступно только владельцу организации")
    return ctx


OwnerDep = Annotated[TenantContext, Depends(require_owner)]
