"""Аудит сайта: запуск и результат."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, status
from sqlalchemy import Select, select

from ...db.base import utcnow
from ...errors import AppError
from ...models import Project, SiteAudit
from ...models.audit import ModuleStatus
from ...tenancy.repository import TenantRepository
from ...worker.tasks.audit import enqueue_site_audit
from ..deps import SessionDep, TenantDep, WriteDep
from ..schemas import AuditIssueRead, AuditRead, CategoryRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["audit"])


class ProjectRepository(TenantRepository[Project]):
    model = Project


class AuditRepository(TenantRepository[SiteAudit]):
    model = SiteAudit

    def scoped(self, *, include_deleted: bool = False) -> Select[tuple[SiteAudit]]:
        # У аудита нет мягкого удаления: история хранится целиком и удаляется
        # только вместе с проектом.
        return select(self.model).where(self.model.organization_id == self.ctx.organization_id)


class WebsiteMissingError(AppError):
    status_code = 422
    error_code = "website_missing"
    message = "У проекта не указан адрес сайта"


class QueueUnavailableError(AppError):
    """Очередь задач недоступна.

    Отдельная ошибка, а не общая «внутренняя»: недоступный Redis — это не
    дефект в коде, а состояние инфраструктуры. Пользователю нужно сказать, что
    повторить попытку имеет смысл, а дежурному — что чинить.
    """

    status_code = 503
    error_code = "queue_unavailable"
    message = "Фоновые задачи временно недоступны. Попробуйте позже"
    retryable = True


class AuditAlreadyRunningError(AppError):
    """Повторный запуск при уже идущем аудите.

    Не ошибка пользователя, а защита от лишней работы: краулер ходит по чужому
    сайту, и запускать его нажатием кнопки по нескольку раз не нужно.
    """

    status_code = 409
    error_code = "audit_already_running"
    message = "Аудит уже выполняется"
    retryable = True


@router.post(
    "/{project_id}/audit",
    response_model=AuditRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запустить аудит сайта",
)
async def start_audit(project_id: uuid.UUID, session: SessionDep, ctx: WriteDep) -> AuditRead:
    project = await ProjectRepository(session, ctx).get_or_404(project_id)

    if not project.website_url:
        raise WebsiteMissingError()

    audits = AuditRepository(session, ctx)
    running = (
        await session.execute(
            audits.scoped()
            .where(SiteAudit.project_id == project_id)
            .where(SiteAudit.status.in_((ModuleStatus.QUEUED, ModuleStatus.RUNNING)))
        )
    ).scalars().first()

    if running is not None:
        raise AuditAlreadyRunningError()

    audit = SiteAudit(
        project_id=project_id,
        url=project.website_url,
        status=ModuleStatus.QUEUED,
        categories=[],
        issues=[],
    )
    await audits.add(audit)
    await session.flush()

    # Задача ставится в очередь после записи: если поставить раньше, воркер
    # может начать раньше, чем запись станет видимой.
    try:
        enqueue_site_audit(audit.id, project.website_url)
    except Exception as exc:
        # Запись удаляется явно, а не оставляется на откат транзакции. Аудит со
        # статусом «в очереди», которого в очереди нет, навсегда заблокировал бы
        # повторный запуск: проверка выше сочла бы его за идущий и вернула 409.
        # Полагаться здесь на чужую политику транзакций слишком хрупко.
        await session.delete(audit)
        await session.flush()
        logger.warning(
            "не удалось поставить аудит в очередь",
            extra={"project_id": str(project_id), "error": type(exc).__name__},
        )
        raise QueueUnavailableError() from exc

    return _to_read(audit)


@router.get(
    "/{project_id}/audit",
    response_model=AuditRead | None,
    summary="Последний аудит сайта",
)
async def get_audit(
    project_id: uuid.UUID, session: SessionDep, ctx: TenantDep
) -> AuditRead | None:
    await ProjectRepository(session, ctx).get_or_404(project_id)

    audits = AuditRepository(session, ctx)
    latest = (
        await session.execute(
            audits.scoped()
            .where(SiteAudit.project_id == project_id)
            .order_by(SiteAudit.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return _to_read(latest) if latest else None


def _to_read(audit: SiteAudit) -> AuditRead:
    return AuditRead(
        id=audit.id,
        project_id=audit.project_id,
        url=audit.url,
        final_url=audit.final_url,
        status=audit.status,
        score=audit.score,
        verdict=audit.verdict,
        metrica_counter=audit.metrica_counter,
        error_reason=audit.error_reason,
        categories=[CategoryRead(**c) for c in (audit.categories or [])],
        issues=[AuditIssueRead(**i) for i in (audit.issues or [])],
        can_launch=not any(i.get("severity") == "critical" for i in (audit.issues or [])),
        started_at=audit.started_at,
        finished_at=audit.finished_at,
        created_at=audit.created_at or utcnow(),
    )
