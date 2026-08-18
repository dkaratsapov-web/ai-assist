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
from ...models.usage import UsageService, UsageUnit
from ...services import niches, offer, profile
from ...services.audit import (
    audit_page,
    collect_signals,
    compare_issues,
    issues_from_stored,
    looks_js_rendered,
)
from ...services.competitors import extract_features
from ...services.crawler import renderer
from ...services.crawler.fetcher import CrawlLimits, FetchError, fetch_page
from ...services.notifications import evaluate_audit, push
from ...services.usage import record as record_usage
from ..app import celery_app
from ..runtime import run_task

logger = logging.getLogger(__name__)


@celery_app.task(name="ads_os.worker.tasks.audit.fetch_site_page")
def fetch_site_page(url: str) -> dict[str, Any]:
    """Загружает страницу. Выполняется в воркере краулера.

    Задача получает адрес аргументом, а не читает его из базы: у этого воркера
    базы нет и быть не должно.
    """
    return asyncio.run(_fetch(url))


async def _fetch(url: str) -> dict[str, Any]:
    try:
        page = await fetch_page(url, limits=CrawlLimits())
    except FetchError as exc:
        return {"ok": False, "reason": exc.reason}

    html = page.html
    rendered = False

    # Пустой каркас вместо страницы означает, что содержимое собирают скрипты.
    # Разбирать его бессмысленно: получится «ни города, ни услуг, ни
    # контактов» — верно по разметке и неверно по существу, потому что
    # посетитель всё это видит.
    #
    # Браузер запускается только здесь, а не на каждой странице: он стоит
    # секунд и сотен мегабайт, и платить их за обычные сайты незачем.
    if looks_js_rendered(collect_signals(html)):
        logger.info("страница собирается скриптами, открываем браузером")
        drawn = await renderer.render(page.final_url)
        if drawn:
            html = drawn
            rendered = True

    return {
        "ok": True,
        "final_url": page.final_url,
        "status_code": page.status_code,
        "html": html,
        "elapsed_ms": page.elapsed_ms,
        # Отмечается для разбора: он иначе предупредит, что проверка неполная,
        # хотя страницу как раз дорисовали и видно всё.
        "rendered": rendered,
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

        # Ниша добавляет к разбору требования площадки: клинике нужна лицензия,
        # БАДу — оговорка «не является лекарством». Сам разбор о нишах не знает
        # намеренно — он одинаков для своего сайта и для сайта конкурента.
        niche = niches.get(
            (
                await session.execute(select(Project.niche).where(Project.id == audit.project_id))
            ).scalar_one_or_none()
        )

        result = audit_page(
            fetched["final_url"],
            fetched["html"],
            status_code=fetched["status_code"],
            # Задача могла быть поставлена в очередь до появления этого поля —
            # тогда времени просто нет, и проверка скорости не проводится.
            elapsed_ms=fetched.get("elapsed_ms"),
            extra_issues=niches.requirement_issues(niche, fetched["html"]),
            rendered=bool(fetched.get("rendered")),
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
        # Заголовок H1 предпочтительнее title: он описывает саму страницу, а
        # title часто содержит хвост с названием компании и городом.
        audit.page_title = (signals.h1[0] if signals.h1 else signals.title)[:300] or None
        audit.internal_links = [[text, href] for text, href in signals.internal_links]
        # Анкета клиента читается тем же заходом на страницу. Отдельный проход
        # ради неё был бы вторым визитом на чужой сайт за теми же данными.
        audit.client_profile = profile.extract(fetched["html"]).as_dict()
        audit.offer = offer.extract(fetched["html"]).as_dict()

        # Учёт ведётся по факту разбора, а не по факту постановки в очередь:
        # задача может не дойти до воркера, и записанная заранее страница
        # оказалась бы потреблением, которого не было.
        await record_usage(
            session,
            organization_id=audit.organization_id,
            service=UsageService.CRAWLER,
            operation="site_audit",
            quantity=1,
            unit=UsageUnit.PAGES,
            project_id=audit.project_id,
            meta={"url": audit.url[:200]},
        )

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
