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
        pages = await _due(session)

        queued = 0
        for project, url in pages:
            audit = SiteAudit(
                organization_id=project.organization_id,
                project_id=project.id,
                url=url,
                status=ModuleStatus.QUEUED,
                categories=[],
                issues=[],
            )
            session.add(audit)
            await session.flush()

            try:
                enqueue_site_audit(audit.id, url)
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


async def _due(session: AsyncSession) -> list[tuple[Project, str]]:
    """Страницы, которым пора на проверку.

    Перепроверяются все страницы, которые когда-либо проверяли, а не только
    главная. Посадочных в кампании обычно несколько, и следить за одной значит
    не заметить, что сломалась соседняя.

    Берутся только активные проекты. Приостановленный специально выведен из
    работы — ходить по его сайту и тем более беспокоить по нему уведомлениями
    незачем.
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
    due: list[tuple[Project, str]] = []

    for project in projects:
        audits = list(
            (
                await session.execute(
                    select(SiteAudit)
                    .where(SiteAudit.project_id == project.id)
                    .order_by(SiteAudit.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

        # Последняя проверка по каждой странице. Страница, которую ни разу не
        # проверяли, в план не попадает: первую проверку человек запускает сам,
        # осознанно, иначе система пошла бы по адресу, о котором её не просили.
        latest: dict[str, SiteAudit] = {}
        for audit in audits:
            latest.setdefault(audit.url, audit)

        for url, audit in latest.items():
            # Идущая проверка означает, что об этой странице уже позаботились.
            if audit.status in (ModuleStatus.QUEUED, ModuleStatus.RUNNING):
                continue

            if (audit.created_at or utcnow()) <= threshold:
                due.append((project, url))

            if len(due) >= MAX_PER_RUN:
                return due

    return due
