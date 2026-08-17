"""Фоновый разбор сайта конкурента.

Разделение то же, что и в аудите, и по той же причине: загрузка идёт в воркере
краулера, у которого нет доступа к базе, разбор и запись — в обычном воркере,
у которого нет выхода наружу (v0.3 §97, v0.4 §20).

Загрузка переиспользуется из аудита: это буквально то же действие — скачать
страницу по адресу. Второй такой задачи быть не должно, иначе правила обхода
чужих сайтов пришлось бы поддерживать в двух местах.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from ...db.base import utcnow
from ...db.session import session_scope
from ...models.audit import ModuleStatus
from ...models.competitor import Competitor
from ...models.usage import UsageService, UsageUnit
from ...services import offer
from ...services.audit import collect_signals
from ...services.competitors import extract_features
from ...services.usage import record as record_usage
from ..app import celery_app
from ..runtime import run_task
from .audit import fetch_site_page

logger = logging.getLogger(__name__)

#: Заголовок страницы длиннее этого обрезается: он идёт в колонку таблицы, а не
#: в текст, и длинный заголовок ломает сравнение визуально.
MAX_TITLE_LENGTH = 120


@celery_app.task(name="ads_os.worker.tasks.competitors.process_competitor")
def process_competitor(fetched: dict[str, Any], competitor_id: str) -> str:
    """Разбирает загруженную страницу конкурента и сохраняет признаки."""
    return run_task(lambda: _process(uuid.UUID(competitor_id), fetched))


async def _process(competitor_id: uuid.UUID, fetched: dict[str, Any]) -> str:
    async with session_scope() as session:
        competitor = (
            await session.execute(select(Competitor).where(Competitor.id == competitor_id))
        ).scalar_one_or_none()

        if competitor is None:
            logger.warning("конкурент не найден", extra={"competitor_id": str(competitor_id)})
            return "not_found"

        competitor.checked_at = utcnow()

        if not fetched.get("ok"):
            competitor.status = ModuleStatus.FAILED
            competitor.error_reason = str(
                fetched.get("reason") or "страницу загрузить не удалось"
            )
            return ModuleStatus.FAILED.value

        signals = collect_signals(fetched["html"])
        competitor.status = ModuleStatus.COMPLETED
        competitor.error_reason = None
        competitor.features = {
            key.value: value for key, value in extract_features(signals).items()
        }
        # Условия предложения дословно: ради них сравнение и существует.
        competitor.offer = offer.extract(fetched["html"]).as_dict()

        # Страница конкурента — такой же расход, как своя: тот же трафик и то же
        # время воркера. Считать только свои значило бы занижать потребление там,
        # где его больше всего.
        await record_usage(
            session,
            organization_id=competitor.organization_id,
            service=UsageService.CRAWLER,
            operation="competitor_check",
            quantity=1,
            unit=UsageUnit.PAGES,
            project_id=competitor.project_id,
            meta={"url": competitor.url[:200]},
        )

        # Название, введённое пользователем, важнее заголовка страницы: он его
        # писал для себя и по нему узнаёт конкурента в таблице.
        if not competitor.title and signals.title:
            competitor.title = signals.title[:MAX_TITLE_LENGTH]

        logger.info(
            "конкурент разобран",
            extra={
                "competitor_id": str(competitor_id),
                "features": sum(1 for v in competitor.features.values() if v),
            },
        )
        return ModuleStatus.COMPLETED.value


def enqueue_competitor(competitor_id: uuid.UUID, url: str) -> None:
    """Ставит разбор конкурента в очередь: загрузка, затем разбор."""
    from celery import chain

    chain(fetch_site_page.s(url), process_competitor.s(str(competitor_id))).delay()
