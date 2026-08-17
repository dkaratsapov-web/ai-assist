"""Заглушка рекламной площадки.

Отвечает детерминированно: те же входные данные дают тот же ответ. Это не
украшение — на заглушке идёт разработка и проходят тесты, и «иногда другое
число» превратило бы любой упавший тест в загадку.

Данные заведомо ненастоящие и выглядят ненастоящими: рекламодатель называется
«Демонстрационный», кампании подписаны. Правдоподобные цифры на этом месте
опаснее очевидно выдуманных — по ним начнут принимать решения (v0.3 §140).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from .contracts import (
    Advertiser,
    Campaign,
    CampaignState,
    DailyStats,
    PlatformResponse,
    Usage,
)

DEMO_LOGIN = "demo-advertiser"


class MockAdapter:
    """Рекламная площадка, которой нет."""

    name = "mock"
    is_live = False

    async def advertisers(self) -> PlatformResponse:
        return PlatformResponse(
            advertisers=(
                Advertiser(
                    login=DEMO_LOGIN,
                    name="Демонстрационный рекламодатель",
                    currency="RUB",
                    can_edit=True,
                ),
            ),
            usage=Usage(),
        )

    async def campaigns(self, advertiser_login: str) -> PlatformResponse:
        return PlatformResponse(
            campaigns=(
                Campaign(
                    id=1,
                    name="Демонстрационная кампания — поиск",
                    state=CampaignState.RUNNING,
                    daily_budget=Decimal("1000.00"),
                ),
                Campaign(
                    id=2,
                    name="Демонстрационная кампания — на модерации",
                    state=CampaignState.ON_MODERATION,
                ),
            ),
            usage=Usage(),
        )

    async def daily_stats(
        self, advertiser_login: str, *, since: date, until: date
    ) -> PlatformResponse:
        """Ровный ряд по дням.

        Числа одинаковые во все дни намеренно. Нарисованная динамика — рост,
        просадка, выходные — читается как настоящая, и на графике заглушку от
        боевых данных станет не отличить.
        """
        if until < since:
            return PlatformResponse(usage=Usage())

        days = (until - since).days + 1
        return PlatformResponse(
            stats=tuple(
                DailyStats(
                    campaign_id=1,
                    on_date=since + timedelta(days=offset),
                    impressions=1000,
                    clicks=50,
                    cost=Decimal("1000.00"),
                    conversions=5,
                )
                for offset in range(days)
            ),
            usage=Usage(),
        )
