"""Лента действий."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import select

from ...models import ActivityLog, Project
from ...services.activity import ACTION_LABELS
from ...tenancy.repository import TenantRepository
from ..deps import SessionDep, TenantDep
from ..schemas import ActivityList, ActivityRead

router = APIRouter(tags=["activity"])


class ProjectRepository(TenantRepository[Project]):
    model = Project


@router.get("/activity", response_model=ActivityList, summary="Журнал действий")
async def list_activity(
    session: SessionDep,
    ctx: TenantDep,
    project_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> ActivityList:
    """Кто что сделал, от новых к старым.

    Журнал общий для организации и виден всем её участникам, а не только
    владельцу. Это осознанно: смысл журнала — общая ответственность, а не
    надзор одного человека за остальными. Скрытый журнал работает как надзор.
    """
    if project_id is not None:
        # Проверяем доступ к проекту прежде, чем показывать связанные записи:
        # иначе по чужому идентификатору можно было бы прочитать чужую историю.
        await ProjectRepository(session, ctx).get_or_404(project_id)

    stmt = (
        select(ActivityLog)
        .where(ActivityLog.organization_id == ctx.organization_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )

    if project_id is not None:
        stmt = stmt.where(ActivityLog.project_id == project_id)

    rows = (await session.execute(stmt)).scalars().all()

    items = [
        ActivityRead(
            id=row.id,
            action=row.action,
            action_label=ACTION_LABELS.get(row.action, row.action.value),
            user_name=row.user_name,
            subject=row.subject,
            project_id=row.project_id,
            details={str(k): str(v) for k, v in (row.details or {}).items()},
            created_at=row.created_at,
        )
        for row in rows
    ]

    return ActivityList(items=items, total=len(items))
