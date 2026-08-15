"""Активные входы пользователя.

Человек должен видеть, откуда он вошёл, и уметь завершить чужой вход, не
дожидаясь никого. Это единственный способ заметить, что доступом воспользовался
кто-то ещё, — и единственный способ это прекратить.

Список свой у каждого: чужие сессии здесь не показываются даже владельцу.
Отключить участника целиком он может на экране участников, а разглядывать, с
какого устройства работает коллега, ему незачем.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from ...db.base import utcnow
from ...errors import NotFoundError
from ...models import Session
from ...services.auth import revoke_session
from ..deps import AuthDep, SessionDep
from ..schemas import SessionList, SessionRead

router = APIRouter(prefix="/auth/sessions", tags=["auth"])


def describe_device(user_agent: str | None) -> str:
    """Короткое человеческое описание устройства.

    Разбор нарочно грубый: цель — чтобы человек узнал свой вход в списке, а не
    чтобы точно определить сборку браузера. Точный отпечаток здесь был бы
    лишними данными о людях без всякой пользы.
    """
    if not user_agent:
        return "Неизвестное устройство"

    agent = user_agent.lower()

    browser = next(
        (
            name
            for marker, name in (
                ("edg/", "Edge"),
                ("yabrowser", "Яндекс Браузер"),
                ("firefox", "Firefox"),
                ("chrome", "Chrome"),
                ("safari", "Safari"),
            )
            if marker in agent
        ),
        None,
    )

    system = next(
        (
            name
            for marker, name in (
                ("android", "Android"),
                ("iphone", "iPhone"),
                ("ipad", "iPad"),
                ("windows", "Windows"),
                ("mac os", "macOS"),
                ("linux", "Linux"),
            )
            if marker in agent
        ),
        None,
    )

    if browser and system:
        return f"{browser} на {system}"
    return browser or system or "Неизвестное устройство"


@router.get("", response_model=SessionList, summary="Мои активные входы")
async def list_sessions(auth: AuthDep, db: SessionDep) -> SessionList:
    rows = (
        (
            await db.execute(
                select(Session)
                .where(Session.user_id == auth.user.id)
                .where(Session.revoked_at.is_(None))
                .where(Session.expires_at > utcnow())
                .order_by(Session.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    items = [
        SessionRead(
            id=row.id,
            is_current=row.id == auth.session.id,
            device=describe_device(row.user_agent),
            ip_address=row.ip_address,
            last_seen_at=row.last_seen_at,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )
        for row in rows
    ]

    return SessionList(items=items, total=len(items))


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Завершить вход",
)
async def revoke(session_id: uuid.UUID, auth: AuthDep, db: SessionDep) -> None:
    """Завершает один чужой вход.

    Текущую сессию через этот путь завершить нельзя: для выхода есть отдельная
    кнопка, которая ещё и убирает куку. Иначе человек «завершил бы» сам себя и
    остался с нерабочей сессией в браузере, не понимая, что произошло.
    """
    if session_id == auth.session.id:
        raise NotFoundError()

    row = (
        await db.execute(
            select(Session)
            .where(Session.id == session_id)
            # Чужие сессии недоступны даже владельцу: список личный.
            .where(Session.user_id == auth.user.id)
            .where(Session.revoked_at.is_(None))
        )
    ).scalar_one_or_none()

    if row is None:
        raise NotFoundError()

    await revoke_session(db, row)
