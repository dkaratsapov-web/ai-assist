"""Уведомления: список и отметка о прочтении."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import Select, func, select

from ...db.base import utcnow
from ...errors import AppError
from ...models import Notification
from ...tenancy.repository import TenantRepository
from ..deps import SessionDep, TenantDep, WriteDep
from ..schemas import NotificationList, NotificationRead

router = APIRouter(tags=["notifications"])


class NotificationRepository(TenantRepository[Notification]):
    model = Notification

    def scoped(self, *, include_deleted: bool = False) -> Select[tuple[Notification]]:
        return select(self.model).where(self.model.organization_id == self.ctx.organization_id)


class NotificationNotFoundError(AppError):
    status_code = 404
    error_code = "notification_not_found"
    message = "Уведомление не найдено"


@router.get("/notifications", response_model=NotificationList, summary="Уведомления")
async def list_notifications(
    session: SessionDep,
    ctx: TenantDep,
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
) -> NotificationList:
    """Что система заметила сама, от новых к старым.

    Уведомления общие для организации, а не личные. Поломка сайта касается
    всех, кто ведёт проект, и адресовать её одному человеку значило бы, что в
    его отпуск о ней не узнает никто.
    """
    stmt = (
        NotificationRepository(session, ctx)
        .scoped()
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )

    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))

    rows = list((await session.execute(stmt)).scalars().all())

    # Считается в базе, а не по выгруженному списку: непрочитанных может быть
    # больше, чем помещается в выдачу, и тогда число на колокольчике врало бы.
    unread = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.organization_id == ctx.organization_id)
                .where(Notification.is_read.is_(False))
            )
        ).scalar_one()
    )

    return NotificationList(
        items=[_to_read(row) for row in rows], total=len(rows), unread=unread
    )


@router.post(
    "/notifications/{notification_id}/read",
    response_model=NotificationRead,
    summary="Отметить прочитанным",
)
async def mark_read(
    notification_id: uuid.UUID, session: SessionDep, ctx: WriteDep
) -> NotificationRead:
    row = (
        await session.execute(
            NotificationRepository(session, ctx)
            .scoped()
            .where(Notification.id == notification_id)
        )
    ).scalar_one_or_none()

    if row is None:
        raise NotificationNotFoundError()

    if not row.is_read:
        row.is_read = True
        row.read_at = utcnow()
        await session.flush()

    return _to_read(row)


@router.post(
    "/notifications/read-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отметить прочитанными все",
)
async def mark_all_read(session: SessionDep, ctx: WriteDep) -> None:
    rows = (
        (
            await session.execute(
                NotificationRepository(session, ctx)
                .scoped()
                .where(Notification.is_read.is_(False))
            )
        )
        .scalars()
        .all()
    )

    moment = utcnow()
    for row in rows:
        row.is_read = True
        row.read_at = moment

    await session.flush()


def _to_read(row: Notification) -> NotificationRead:
    return NotificationRead(
        id=row.id,
        project_id=row.project_id,
        project_name=row.project_name,
        kind=row.kind,
        level=row.level,
        title=row.title,
        body=row.body,
        is_read=row.is_read,
        created_at=row.created_at or utcnow(),
    )
