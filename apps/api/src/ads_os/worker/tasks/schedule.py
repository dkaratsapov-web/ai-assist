"""Регулярные проверки.

Смысл не в самой периодичности, а в том, что сайт клиента меняется без нашего
участия. Форму убрали, счётчик Метрики слетел при переносе, домен не продлили —
всё это происходит в момент, когда никто не смотрит, а деньги продолжают
тратиться.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.base import utcnow
from ...db.session import session_scope
from ...models.audit import ModuleStatus, SiteAudit
from ...models.project import Project, ProjectStatus
from ..app import celery_app
from ..runtime import run_task
from .audit import enqueue_site_audit

logger = logging.getLogger(__name__)

#: Как часто перепроверяется сайт. Неделя — компромисс: чаще значит ходить по
#: чужому сайту без повода, реже — узнавать о поломке, когда бюджет уже ушёл.
RECHECK_INTERVAL = timedelta(days=7)

#: Сколько проверок ставится в очередь за один запуск. Ограничение защищает не
#: нас, а чужие сайты: одновременный обход сотни доменов с одного адреса
#: выглядит как атака и приводит к блокировке краулера.
MAX_PER_RUN = 25


@celery_app.task(name="ads_os.worker.tasks.schedule.recheck_sites")
def recheck_sites() -> int:
    """Ставит в очередь проверку сайтов, которые давно не проверяли."""
    return run_task(_recheck)


async def _recheck() -> int:
    async with session_scope() as session:
        projects = await _due(session)

        queued = 0
        for project in projects:
            if not project.website_url:
                continue

            audit = SiteAudit(
                organization_id=project.organization_id,
                project_id=project.id,
                url=project.website_url,
                status=ModuleStatus.QUEUED,
                categories=[],
                issues=[],
            )
            session.add(audit)
            await session.flush()

            try:
                enqueue_site_audit(audit.id, project.website_url)
            except Exception as exc:
                # Недоступная очередь — не повод оставить запись «в очереди»
                # навсегда: она заблокировала бы и ручной запуск.
                await session.delete(audit)
                await session.flush()
                logger.warning(
                    "плановая проверка не поставлена",
                    extra={"project_id": str(project.id), "error": type(exc).__name__},
                )
                continue

            queued += 1

        logger.info("плановые проверки поставлены", extra={"count": queued})
        return queued


async def _due(session: AsyncSession) -> list[Project]:
    """Проекты, которым пора на проверку.

    Берутся только активные и только с указанным сайтом. Приостановленный
    проект специально выведен из работы — ходить по его сайту и тем более
    беспокоить по нему уведомлениями незачем.
    """
    projects = list(
        (
            await session.execute(
                select(Project)
                .where(Project.status == ProjectStatus.ACTIVE)
                .where(Project.website_url.is_not(None))
                .where(Project.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )

    threshold = utcnow() - RECHECK_INTERVAL
    due: list[Project] = []

    for project in projects:
        latest = (
            await session.execute(
                select(SiteAudit)
                .where(SiteAudit.project_id == project.id)
                .order_by(SiteAudit.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        # Проект без единой проверки в план не попадает: первую человек
        # запускает сам, осознанно. Иначе система пошла бы по сайту, о котором
        # её ещё не просили.
        if latest is None:
            continue

        # Идущая проверка означает, что о проекте уже позаботились.
        if latest.status in (ModuleStatus.QUEUED, ModuleStatus.RUNNING):
            continue

        if (latest.created_at or utcnow()) <= threshold:
            due.append(project)

        if len(due) >= MAX_PER_RUN:
            break

    return due
