"""Фоновый аудит сайта.

Работа намеренно разделена на две задачи, которые выполняют разные воркеры.

Загрузка страницы идёт в воркере краулера: он ходит по чужим сайтам и потому
запускается с ограниченным доступом к сети и **без доступа к базе** (v0.3 §97).
Разбор и запись результата идут в обычном воркере, у которого база есть, но нет
права ходить наружу.

Если бы это была одна задача, любая ошибка в разборе чужой страницы выполнялась
бы в процессе, имеющем и доступ в интернет, и доступ к данным всех клиентов.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.base import utcnow
from ...db.session import session_scope
from ...models.audit import ModuleStatus, SiteAudit
from ...models.project import Project
from ...services.audit import (
    audit_page,
    collect_signals,
    compare_issues,
    issues_from_stored,
)
from ...services.competitors import extract_features
from ...services.crawler.fetcher import CrawlLimits, FetchError, fetch_page
from ...services.notifications import evaluate_audit, push
from ..app import celery_app
from ..runtime import run_task

logger = logging.getLogger(__name__)


@celery_app.task(name="ads_os.worker.tasks.audit.fetch_site_page")
def fetch_site_page(url: str) -> dict[str, Any]:
    """Загружает страницу. Выполняется в воркере краулера.

    Задача получает адрес аргументом, а не читает его из базы: у этого воркера
    базы нет и быть не должно.
    """
    try:
        page = asyncio.run(fetch_page(url, limits=CrawlLimits()))
    except FetchError as exc:
        return {"ok": False, "reason": exc.reason}

    return {
        "ok": True,
        "final_url": page.final_url,
        "status_code": page.status_code,
        "html": page.html,
        "elapsed_ms": page.elapsed_ms,
    }


@celery_app.task(name="ads_os.worker.tasks.audit.process_site_audit")
def process_site_audit(fetched: dict[str, Any], audit_id: str) -> str:
    """Разбирает загруженную страницу и сохраняет результат."""
    return run_task(lambda: _process(uuid.UUID(audit_id), fetched))


async def _process(audit_id: uuid.UUID, fetched: dict[str, Any]) -> str:
    async with session_scope() as session:
        audit = (
            await session.execute(select(SiteAudit).where(SiteAudit.id == audit_id))
        ).scalar_one_or_none()

        if audit is None:
            logger.warning("аудит не найден", extra={"audit_id": str(audit_id)})
            return "not_found"

        if audit.status in (ModuleStatus.COMPLETED, ModuleStatus.FAILED):
            # Очередь может доставить задачу повторно — это норма, и переделывать
            # работу не нужно (v0.3 §33).
            logger.info(
                "аудит уже обработан",
                extra={"audit_id": str(audit_id), "status": audit.status.value},
            )
            return audit.status.value

        audit.started_at = audit.started_at or utcnow()
        audit.finished_at = utcnow()

        if not fetched.get("ok"):
            audit.status = ModuleStatus.FAILED
            audit.error_reason = str(fetched.get("reason") or "страницу загрузить не удалось")
            logger.warning(
                "аудит не выполнен",
                extra={"audit_id": str(audit_id), "reason": audit.error_reason},
            )
            await _notify(session, audit, failed_reason=audit.error_reason)
            return ModuleStatus.FAILED.value

        result = audit_page(
            fetched["final_url"],
            fetched["html"],
            status_code=fetched["status_code"],
            # Задача могла быть поставлена в очередь до появления этого поля —
            # тогда времени просто нет, и проверка скорости не проводится.
            elapsed_ms=fetched.get("elapsed_ms"),
        )

        audit.status = ModuleStatus.COMPLETED
        audit.score = result.score
        audit.verdict = result.verdict.value
        audit.categories = [asdict(c) for c in result.categories]
        audit.issues = [asdict(i) for i in result.issues]
        audit.metrica_counter = result.metrica_counter
        audit.final_url = fetched["final_url"]
        # Те же признаки, что собираются у конкурентов. Сохраняются здесь, а не
        # выводятся потом из текста находок: формулировку находки однажды
        # поправят, и сравнение молча начнёт врать.
        signals = collect_signals(fetched["html"])
        audit.features = {key.value: value for key, value in extract_features(signals).items()}
        audit.selling_points = list(signals.selling_points)

        await _notify(session, audit)

        logger.info(
            "аудит завершён",
            extra={
                "audit_id": str(audit_id),
                "score": result.score,
                "verdict": result.verdict.value,
                "blocking": len(result.blocking_issues),
            },
        )
        return ModuleStatus.COMPLETED.value


def enqueue_site_audit(audit_id: uuid.UUID, url: str) -> None:
    """Ставит аудит в очередь: загрузка, затем разбор.

    Две задачи связаны цепочкой — результат первой передаётся во вторую. Так
    воркеру краулера не нужен доступ к базе, а обычному воркеру — доступ
    наружу.
    """
    from celery import chain

    chain(fetch_site_page.s(url), process_site_audit.s(str(audit_id))).delay()


async def _notify(
    session: AsyncSession, audit: SiteAudit, *, failed_reason: str | None = None
) -> None:
    """Сообщает, если состояние сайта изменилось к худшему.

    Сравнение идёт с предыдущей завершённой проверкой этого же проекта. Первая
    проверка уведомления не порождает: сообщать «у сайта есть замечания» сразу
    после того, как человек сам её запустил и смотрит на результат, незачем.
    """
    previous = (
        await session.execute(
            select(SiteAudit)
            .where(SiteAudit.project_id == audit.project_id)
            .where(SiteAudit.status == ModuleStatus.COMPLETED)
            .where(SiteAudit.id != audit.id)
            .order_by(SiteAudit.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if previous is None:
        return

    changes = (
        compare_issues(
            issues_from_stored(previous.issues or []),
            issues_from_stored(audit.issues or []),
        )
        if failed_reason is None
        else None
    )

    alert = evaluate_audit(
        changes=changes,
        score=audit.score,
        previous_score=previous.score,
        failed_reason=failed_reason,
    )
    if alert is None:
        return

    project = (
        await session.execute(select(Project).where(Project.id == audit.project_id))
    ).scalar_one_or_none()

    await push(
        session,
        alert,
        organization_id=audit.organization_id,
        project_id=audit.project_id,
        project_name=project.name if project else "проект удалён",
    )
