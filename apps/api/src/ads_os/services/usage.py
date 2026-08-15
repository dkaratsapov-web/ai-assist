"""Запись потребления и проверка лимитов (v0.4 §13).

Платёжная система в MVP не подключается, но считать нужно с первого дня:
историю невозможно восстановить задним числом. Когда тарифы появятся, вопрос
«сколько этот клиент реально потребил за полгода» должен иметь ответ, а не
предположение.

Сегодня считаются страницы краулера — это настоящий расход: трафик, время
воркера и нагрузка на чужой сайт. Вызовы моделей начнут считаться в тот же
журнал, как только появится провайдер: место под них уже есть.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from ..db.base import utcnow
from ..models.organization import OrganizationPlan
from ..models.usage import UsageEvent, UsageService, UsageUnit

logger = logging.getLogger(__name__)

#: Пределы колонок. Значения обрезаются до них при записи: превышение порвало
#: бы транзакцию целиком, а вместе с ней и работу, ради которой счётчик писали.
MAX_OPERATION_LENGTH = 120
MAX_META_LENGTH = 200

#: Окно учёта. Календарный месяц не берётся намеренно: лимит, обнуляющийся
#: первого числа, позволяет израсходовать двойную норму за два дня на стыке.
USAGE_WINDOW = timedelta(days=30)


async def record(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    service: UsageService,
    operation: str,
    quantity: int | Decimal,
    unit: UsageUnit,
    project_id: uuid.UUID | None = None,
    meta: dict[str, str] | None = None,
) -> None:
    """Записывает потребление.

    Значения обрезаются до размеров колонок здесь, а не полагаются на
    аккуратность вызывающего. Причина в том, как ведёт себя база: неудачная
    запись рвёт всю транзакцию, а не только эту строку. Перехватить исключение
    недостаточно — сессия после сбоя всё равно непригодна, и вместе со строкой
    статистики пропала бы сама проверка сайта.

    Поэтому запись здесь не может не пройти: длина ограничена, число приводится
    к Decimal, а сохранение уходит вместе с окружающей транзакцией.
    """
    db.add(
        UsageEvent(
            organization_id=organization_id,
            project_id=project_id,
            service=service,
            operation=operation[:MAX_OPERATION_LENGTH],
            quantity=Decimal(quantity),
            unit=unit,
            # Персональные данные сюда не попадают: это метаданные учёта, а не
            # копия запроса (v0.4 §2.3).
            meta={key: str(value)[:MAX_META_LENGTH] for key, value in (meta or {}).items()},
        )
    )


@dataclass(frozen=True, slots=True)
class UsageSummary:
    """Потребление за окно учёта вместе с лимитом."""

    crawler_pages: int
    crawler_pages_limit: int
    ai_tokens: int
    ai_tokens_limit: int

    @property
    def crawler_share(self) -> float:
        """Доля израсходованного. Ноль при нулевом лимите — а не деление на ноль."""
        return self.crawler_pages / self.crawler_pages_limit if self.crawler_pages_limit else 0.0

    @property
    def ai_share(self) -> float:
        return self.ai_tokens / self.ai_tokens_limit if self.ai_tokens_limit else 0.0


async def summarize(db: DbSession, organization_id: uuid.UUID) -> UsageSummary:
    """Считает потребление за последние тридцать дней."""
    since = utcnow() - USAGE_WINDOW

    totals: dict[UsageService, int] = {}
    rows = await db.execute(
        select(UsageEvent.service, func.sum(UsageEvent.quantity))
        .where(UsageEvent.organization_id == organization_id)
        .where(UsageEvent.created_at >= since)
        .group_by(UsageEvent.service)
    )
    for service, total in rows:
        totals[service] = int(total or 0)

    plan = (
        await db.execute(
            select(OrganizationPlan).where(OrganizationPlan.organization_id == organization_id)
        )
    ).scalar_one_or_none()

    return UsageSummary(
        crawler_pages=totals.get(UsageService.CRAWLER, 0),
        crawler_pages_limit=plan.crawler_pages_limit if plan else 0,
        ai_tokens=totals.get(UsageService.AI, 0),
        ai_tokens_limit=plan.ai_usage_limit if plan else 0,
    )


async def crawler_limit_reached(db: DbSession, organization_id: uuid.UUID) -> bool:
    """Исчерпан ли лимит страниц краулера.

    Проверяется перед запуском проверки, а не после: смысл лимита в том, чтобы
    работа не началась, а не в том, чтобы её посчитать и всё равно выполнить.

    Организация без плана лимитом не ограничена. Это осознанно: отсутствие
    плана означает, что тарифы ещё не заведены, и превращать это в запрет
    работы значило бы сломать сервис настройкой, которой никто не делал.
    """
    summary = await summarize(db, organization_id)
    if not summary.crawler_pages_limit:
        return False
    return summary.crawler_pages >= summary.crawler_pages_limit
